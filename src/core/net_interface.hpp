#pragma once

#include <string>
#include <vector>
#include <memory>
#include <cstdint>
#include <cstddef>

namespace ttl2wifi {

class ISocket {
public:
    virtual ~ISocket() = default;
    virtual int send(const uint8_t* data, size_t len) = 0;
    virtual int recv(uint8_t* buf, size_t max_len, uint32_t timeout_ms = 0) = 0;
    virtual void close() = 0;
    virtual bool is_connected() const = 0;
    virtual bool has_data() = 0;

    int send_str(const std::string& str) {
        return send(reinterpret_cast<const uint8_t*>(str.data()), str.size());
    }
};

struct WifiAp {
    std::string ssid;
    int rssi = 0;
    int channel = 0;
    std::string security;
};

struct WifiStatus {
    bool connected = false;
    std::string ip;
    std::string netmask;
    std::string gateway;
    std::string dns;
    std::string mac;
    int rssi = 0;
};

class INetwork {
public:
    virtual ~INetwork() = default;

    virtual std::vector<WifiAp> wifi_scan() = 0;
    virtual bool wifi_join(const std::string& ssid, const std::string& password) = 0;
    virtual bool wifi_leave() = 0;
    virtual WifiStatus wifi_status() = 0;

    virtual bool resolve_dns(const std::string& host, std::string& ip_out) = 0;
    virtual std::unique_ptr<ISocket> connect_tcp(const std::string& host, uint16_t port, uint32_t timeout_ms = 10000) = 0;
    virtual std::unique_ptr<ISocket> connect_tls(const std::string& host, uint16_t port, const std::string& sni, uint32_t timeout_ms = 10000) = 0;
    virtual std::string get_ntp_time(const std::string& server = "pool.ntp.org") = 0;
};

} // namespace ttl2wifi

