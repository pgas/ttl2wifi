#include "gemini.hpp"
#include <sstream>

namespace ttl2wifi::protocols {

static void parse_gemini_url(const std::string& url, std::string& host, uint16_t& port, std::string& path) {
    std::string u = url;
    if (u.find("gemini://") == 0) {
        u = u.substr(9);
    }
    port = 1965;
    size_t slash = u.find('/');
    std::string hostport;
    if (slash != std::string::npos) {
        hostport = u.substr(0, slash);
        path = u.substr(slash);
    } else {
        hostport = u;
        path = "/";
    }
    size_t colon = hostport.find(':');
    if (colon != std::string::npos) {
        port = static_cast<uint16_t>(std::strtoul(hostport.c_str() + colon + 1, nullptr, 10));
        host = hostport.substr(0, colon);
    } else {
        host = hostport;
    }
}

static std::string resolve_relative_url(const std::string& base_url, const std::string& target) {
    if (target.find("://") != std::string::npos) {
        return target;
    }
    std::string host;
    uint16_t port;
    std::string path;
    parse_gemini_url(base_url, host, port, path);

    std::string base_prefix = "gemini://" + host + (port != 1965 ? (":" + std::to_string(port)) : "");

    if (!target.empty() && target[0] == '/') {
        return base_prefix + target;
    }
    // Relative to current dir
    size_t last_slash = path.rfind('/');
    std::string dir = (last_slash != std::string::npos) ? path.substr(0, last_slash + 1) : "/";
    return base_prefix + dir + target;
}

bool gemini_fetch(const std::string& initial_url, ISerialIO& io, INetwork& net, NavHistory& nav, bool push_history, int max_redirects) {
    std::string current_url = initial_url;
    if (current_url.find("gemini://") != 0) {
        current_url = "gemini://" + current_url;
    }

    for (int redir = 0; redir <= max_redirects; ++redir) {
        std::string host;
        uint16_t port = 1965;
        std::string path = "/";
        parse_gemini_url(current_url, host, port, path);

        io.reset_pager();
        auto sock = net.connect_tls(host, port, host, 10000);
        if (!sock) {
            io.write_line_paged("ERROR: TLS connection failed to " + host);
            return false;
        }

        std::string req = current_url + "\r\n";
        sock->send_str(req);

        // Read header line (<STATUS> <META>\r\n)
        std::string header_line;
        uint8_t ch;
        while (true) {
            int n = sock->recv(&ch, 1, 10000);
            if (n <= 0) break;
            if (ch == '\r') continue;
            if (ch == '\n') break;
            header_line += static_cast<char>(ch);
        }

        if (header_line.size() < 2) {
            io.write_line_paged("ERROR: Empty or invalid Gemini header");
            sock->close();
            return false;
        }

        int status = std::atoi(header_line.substr(0, 2).c_str());
        std::string meta = header_line.size() > 3 ? header_line.substr(3) : "";

        // 1x: INPUT
        if (status >= 10 && status <= 19) {
            sock->close();
            std::string prompt = meta.empty() ? "Input: " : (meta + ": ");
            io.write_paced(prompt);
            std::string user_input = io.read_line(true);
            if (user_input.empty()) return false;
            std::string query_url = current_url + "?" + user_input;
            return gemini_fetch(query_url, io, net, nav, push_history, max_redirects);
        }

        // 3x: REDIRECT
        if (status >= 30 && status <= 39) {
            sock->close();
            current_url = resolve_relative_url(current_url, meta);
            continue;
        }

        // 4x / 5x: ERROR
        if (status >= 40) {
            sock->close();
            io.write_line_paged("ERROR " + std::to_string(status) + ": " + meta);
            return false;
        }

        // 2x: SUCCESS
        nav.set_page(current_url, push_history);

        bool in_pre = false;
        std::string line_buf;

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

            // Render line
            if (line_buf.rfind("```", 0) == 0) {
                in_pre = !in_pre;
                if (!line_buf.substr(3).empty()) {
                    io.write_line_paged("--- " + line_buf.substr(3) + " ---");
                }
            } else if (in_pre) {
                if (!io.write_line_paged(line_buf)) break;
            } else if (line_buf.rfind("=>", 0) == 0) {
                // Link
                std::string link_body = line_buf.substr(2);
                while (!link_body.empty() && (link_body[0] == ' ' || link_body[0] == '\t')) {
                    link_body = link_body.substr(1);
                }
                size_t space = link_body.find_first_of(" \t");
                std::string link_target;
                std::string link_label;
                if (space != std::string::npos) {
                    link_target = link_body.substr(0, space);
                    link_label = link_body.substr(space + 1);
                    while (!link_label.empty() && (link_label[0] == ' ' || link_label[0] == '\t')) {
                        link_label = link_label.substr(1);
                    }
                } else {
                    link_target = link_body;
                    link_label = link_target;
                }

                std::string resolved = resolve_relative_url(current_url, link_target);
                size_t idx = nav.add_link(resolved, link_label, "GMI");

                char prefix[32];
                snprintf(prefix, sizeof(prefix), "[%2zu:GMI] ", idx);
                if (!io.write_line_paged(std::string(prefix) + link_label)) break;
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

    io.write_line_paged("ERROR: Too many redirects");
    return false;
}

} // namespace ttl2wifi::protocols

