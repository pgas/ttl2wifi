#include "gopher.hpp"
#include <sstream>
#include <map>

namespace ttl2wifi::protocols {

static const std::map<char, std::string> GOPHER_TYPES = {
    {'0', "TXT"},
    {'1', "DIR"},
    {'7', "QRY"},
    {'8', "TEL"},
    {'9', "BIN"},
    {'g', "GIF"},
    {'I', "IMG"},
    {'h', "HTM"},
    {'s', "SND"},
};

static std::vector<std::string> split_string(const std::string& s, char delim) {
    std::vector<std::string> tokens;
    std::string token;
    std::istringstream token_stream(s);
    while (std::getline(token_stream, token, delim)) {
        tokens.push_back(token);
    }
    return tokens;
}

bool gopher_fetch(const std::string& url_raw, ISerialIO& io, INetwork& net, NavHistory& nav, const std::string& query, bool push_history) {
    std::string u = url_raw;
    if (u.find("gopher://") == 0) {
        u = u.substr(9);
    }

    std::string hostport;
    std::string selector;
    char item_type = '1';

    size_t slash = u.find('/');
    if (slash != std::string::npos) {
        hostport = u.substr(0, slash);
        selector = u.substr(slash + 1);
        if (!selector.empty() && selector.size() >= 1 && (selector.size() == 1 || selector[1] == '/')) {
            item_type = selector[0];
            selector = selector.substr(1);
        } else if (!selector.empty() && selector[0] != '/') {
            selector = "/" + selector;
        }
    } else {
        hostport = u;
    }

    std::string host = hostport;
    uint16_t port = 70;
    size_t colon = host.find(':');
    if (colon != std::string::npos) {
        port = static_cast<uint16_t>(std::strtoul(host.c_str() + colon + 1, nullptr, 10));
        host = host.substr(0, colon);
    }

    std::string canon_url = "gopher://" + hostport + "/" + item_type + selector;
    nav.set_page(canon_url, push_history);

    io.reset_pager();
    auto sock = net.connect_tcp(host, port, 10000);
    if (!sock) {
        io.write_line_paged("ERROR: Failed to connect to " + host);
        return false;
    }

    std::string req = selector;
    if (!query.empty()) {
        req += "\t" + query;
    }
    req += "\r\n";
    sock->send_str(req);

    std::string line_buf;
    uint8_t ch;
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

        // We have a complete line
        if (line_buf == ".") {
            break;
        }

        if (line_buf.find('\t') != std::string::npos && (item_type == '1' || item_type == '7')) {
            char t_ch = line_buf[0];
            std::string rest = line_buf.substr(1);
            auto parts = split_string(rest, '\t');
            std::string display = parts.size() > 0 ? parts[0] : "";
            std::string sel = parts.size() > 1 ? parts[1] : "";
            std::string h = parts.size() > 2 ? parts[2] : host;
            std::string p = parts.size() > 3 ? parts[3] : "70";

            if (t_ch == 'i') {
                if (!io.write_line_paged("       " + display)) break;
            } else {
                std::string tag = std::string(1, t_ch);
                auto it = GOPHER_TYPES.find(t_ch);
                if (it != GOPHER_TYPES.end()) tag = it->second;

                std::string hp = (p != "70") ? (h + ":" + p) : h;
                std::string link_url;
                if (sel.find("URL:") == 0) {
                    link_url = sel.substr(4);
                } else if (t_ch == '8') {
                    link_url = "telnet://" + hp;
                } else {
                    if (sel.empty() || sel[0] != '/') sel = "/" + sel;
                    link_url = "gopher://" + hp + "/" + t_ch + sel;
                }

                size_t idx = nav.add_link(link_url, display, std::string(1, t_ch));
                char prefix[32];
                snprintf(prefix, sizeof(prefix), "[%2zu:%-3s] ", idx, tag.c_str());
                if (!io.write_line_paged(std::string(prefix) + display)) break;
            }
        } else {
            if (!io.write_line_paged(line_buf)) break;
        }
        line_buf.clear();
    }

    if (!line_buf.empty()) {
        io.write_line_paged(line_buf);
    }
    sock->close();
    return true;
}

} // namespace ttl2wifi::protocols

