#include "modem.hpp"
#include "../protocols/gopher.hpp"
#include "../protocols/gemini.hpp"
#include "../protocols/http.hpp"
#include "../protocols/xmodem.hpp"
#include <algorithm>
#include <cctype>

namespace ttl2wifi {

static const char* HELP_TEXT =
    "=== TTL2WiFi AT Command Reference ===\r\n"
    "Classic Hayes Commands:\r\n"
    "  AT                 - Attention check (OK)\r\n"
    "  ATI                - Modem info, MAC, IP & settings\r\n"
    "  AT? / AT+HELP      - Show this command summary\r\n"
    "  ATE0 / ATE1        - Command echo Off / On\r\n"
    "  AT&K0 / &K3 / &K4  - Flow control: None / HW RTS-CTS / SW XON-XOFF\r\n"
    "  AT+PAGE=<lines>    - Screen pager (e.g. AT+PAGE=22, or 0=off)\r\n"
    "  AT&W / ATZ / AT&F  - Save / Reload / Factory-reset config\r\n"
    "  ATDT<host>:<port>  - Dial raw TCP stream (+++ to escape)\r\n"
    "  ATDS<host>:<port>  - Dial TLS stream (+++ to escape)\r\n"
    "  ATO / ATH          - Return to online socket / Hang up\r\n"
    "Wi-Fi & Network Commands:\r\n"
    "  AT+WSCAN           - Scan Wi-Fi access points\r\n"
    "  AT+WJOIN=\"ssid\",\"pw\" - Connect to Wi-Fi network\r\n"
    "  AT+WLEAVE / +WSTAT - Disconnect / Show Wi-Fi & IP status\r\n"
    "  AT+WDNS=\"host\"     - DNS lookup\r\n"
    "  AT+TIME            - Sync RTC via NTP & print UTC time\r\n"
    "Protocols, Browsing & File Transfer:\r\n"
    "  AT+GOPHER=\"url\"    - Fetch Gopher menu/file (numbers links [1]..[N])\r\n"
    "  AT+GEMINI=\"url\"    - Fetch Gemini page over TLS (numbers links [1]..[N])\r\n"
    "  AT+GO=<n>[,\"qry\"]  - Follow numbered link [n] (or AT+BACK / AT+LINKS)\r\n"
    "  AT+HTTPGET=\"url\"   - Fetch HTTP/HTTPS URL\r\n"
    "  AT+XMODEM=\"url\"    - Download URL via 128B XMODEM (CRC/Checksum)\r\n";

static std::string to_upper(const std::string& s) {
    std::string out = s;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return std::toupper(c);
    });
    return out;
}

static std::string trim(const std::string& s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

std::vector<std::string> AtModem::parse_quoted_args(const std::string& s) {
    std::vector<std::string> args;
    std::string cur;
    bool in_q = false;
    for (char ch : s) {
        if (ch == '"') {
            in_q = !in_q;
        } else if (ch == ',' && !in_q) {
            args.push_back(trim(cur));
            cur.clear();
        } else {
            cur += ch;
        }
    }
    if (!cur.empty() || (!s.empty() && s.back() == ',')) {
        args.push_back(trim(cur));
    }
    return args;
}

bool AtModem::parse_host_port(const std::string& target, uint16_t def_port, std::string& host_out, uint16_t& port_out) {
    std::string t = trim(target);
    if (t.empty()) return false;
    size_t colon = t.find(':');
    if (colon != std::string::npos) {
        host_out = t.substr(0, colon);
        char* endp = nullptr;
        unsigned long p = std::strtoul(t.c_str() + colon + 1, &endp, 10);
        port_out = (endp != t.c_str() + colon + 1 && p > 0 && p <= 65535) ? static_cast<uint16_t>(p) : def_port;
    } else {
        host_out = t;
        port_out = def_port;
    }
    return !host_out.empty();
}

AtModem::AtModem(ISerialIO& io, INetwork& net)
    : io_(io), net_(net) {}

void AtModem::init() {
    load_config();
    io_.set_page_lines(config_.page_lines);
    apply_flow_mode(config_.flow_mode);
    mode_ = ModemMode::COMMAND;
    cmd_buf_.clear();
}

std::string AtModem::flow_desc() const {
    switch (config_.flow_mode) {
        case 0: return "&K0 (None)";
        case 3: return "&K3 (HW RTS/CTS)";
        case 4: return "&K4 (SW XON/XOFF)";
        default: return "Custom";
    }
}

std::string AtModem::banner() const {
    return std::string("\r\nTTL2WiFi v") + VERSION + " Hayes AT / Protocol Bridge Ready (115200 8N1, " +
           flow_desc() + ")\r\nType AT? for commands.\r\nOK\r\n";
}

void AtModem::reply(const std::string& text) {
    io_.write_paced(text + "\r\n");
}

void AtModem::write_info() {
    io_.write_line_paged("TTL2WiFi v" + std::string(VERSION) + " (C++ Native)");
    io_.write_line_paged("Flow Control: " + flow_desc());
    io_.write_line_paged("Pager: " + (config_.page_lines > 0 ? (std::to_string(config_.page_lines) + " lines") : "Off"));
    io_.write_line_paged("Local Echo: " + std::string(config_.echo ? "On (E1)" : "Off (E0)"));

    WifiStatus st = net_.wifi_status();
    io_.write_line_paged("Wi-Fi Status: " + std::string(st.connected ? "Connected" : "Disconnected"));
    if (st.connected) {
        io_.write_line_paged("  SSID: " + config_.wifi_ssid);
        io_.write_line_paged("  IP: " + st.ip);
        io_.write_line_paged("  Netmask: " + st.netmask);
        io_.write_line_paged("  Gateway: " + st.gateway);
        io_.write_line_paged("  DNS: " + st.dns);
        io_.write_line_paged("  MAC: " + st.mac);
        io_.write_line_paged("  RSSI: " + std::to_string(st.rssi) + " dBm");
    }
    reply("OK");
}

void AtModem::dial_stream(const std::string& target, bool use_tls) {
    std::string host;
    uint16_t port;
    if (!parse_host_port(target, use_tls ? 443 : 23, host, port)) {
        reply("ERROR");
        return;
    }

    close_socket();
    reply("DIALING " + host + ":" + std::to_string(port) + "...");

    if (use_tls) {
        active_sock_ = net_.connect_tls(host, port, host, 10000);
    } else {
        active_sock_ = net_.connect_tcp(host, port, 10000);
    }

    if (!active_sock_ || !active_sock_->is_connected()) {
        close_socket();
        reply("NO CARRIER");
        return;
    }

    peer_desc_ = (use_tls ? "TLS " : "") + host + ":" + std::to_string(port);
    mode_ = ModemMode::ONLINE;
    plus_count_ = 0;
    last_rx_ms_ = io_.ticks_ms();
    reply("CONNECT " + peer_desc_);
}

void AtModem::close_socket() {
    if (active_sock_) {
        active_sock_->close();
        active_sock_.reset();
    }
    mode_ = ModemMode::COMMAND;
}

void AtModem::follow_url(const std::string& url, const std::string& query, bool push_history) {
    if (url.rfind("gemini://", 0) == 0) {
        std::string full_url = url;
        if (!query.empty()) full_url += "?" + query;
        protocols::gemini_fetch(full_url, io_, net_, nav_, push_history);
    } else if (url.rfind("http://", 0) == 0 || url.rfind("https://", 0) == 0) {
        protocols::http_fetch(url, io_, net_);
    } else if (url.rfind("telnet://", 0) == 0) {
        std::string target = url.substr(9);
        std::string host;
        uint16_t port = 23;
        parse_host_port(target, 23, host, port);
        io_.write_paced("+TELNET: Use ZTELNET or ATDT for " + host + ":" + std::to_string(port) + "\r\n");
    } else {
        protocols::gopher_fetch(url, io_, net_, nav_, query, push_history);
    }
    reply("OK");
}

void AtModem::tick() {
    if (mode_ == ModemMode::COMMAND) {
        int b = io_.read_raw_byte(5);
        if (b < 0) return;

        if (b == '\r' || b == '\n') {
            if (config_.echo) io_.write("\r\n");
            handle_command(cmd_buf_);
            cmd_buf_.clear();
            return;
        }

        if (b == ASCII_BS || b == ASCII_DEL) {
            if (!cmd_buf_.empty()) {
                cmd_buf_.pop_back();
                if (config_.echo) io_.write("\b \b");
            }
            return;
        }

        if (b >= 32 && b <= 126) {
            cmd_buf_ += static_cast<char>(b);
            if (config_.echo) {
                uint8_t ch = static_cast<uint8_t>(b);
                io_.write(&ch, 1);
            }
        }
    } else if (mode_ == ModemMode::ONLINE) {
        // Forward socket RX -> UART TX
        uint8_t sock_buf[256];
        int n = active_sock_ ? active_sock_->recv(sock_buf, sizeof(sock_buf), 0) : -1;
        if (n > 0) {
            io_.write_paced(sock_buf, n);
        } else if (n == 0 && active_sock_ && !active_sock_->is_connected()) {
            close_socket();
            reply("NO CARRIER");
            return;
        }

        // Forward UART RX -> Socket TX (monitoring for +++ escape)
        uint32_t now = io_.ticks_ms();
        int b = io_.read_raw_byte(0);

        if (b >= 0) {
            if (b == '+') {
                if (plus_count_ == 0 && (now - last_rx_ms_ >= 1000)) {
                    plus_count_ = 1;
                    last_plus_ms_ = now;
                } else if ((plus_count_ == 1 || plus_count_ == 2) && (now - last_plus_ms_ <= 1000)) {
                    plus_count_++;
                    last_plus_ms_ = now;
                } else {
                    // broken guard time, flush pluses
                    for (int i = 0; i < plus_count_; ++i) {
                        uint8_t p = '+';
                        active_sock_->send(&p, 1);
                    }
                    plus_count_ = 0;
                    uint8_t ch = static_cast<uint8_t>(b);
                    active_sock_->send(&ch, 1);
                }
            } else {
                for (int i = 0; i < plus_count_; ++i) {
                    uint8_t p = '+';
                    active_sock_->send(&p, 1);
                }
                plus_count_ = 0;
                uint8_t ch = static_cast<uint8_t>(b);
                active_sock_->send(&ch, 1);
            }
            last_rx_ms_ = now;
        } else {
            // Check guard time after 3 pluses
            if (plus_count_ == 3 && (now - last_plus_ms_ >= 1000)) {
                plus_count_ = 0;
                mode_ = ModemMode::COMMAND;
                reply("OK");
            }
        }
    }
}

void AtModem::handle_command(const std::string& line) {
    std::string raw = trim(line);
    if (raw.empty()) return;

    std::string up = to_upper(raw);
    if (up == "HELP") {
        io_.write_paced(HELP_TEXT);
        reply("OK");
        return;
    }

    if (up.rfind("AT", 0) != 0) {
        reply("ERROR (Commands must start with AT; type AT? for help)");
        return;
    }

    std::string body = trim(raw.substr(2));
    std::string body_up = to_upper(body);

    if (body_up.empty()) {
        reply("OK");
    } else if (body_up == "?" || body_up == "+HELP") {
        io_.write_paced(HELP_TEXT);
        reply("OK");
    } else if (body_up == "I" || body_up == "I0" || body_up == "I1") {
        write_info();
    } else if (body_up == "E0" || body_up == "E1") {
        config_.echo = (body_up == "E1");
        reply("OK");
    } else if (body_up == "&K0" || body_up == "&K3" || body_up == "&K4") {
        config_.flow_mode = body_up[2] - '0';
        apply_flow_mode(config_.flow_mode);
        reply("OK");
    } else if (body_up.rfind("+PAGE=", 0) == 0) {
        char* endp = nullptr;
        long lines = std::strtol(body.c_str() + 6, &endp, 10);
        if (endp != body.c_str() + 6) {
            config_.page_lines = std::max(0L, lines);
            io_.set_page_lines(config_.page_lines);
            reply("OK");
        } else {
            reply("ERROR");
        }
    } else if (body_up == "&W") {
        save_config();
        reply("OK");
    } else if (body_up == "Z") {
        load_config();
        io_.set_page_lines(config_.page_lines);
        apply_flow_mode(config_.flow_mode);
        reply("OK");
    } else if (body_up == "&F") {
        config_.reset_defaults();
        io_.set_page_lines(config_.page_lines);
        apply_flow_mode(config_.flow_mode);
        reply("OK");
    } else if (body_up == "O") {
        if (active_sock_ && active_sock_->is_connected()) {
            mode_ = ModemMode::ONLINE;
            plus_count_ = 0;
            reply("CONNECT " + peer_desc_);
        } else {
            reply("NO CARRIER");
        }
    } else if (body_up == "H" || body_up == "H0") {
        close_socket();
        reply("NO CARRIER");
    } else if (body_up.rfind("DT", 0) == 0) {
        dial_stream(body.substr(2), false);
    } else if (body_up.rfind("DS", 0) == 0) {
        dial_stream(body.substr(2), true);
    } else if (body_up.rfind("D", 0) == 0) {
        dial_stream(body.substr(1), false);
    } else if (body_up == "+WSCAN") {
        io_.write_paced("+WSCAN: Scanning...\r\n");
        auto aps = net_.wifi_scan();
        for (const auto& ap : aps) {
            char line_buf[128];
            snprintf(line_buf, sizeof(line_buf), "  ch%-2d  %4d dBm  sec=%-10s  %s\r\n",
                     ap.channel, ap.rssi, ap.security.c_str(), ap.ssid.c_str());
            io_.write_paced(line_buf);
        }
        reply("OK");
    } else if (body_up.rfind("+WJOIN=", 0) == 0) {
        auto args = parse_quoted_args(body.substr(7));
        if (!args.empty() && !args[0].empty()) {
            std::string pw = (args.size() > 1) ? args[1] : "";
            io_.write_paced("+WJOIN: Connecting to " + args[0] + "...\r\n");
            if (net_.wifi_join(args[0], pw)) {
                config_.wifi_ssid = args[0];
                config_.wifi_password = pw;
                reply("OK");
            } else {
                reply("ERROR: Failed to connect to " + args[0]);
            }
        } else {
            reply("ERROR: Usage AT+WJOIN=\"ssid\",\"password\"");
        }
    } else if (body_up == "+WLEAVE") {
        net_.wifi_leave();
        reply("OK");
    } else if (body_up == "+WSTAT") {
        auto st = net_.wifi_status();
        if (st.connected) {
            io_.write_paced("+WSTAT: Connected\r\n");
            io_.write_paced("  IP: " + st.ip + "\r\n");
            io_.write_paced("  Netmask: " + st.netmask + "\r\n");
            io_.write_paced("  Gateway: " + st.gateway + "\r\n");
            io_.write_paced("  DNS: " + st.dns + "\r\n");
            io_.write_paced("  MAC: " + st.mac + "\r\n");
            io_.write_paced("  RSSI: " + std::to_string(st.rssi) + " dBm\r\n");
        } else {
            io_.write_paced("+WSTAT: Disconnected\r\n");
        }
        reply("OK");
    } else if (body_up.rfind("+WDNS=", 0) == 0) {
        auto args = parse_quoted_args(body.substr(6));
        if (!args.empty() && !args[0].empty()) {
            std::string ip;
            if (net_.resolve_dns(args[0], ip)) {
                io_.write_paced("+WDNS: " + args[0] + " -> " + ip + "\r\n");
                reply("OK");
            } else {
                reply("ERROR: DNS resolution failed");
            }
        } else {
            reply("ERROR: Usage AT+WDNS=\"host\"");
        }
    } else if (body_up == "+TIME") {
        std::string t = net_.get_ntp_time();
        if (!t.empty()) {
            io_.write_paced("+TIME: " + t + "\r\n");
            reply("OK");
        } else {
            reply("ERROR: NTP sync failed");
        }
    } else if (body_up.rfind("+GOPHER=", 0) == 0) {
        auto args = parse_quoted_args(body.substr(8));
        if (!args.empty()) {
            protocols::gopher_fetch(args[0], io_, net_, nav_);
            reply("OK");
        } else {
            reply("ERROR: Usage AT+GOPHER=\"url\"");
        }
    } else if (body_up.rfind("+GEMINI=", 0) == 0) {
        auto args = parse_quoted_args(body.substr(8));
        if (!args.empty()) {
            protocols::gemini_fetch(args[0], io_, net_, nav_);
            reply("OK");
        } else {
            reply("ERROR: Usage AT+GEMINI=\"url\"");
        }
    } else if (body_up.rfind("+GO=", 0) == 0) {
        auto args = parse_quoted_args(body.substr(4));
        if (!args.empty()) {
            char* endp = nullptr;
            unsigned long idx = std::strtoul(args[0].c_str(), &endp, 10);
            const auto* link = (endp != args[0].c_str()) ? nav_.get_link(idx) : nullptr;
            if (link) {
                std::string q = (args.size() > 1) ? args[1] : "";
                io_.write_paced("+GO [" + std::to_string(idx) + "]: " + link->url + "\r\n");
                follow_url(link->url, q, true);
            } else {
                reply("ERROR: Link [" + args[0] + "] out of range");
            }
        } else {
            reply("ERROR: Usage AT+GO=<n>[,\"query\"]");
        }
    } else if (body_up == "+BACK") {
        if (nav_.has_history()) {
            std::string prev = nav_.pop_history();
            io_.write_paced("+BACK: " + prev + "\r\n");
            follow_url(prev, "", false);
        } else {
            reply("ERROR: History is empty");
        }
    } else if (body_up == "+LINKS") {
        io_.reset_pager();
        if (nav_.links().empty()) {
            io_.write_paced("+LINKS: None\r\n");
        } else {
            for (size_t i = 0; i < nav_.links().size(); ++i) {
                const auto& lnk = nav_.links()[i];
                char buf[64];
                snprintf(buf, sizeof(buf), "[%2zu:%-3s] ", i + 1, lnk.item_type.c_str());
                if (!io_.write_line_paged(std::string(buf) + lnk.label + " -> " + lnk.url)) break;
            }
        }
        reply("OK");
    } else if (body_up.rfind("+HTTPGET=", 0) == 0) {
        auto args = parse_quoted_args(body.substr(9));
        if (!args.empty()) {
            protocols::http_fetch(args[0], io_, net_);
            reply("OK");
        } else {
            reply("ERROR: Usage AT+HTTPGET=\"url\"");
        }
    } else if (body_up.rfind("+XMODEM=", 0) == 0) {
        auto args = parse_quoted_args(body.substr(8));
        if (!args.empty()) {
            uint32_t delay_us = 250;
            if (args.size() > 1) {
                char* endp = nullptr;
                unsigned long d = std::strtoul(args[1].c_str(), &endp, 10);
                if (endp != args[1].c_str()) delay_us = static_cast<uint32_t>(d);
            }
            if (protocols::xmodem_download_and_send(args[0], io_, net_, delay_us)) {
                reply("OK");
            } else {
                reply("ERROR: XMODEM transfer failed");
            }
        } else {
            reply("ERROR: Usage AT+XMODEM=\"url\"[,delay]");
        }
    } else {
        reply("ERROR: Unknown command AT" + body);
    }
}

} // namespace ttl2wifi

