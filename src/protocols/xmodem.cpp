#include "xmodem.hpp"
#include <vector>

namespace ttl2wifi::protocols {

constexpr uint8_t X_SOH = 0x01;
constexpr uint8_t X_EOT = 0x04;
constexpr uint8_t X_ACK = 0x06;
constexpr uint8_t X_NAK = 0x15;
constexpr uint8_t X_CAN = 0x18;
constexpr uint8_t X_CPM_EOF = 0x1A;

static uint16_t calc_crc16(const uint8_t* ptr, size_t count) {
    uint16_t crc = 0;
    while (count-- > 0) {
        crc = crc ^ (static_cast<uint16_t>(*ptr++) << 8);
        for (int i = 0; i < 8; ++i) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc = crc << 1;
            }
        }
    }
    return crc;
}

static uint8_t calc_checksum(const uint8_t* ptr, size_t count) {
    uint8_t sum = 0;
    while (count-- > 0) {
        sum += *ptr++;
    }
    return sum;
}

bool xmodem_send_stream(const uint8_t* data, size_t len, ISerialIO& io, uint32_t delay_us) {
    io.flush_rx();

    // 1. Wait for receiver handshake ('C' for CRC or NAK for additive checksum)
    bool use_crc = false;
    uint32_t start_ms = io.ticks_ms();
    while (true) {
        int b = io.read_raw_byte(1000);
        if (b == 'C') {
            use_crc = true;
            break;
        }
        if (b == X_NAK) {
            use_crc = false;
            break;
        }
        if (b == X_CAN) {
            return false;
        }
        if ((io.ticks_ms() - start_ms) > 60000) { // 60s timeout waiting for CP/M XM.COM
            return false;
        }
    }

    // Small pause and flush any duplicate handshake bytes
    io.sleep_us(50000);
    io.flush_rx();

    // 2. Transmit 128-byte packets
    uint8_t packet_num = 1;
    size_t offset = 0;
    uint8_t pkt[133]; // SOH + blk + ~blk + 128 bytes + 1 or 2 bytes CRC/chk

    while (offset < len) {
        size_t chunk_len = std::min<size_t>(128, len - offset);
        pkt[0] = X_SOH;
        pkt[1] = packet_num;
        pkt[2] = ~packet_num;

        // Copy data and pad with CPM EOF (0x1A)
        for (size_t i = 0; i < 128; ++i) {
            if (i < chunk_len) {
                pkt[3 + i] = data[offset + i];
            } else {
                pkt[3 + i] = X_CPM_EOF;
            }
        }

        size_t pkt_len = 3 + 128;
        if (use_crc) {
            uint16_t crc = calc_crc16(&pkt[3], 128);
            pkt[pkt_len++] = static_cast<uint8_t>(crc >> 8);
            pkt[pkt_len++] = static_cast<uint8_t>(crc & 0xFF);
        } else {
            pkt[pkt_len++] = calc_checksum(&pkt[3], 128);
        }

        // Retry sending block up to 10 times
        bool block_acked = false;
        for (int retry = 0; retry < 10; ++retry) {
            io.write_paced_bytes(pkt, pkt_len, delay_us);
            int resp = io.read_raw_byte(3000);
            if (resp == X_ACK) {
                block_acked = true;
                break;
            }
            if (resp == X_CAN) {
                return false;
            }
            // Retry on NAK or timeout
        }

        if (!block_acked) {
            return false;
        }

        offset += chunk_len;
        packet_num++;
    }

    // 3. Send EOT
    for (int retry = 0; retry < 10; ++retry) {
        uint8_t eot = X_EOT;
        io.write_paced_bytes(&eot, 1, delay_us);
        int resp = io.read_raw_byte(3000);
        if (resp == X_ACK) {
            io.sleep_us(300000);
            io.write_paced("\r\n+XMODEM: Transfer complete\r\n");
            return true;
        }
    }
    return false;
}

bool xmodem_download_and_send(const std::string& url, ISerialIO& io, INetwork& net, uint32_t delay_us) {
    // Basic HTTP fetch to buffer, then XMODEM stream to host
    std::string host;
    uint16_t port = 80;
    std::string path = "/";
    bool is_https = false;

    std::string u = url;
    if (u.find("http://") == 0) {
        u = u.substr(7);
        port = 80;
    } else if (u.find("https://") == 0) {
        u = u.substr(8);
        port = 443;
        is_https = true;
    }

    size_t slash = u.find('/');
    if (slash != std::string::npos) {
        host = u.substr(0, slash);
        path = u.substr(slash);
    } else {
        host = u;
    }

    size_t colon = host.find(':');
    if (colon != std::string::npos) {
        port = static_cast<uint16_t>(std::strtoul(host.c_str() + colon + 1, nullptr, 10));
        host = host.substr(0, colon);
    }

    io.write_paced("+XMODEM: Connecting to " + host + "...\r\n");
    std::unique_ptr<ISocket> sock;
    if (is_https) {
        sock = net.connect_tls(host, port, host, 10000);
    } else {
        sock = net.connect_tcp(host, port, 10000);
    }

    if (!sock) {
        io.write_paced("+XMODEM: Connection failed\r\n");
        return false;
    }

    std::string req = "GET " + path + " HTTP/1.0\r\nHost: " + host + "\r\nConnection: close\r\n\r\n";
    sock->send_str(req);

    std::vector<uint8_t> body;
    std::vector<uint8_t> raw_buf;
    uint8_t chunk[512];
    bool header_done = false;

    while (true) {
        int n = sock->recv(chunk, sizeof(chunk), 5000);
        if (n <= 0) break;
        raw_buf.insert(raw_buf.end(), chunk, chunk + n);

        if (!header_done) {
            // Find \r\n\r\n
            for (size_t i = 3; i < raw_buf.size(); ++i) {
                if (raw_buf[i - 3] == '\r' && raw_buf[i - 2] == '\n' &&
                    raw_buf[i - 1] == '\r' && raw_buf[i] == '\n') {
                    header_done = true;
                    body.insert(body.end(), raw_buf.begin() + i + 1, raw_buf.end());
                    raw_buf.clear();
                    break;
                }
            }
        } else {
            body.insert(body.end(), chunk, chunk + n);
        }
    }
    sock->close();

    io.write_paced("+XMODEM: Downloaded " + std::to_string(body.size()) +
                   " bytes. Start receiver now (waiting up to 60s for NAK/'C')...\r\n");
    return xmodem_send_stream(body.data(), body.size(), io, delay_us);
}

} // namespace ttl2wifi::protocols

