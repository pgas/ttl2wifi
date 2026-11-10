#pragma once

#include <string>
#include <cstdint>

namespace ttl2wifi {

struct ModemConfig {
    std::string wifi_ssid;
    std::string wifi_password;
    bool echo = true;
    int flow_mode = 3;    // 0: None, 3: HW RTS/CTS, 4: SW XON/XOFF
    int page_lines = 0;   // 0: continuous
    uint32_t baud = 115200;

    std::string to_json() const;
    bool from_json(const std::string& json_str);
    void reset_defaults();
};

} // namespace ttl2wifi

