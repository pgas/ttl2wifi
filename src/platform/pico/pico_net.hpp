#pragma once

#include "../../core/net_interface.hpp"
#include <string>

namespace ttl2wifi::pico {

class PicoNetwork : public INetwork {
public:
    PicoNetwork();
    ~PicoNetwork() override = default;

    bool init();

    std::vector<WifiAp> wifi_scan() override;
    bool wifi_join(const std::string& ssid, const std::string& password) override;
    bool wifi_leave() override;
    WifiStatus wifi_status() override;

    bool resolve_dns(const std::string& host, std::string& ip_out) override;
    std::unique_ptr<ISocket> connect_tcp(const std::string& host, uint16_t port, uint32_t timeout_ms = 10000) override;
    std::unique_ptr<ISocket> connect_tls(const std::string& host, uint16_t port, const std::string& sni, uint32_t timeout_ms = 10000) override;
    std::string get_ntp_time(const std::string& server = "pool.ntp.org") override;

private:
    bool initialized_ = false;
};

} // namespace ttl2wifi::pico

