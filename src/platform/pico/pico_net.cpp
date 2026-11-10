#include "pico_net.hpp"
#include "../../protocols/ntp.hpp"
#include "pico/cyw43_arch.h"
#include "lwip/altcp.h"
#include "lwip/altcp_tcp.h"
#include "lwip/altcp_tls.h"
#include "lwip/dns.h"
#include "lwip/pbuf.h"
#include "mbedtls/ssl.h"
#include <cstring>
#include <vector>
#include <deque>

namespace ttl2wifi::pico {

static struct altcp_tls_config* g_tls_client_conf = nullptr;

class PicoSocket : public ISocket {
public:
    PicoSocket() = default;
    ~PicoSocket() override { close(); }

    bool connect(const ip_addr_t* ip, uint16_t port, struct altcp_tls_config* tls_conf, const std::string& sni, uint32_t timeout_ms) {
        cyw43_arch_lwip_begin();
        if (tls_conf) {
            pcb_ = altcp_tls_new(tls_conf, IPADDR_TYPE_V4);
            if (pcb_ && !sni.empty()) {
                mbedtls_ssl_context* ssl = static_cast<mbedtls_ssl_context*>(altcp_tls_context(pcb_));
                if (ssl) {
                    mbedtls_ssl_set_hostname(ssl, sni.c_str());
                }
            }
        } else {
            pcb_ = altcp_new_ip_type(nullptr, IPADDR_TYPE_V4);
        }

        if (!pcb_) {
            cyw43_arch_lwip_end();
            return false;
        }

        altcp_arg(pcb_, this);
        altcp_recv(pcb_, recv_callback);
        altcp_err(pcb_, err_callback);

        connected_ = false;
        error_ = false;

        err_t err = altcp_connect(pcb_, ip, port, connected_callback);
        cyw43_arch_lwip_end();

        if (err != ERR_OK) {
            close();
            return false;
        }

        uint32_t start = to_ms_since_boot(get_absolute_time());
        while (!connected_ && !error_) {
            cyw43_arch_poll();
            sleep_us(100);
            if ((to_ms_since_boot(get_absolute_time()) - start) > timeout_ms) {
                close();
                return false;
            }
        }

        return connected_;
    }

    int send(const uint8_t* data, size_t len) override {
        if (!pcb_ || !connected_) return -1;
        cyw43_arch_lwip_begin();
        size_t sent = 0;
        while (sent < len) {
            u16_t can_send = altcp_sndbuf(pcb_);
            if (can_send == 0) {
                cyw43_arch_lwip_end();
                cyw43_arch_poll();
                sleep_us(100);
                cyw43_arch_lwip_begin();
                continue;
            }
            u16_t chunk = (len - sent) > can_send ? can_send : static_cast<u16_t>(len - sent);
            err_t err = altcp_write(pcb_, data + sent, chunk, TCP_WRITE_FLAG_COPY);
            if (err != ERR_OK) break;
            altcp_output(pcb_);
            sent += chunk;
        }
        cyw43_arch_lwip_end();
        return static_cast<int>(sent);
    }

    int recv(uint8_t* buf, size_t max_len, uint32_t timeout_ms) override {
        if (!connected_ && rx_buf_.empty()) return -1;

        uint32_t start = to_ms_since_boot(get_absolute_time());
        while (rx_buf_.empty() && connected_) {
            if (timeout_ms == 0) return 0;
            cyw43_arch_poll();
            sleep_us(100);
            if ((to_ms_since_boot(get_absolute_time()) - start) > timeout_ms) {
                return 0; // timeout
            }
        }

        size_t count = 0;
        while (!rx_buf_.empty() && count < max_len) {
            buf[count++] = rx_buf_.front();
            rx_buf_.pop_front();
        }
        return static_cast<int>(count);
    }

    void close() override {
        cyw43_arch_lwip_begin();
        if (pcb_) {
            altcp_arg(pcb_, nullptr);
            altcp_recv(pcb_, nullptr);
            altcp_err(pcb_, nullptr);
            altcp_close(pcb_);
            pcb_ = nullptr;
        }
        cyw43_arch_lwip_end();
        connected_ = false;
        rx_buf_.clear();
    }

    bool is_connected() const override { return connected_ && pcb_ != nullptr; }
    bool has_data() override { return !rx_buf_.empty(); }

    void on_connected() { connected_ = true; }
    void on_error() { error_ = true; connected_ = false; pcb_ = nullptr; }

    void on_recv(struct altcp_pcb* pcb, struct pbuf* p) {
        if (!p) {
            // Remote closed connection
            connected_ = false;
            return;
        }
        struct pbuf* q = p;
        while (q) {
            const auto* data = reinterpret_cast<const uint8_t*>(q->payload);
            for (u16_t i = 0; i < q->len; ++i) {
                rx_buf_.push_back(data[i]);
            }
            q = q->next;
        }
        altcp_recved(pcb, p->tot_len);
        pbuf_free(p);
    }

private:
    static err_t connected_callback(void* arg, struct altcp_pcb*, err_t err) {
        auto* self = static_cast<PicoSocket*>(arg);
        if (self && err == ERR_OK) self->on_connected();
        return ERR_OK;
    }

    static err_t recv_callback(void* arg, struct altcp_pcb* pcb, struct pbuf* p, err_t) {
        auto* self = static_cast<PicoSocket*>(arg);
        if (self) self->on_recv(pcb, p);
        return ERR_OK;
    }

    static void err_callback(void* arg, err_t) {
        auto* self = static_cast<PicoSocket*>(arg);
        if (self) self->on_error();
    }

    struct altcp_pcb* pcb_ = nullptr;
    volatile bool connected_ = false;
    volatile bool error_ = false;
    std::deque<uint8_t> rx_buf_;
};

PicoNetwork::PicoNetwork() = default;

bool PicoNetwork::init() {
    if (initialized_) return true;
    if (cyw43_arch_init() != 0) {
        return false;
    }
    cyw43_arch_enable_sta_mode();
    initialized_ = true;
    return true;
}

static int scan_result_cb(void* env, const cyw43_ev_scan_result_t* result) {
    if (!result) return 0;
    auto* list = reinterpret_cast<std::vector<WifiAp>*>(env);
    WifiAp ap;
    ap.ssid = reinterpret_cast<const char*>(result->ssid);
    ap.rssi = result->rssi;
    ap.channel = result->channel;
    uint32_t auth = static_cast<uint32_t>(result->auth_mode);
    if (auth == CYW43_AUTH_OPEN) {
        ap.security = "OPEN";
    } else if (auth == CYW43_AUTH_WPA_TKIP_PSK) {
        ap.security = "WPA";
    } else if (auth == CYW43_AUTH_WPA2_AES_PSK) {
        ap.security = "WPA2";
    } else if (auth == CYW43_AUTH_WPA2_MIXED_PSK) {
        ap.security = "WPA2-MIXED";
    } else {
        ap.security = "SECURED";
    }
    list->push_back(ap);
    return 0;
}

std::vector<WifiAp> PicoNetwork::wifi_scan() {
    std::vector<WifiAp> list;
    if (!initialized_) return list;

    cyw43_wifi_scan_options_t scan_options = {0};
    cyw43_wifi_scan(&cyw43_state, &scan_options, &list, scan_result_cb);
    while (cyw43_wifi_scan_active(&cyw43_state)) {
        cyw43_arch_poll();
        sleep_ms(100);
    }
    return list;
}

bool PicoNetwork::wifi_join(const std::string& ssid, const std::string& password) {
    if (!initialized_) return false;
    uint32_t auth = password.empty() ? CYW43_AUTH_OPEN : CYW43_AUTH_WPA2_AES_PSK;
    int err = cyw43_arch_wifi_connect_timeout_ms(ssid.c_str(), password.c_str(), auth, 30000);
    return err == 0;
}

bool PicoNetwork::wifi_leave() {
    if (!initialized_) return false;
    cyw43_wifi_leave(&cyw43_state, CYW43_ITF_STA);
    return true;
}

WifiStatus PicoNetwork::wifi_status() {
    WifiStatus st;
    if (!initialized_) return st;

    int link_status = cyw43_tcpip_link_status(&cyw43_state, CYW43_ITF_STA);
    st.connected = (link_status == CYW43_LINK_UP);

    if (st.connected) {
        const ip4_addr_t* ip = netif_ip4_addr(netif_default);
        const ip4_addr_t* netmask = netif_ip4_netmask(netif_default);
        const ip4_addr_t* gw = netif_ip4_gw(netif_default);

        char buf[32];
        ip4addr_ntoa_r(ip, buf, sizeof(buf));
        st.ip = buf;

        ip4addr_ntoa_r(netmask, buf, sizeof(buf));
        st.netmask = buf;

        ip4addr_ntoa_r(gw, buf, sizeof(buf));
        st.gateway = buf;

        const ip_addr_t* dns = dns_getserver(0);
        ipaddr_ntoa_r(dns, buf, sizeof(buf));
        st.dns = buf;

        uint8_t mac[6];
        cyw43_wifi_get_mac(&cyw43_state, CYW43_ITF_STA, mac);
        char mac_str[20];
        snprintf(mac_str, sizeof(mac_str), "%02X:%02X:%02X:%02X:%02X:%02X",
                 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
        st.mac = mac_str;

        int32_t rssi = 0;
        cyw43_wifi_get_rssi(&cyw43_state, &rssi);
        st.rssi = static_cast<int>(rssi);
    }
    return st;
}

struct DnsResult {
    ip_addr_t ip;
    bool done = false;
    bool success = false;
};

static void dns_found_cb(const char*, const ip_addr_t* ipaddr, void* arg) {
    auto* res = static_cast<DnsResult*>(arg);
    if (ipaddr) {
        res->ip = *ipaddr;
        res->success = true;
    }
    res->done = true;
}

bool PicoNetwork::resolve_dns(const std::string& host, std::string& ip_out) {
    if (!initialized_) return false;
    DnsResult res;
    cyw43_arch_lwip_begin();
    err_t err = dns_gethostbyname(host.c_str(), &res.ip, dns_found_cb, &res);
    cyw43_arch_lwip_end();

    if (err == ERR_OK) {
        char buf[32];
        ipaddr_ntoa_r(&res.ip, buf, sizeof(buf));
        ip_out = buf;
        return true;
    }

    if (err == ERR_INPROGRESS) {
        uint32_t start = to_ms_since_boot(get_absolute_time());
        while (!res.done) {
            cyw43_arch_poll();
            sleep_us(100);
            if ((to_ms_since_boot(get_absolute_time()) - start) > 10000) {
                return false;
            }
        }
        if (res.success) {
            char buf[32];
            ipaddr_ntoa_r(&res.ip, buf, sizeof(buf));
            ip_out = buf;
            return true;
        }
    }

    return false;
}

std::unique_ptr<ISocket> PicoNetwork::connect_tcp(const std::string& host, uint16_t port, uint32_t timeout_ms) {
    if (!initialized_) return nullptr;
    std::string ip_str;
    if (!resolve_dns(host, ip_str)) {
        return nullptr;
    }

    ip_addr_t ip;
    ipaddr_aton(ip_str.c_str(), &ip);

    auto sock = std::make_unique<PicoSocket>();
    if (!sock->connect(&ip, port, nullptr, "", timeout_ms)) {
        return nullptr;
    }
    return sock;
}

std::unique_ptr<ISocket> PicoNetwork::connect_tls(const std::string& host, uint16_t port, const std::string& sni, uint32_t timeout_ms) {
    if (!initialized_) return nullptr;
    std::string ip_str;
    if (!resolve_dns(host, ip_str)) {
        return nullptr;
    }

    ip_addr_t ip;
    ipaddr_aton(ip_str.c_str(), &ip);

    if (!g_tls_client_conf) {
        g_tls_client_conf = altcp_tls_create_config_client(nullptr, 0);
    }
    if (!g_tls_client_conf) {
        return nullptr;
    }

    auto sock = std::make_unique<PicoSocket>();
    std::string server_sni = sni.empty() ? host : sni;
    if (!sock->connect(&ip, port, g_tls_client_conf, server_sni, timeout_ms)) {
        return nullptr;
    }
    return sock;
}

std::string PicoNetwork::get_ntp_time(const std::string& server) {
    std::string s = protocols::ntp_sync_host(server);
    if (!s.empty()) return s;
    return "NTP sync error";
}

} // namespace ttl2wifi::pico
