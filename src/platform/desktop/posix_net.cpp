#include "posix_net.hpp"
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include "../../protocols/ntp.hpp"
#include <ctime>
#include <cstring>
#include <openssl/ssl.h>
#include <openssl/err.h>

namespace ttl2wifi::desktop {

class PosixTcpSocket : public ISocket {
public:
    explicit PosixTcpSocket(int fd, SSL* ssl = nullptr, SSL_CTX* ctx = nullptr)
        : fd_(fd), ssl_(ssl), ssl_ctx_(ctx) {}

    ~PosixTcpSocket() override {
        close();
    }

    int send(const uint8_t* data, size_t len) override {
        if (!is_connected()) return -1;
        if (ssl_) {
            int ret = SSL_write(ssl_, data, static_cast<int>(len));
            return ret > 0 ? ret : -1;
        } else {
            ssize_t ret = ::send(fd_, data, len, 0);
            return ret >= 0 ? static_cast<int>(ret) : -1;
        }
    }

    int recv(uint8_t* buf, size_t max_len, uint32_t timeout_ms) override {
        if (!is_connected()) return -1;

        if (timeout_ms > 0) {
            struct pollfd pfd{};
            pfd.fd = fd_;
            pfd.events = POLLIN;
            int pr = ::poll(&pfd, 1, static_cast<int>(timeout_ms));
            if (pr <= 0) return 0; // timeout or error
        }

        if (ssl_) {
            int ret = SSL_read(ssl_, buf, static_cast<int>(max_len));
            if (ret <= 0) {
                int err = SSL_get_error(ssl_, ret);
                if (err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE) {
                    return 0;
                }
                close();
                return 0;
            }
            return ret;
        } else {
            ssize_t ret = ::recv(fd_, buf, max_len, timeout_ms == 0 ? MSG_DONTWAIT : 0);
            if (ret < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) return 0;
                close();
                return 0;
            }
            if (ret == 0) {
                close();
            }
            return static_cast<int>(ret);
        }
    }

    void close() override {
        if (ssl_) {
            SSL_shutdown(ssl_);
            SSL_free(ssl_);
            ssl_ = nullptr;
        }
        if (ssl_ctx_) {
            SSL_CTX_free(ssl_ctx_);
            ssl_ctx_ = nullptr;
        }
        if (fd_ >= 0) {
            ::close(fd_);
            fd_ = -1;
        }
    }

    bool is_connected() const override {
        return fd_ >= 0;
    }

    bool has_data() override {
        if (!is_connected()) return false;
        if (ssl_ && SSL_pending(ssl_) > 0) return true;
        struct pollfd pfd{};
        pfd.fd = fd_;
        pfd.events = POLLIN;
        return ::poll(&pfd, 1, 0) > 0;
    }

private:
    int fd_ = -1;
    SSL* ssl_ = nullptr;
    SSL_CTX* ssl_ctx_ = nullptr;
};

PosixNetwork::PosixNetwork() {
    SSL_library_init();
    SSL_load_error_strings();
    OpenSSL_add_all_algorithms();
}

PosixNetwork::~PosixNetwork() = default;

std::vector<WifiAp> PosixNetwork::wifi_scan() {
    return {
        {"HostBridge_5G", -45, 36, "WPA2-PSK"},
        {"HostBridge_2G", -50, 6, "WPA2-PSK"},
        {"RetroNet", -65, 1, "OPEN"}
    };
}

bool PosixNetwork::wifi_join(const std::string& ssid, const std::string&) {
    wifi_ssid_ = ssid;
    wifi_connected_ = true;
    return true;
}

bool PosixNetwork::wifi_leave() {
    wifi_connected_ = false;
    return true;
}

WifiStatus PosixNetwork::wifi_status() {
    WifiStatus st;
    st.connected = wifi_connected_;
    if (st.connected) {
        st.ip = "127.0.0.1";
        st.netmask = "255.255.255.0";
        st.gateway = "127.0.0.1";
        st.dns = "1.1.1.1";
        st.mac = "AA:BB:CC:DD:EE:FF";
        st.rssi = -42;
    }
    return st;
}

bool PosixNetwork::resolve_dns(const std::string& host, std::string& ip_out) {
    struct addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host.c_str(), nullptr, &hints, &res) != 0 || !res) {
        return false;
    }
    char ipstr[INET_ADDRSTRLEN];
    auto* ipv4 = reinterpret_cast<struct sockaddr_in*>(res->ai_addr);
    inet_ntop(AF_INET, &(ipv4->sin_addr), ipstr, INET_ADDRSTRLEN);
    ip_out = ipstr;
    freeaddrinfo(res);
    return true;
}

std::unique_ptr<ISocket> PosixNetwork::connect_tcp(const std::string& host, uint16_t port, uint32_t timeout_ms) {
    struct addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    std::string port_str = std::to_string(port);
    if (getaddrinfo(host.c_str(), port_str.c_str(), &hints, &res) != 0 || !res) {
        return nullptr;
    }

    int s = ::socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (s < 0) {
        freeaddrinfo(res);
        return nullptr;
    }

    // Connect with timeout
    int flags = fcntl(s, F_GETFL, 0);
    fcntl(s, F_SETFL, flags | O_NONBLOCK);

    int rc = ::connect(s, res->ai_addr, res->ai_addrlen);
    freeaddrinfo(res);

    if (rc < 0 && errno == EINPROGRESS) {
        struct pollfd pfd{};
        pfd.fd = s;
        pfd.events = POLLOUT;
        int pr = ::poll(&pfd, 1, static_cast<int>(timeout_ms));
        if (pr <= 0) {
            ::close(s);
            return nullptr;
        }
        int so_error = 0;
        socklen_t len = sizeof(so_error);
        getsockopt(s, SOL_SOCKET, SO_ERROR, &so_error, &len);
        if (so_error != 0) {
            ::close(s);
            return nullptr;
        }
    } else if (rc < 0) {
        ::close(s);
        return nullptr;
    }

    return std::make_unique<PosixTcpSocket>(s);
}

std::unique_ptr<ISocket> PosixNetwork::connect_tls(const std::string& host, uint16_t port, const std::string& sni, uint32_t timeout_ms) {
    auto tcp_sock = connect_tcp(host, port, timeout_ms);
    if (!tcp_sock) return nullptr;

    SSL_CTX* ctx = SSL_CTX_new(TLS_client_method());
    if (!ctx) return nullptr;

    SSL* ssl = SSL_new(ctx);
    if (!ssl) {
        SSL_CTX_free(ctx);
        return nullptr;
    }

    if (!sni.empty()) {
        SSL_set_tlsext_host_name(ssl, sni.c_str());
    }

    // Wrap raw socket fd into PosixTcpSocket
    // To do that, we extract fd
    auto* raw_posix = static_cast<PosixTcpSocket*>(tcp_sock.release());
    // PosixTcpSocket private fd, or we pass ownership
    // Instead of leaking, let's reopen or pass fd
    int fd = -1;
    // Let's connect directly:
    SSL_CTX_free(ctx);
    SSL_free(ssl);
    delete raw_posix;

    // Directly create TLS socket
    struct addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    std::string port_str = std::to_string(port);
    if (getaddrinfo(host.c_str(), port_str.c_str(), &hints, &res) != 0 || !res) {
        return nullptr;
    }
    int s = ::socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (s < 0) {
        freeaddrinfo(res);
        return nullptr;
    }

    if (::connect(s, res->ai_addr, res->ai_addrlen) < 0) {
        freeaddrinfo(res);
        ::close(s);
        return nullptr;
    }
    freeaddrinfo(res);

    ctx = SSL_CTX_new(TLS_client_method());
    ssl = SSL_new(ctx);
    if (!sni.empty()) {
        SSL_set_tlsext_host_name(ssl, sni.c_str());
    }
    SSL_set_fd(ssl, s);
    if (SSL_connect(ssl) <= 0) {
        SSL_free(ssl);
        SSL_CTX_free(ctx);
        ::close(s);
        return nullptr;
    }

    return std::make_unique<PosixTcpSocket>(s, ssl, ctx);
}

std::string PosixNetwork::get_ntp_time(const std::string& server) {
    std::string s = protocols::ntp_sync_host(server);
    if (!s.empty()) return s;
    // Fallback to local clock if network fails
    time_t now = time(nullptr);
    struct tm* gmt = gmtime(&now);
    char buf[64];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S UTC", gmt);
    return std::string(buf);
}

} // namespace ttl2wifi::desktop

