#include "http.hpp"

namespace ttl2wifi::protocols {

bool http_fetch(const std::string& url, ISerialIO& io, INetwork& net) {
    std::string u = url;
    bool is_https = false;
    uint16_t port = 80;

    if (u.find("http://") == 0) {
        u = u.substr(7);
        port = 80;
    } else if (u.find("https://") == 0) {
        u = u.substr(8);
        port = 443;
        is_https = true;
    }

    std::string host;
    std::string path = "/";
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

    io.reset_pager();
    std::unique_ptr<ISocket> sock;
    if (is_https) {
        sock = net.connect_tls(host, port, host, 10000);
    } else {
        sock = net.connect_tcp(host, port, 10000);
    }

    if (!sock) {
        io.write_line_paged("ERROR: Failed to connect to " + host);
        return false;
    }

    std::string req = "GET " + path + " HTTP/1.0\r\nHost: " + host + "\r\nUser-Agent: ttl2wifi/2.0\r\nConnection: close\r\n\r\n";
    sock->send_str(req);

    std::string line_buf;
    uint8_t ch;
    bool in_headers = true;

    while (true) {
        if (io.check_abort()) {
            io.write_paced("\r\n^C Aborted\r\n");
            break;
        }
        int n = sock->recv(&ch, 1, 10000);
        if (n <= 0) break;

        if (ch == '\r') continue;
        if (ch != '\n') {
            line_buf += static_cast<char>(ch);
            continue;
        }

        if (in_headers) {
            if (line_buf.empty()) {
                in_headers = false;
            }
        } else {
            if (!io.write_line_paged(line_buf)) break;
        }
        line_buf.clear();
    }

    if (!line_buf.empty() && !in_headers) {
        io.write_line_paged(line_buf);
    }
    sock->close();
    return true;
}

} // namespace ttl2wifi::protocols

