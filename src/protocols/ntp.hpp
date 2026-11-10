#pragma once

#include <string>
#include <cstdint>
#include "../core/net_interface.hpp"

namespace ttl2wifi::protocols {

struct NtpDateTime {
    int year = 1970;
    int month = 1;
    int day = 1;
    int dotw = 4; // Day of week (0=Sun..6=Sat)
    int hour = 0;
    int min = 0;
    int sec = 0;
    uint32_t unix_time = 0;
};

// Query SNTP server (UDP port 123)
std::string ntp_sync_host(const std::string& host = "pool.ntp.org", NtpDateTime* dt_out = nullptr);

} // namespace ttl2wifi::protocols
