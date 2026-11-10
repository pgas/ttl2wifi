#pragma once

#include <string>
#include <cstdint>

namespace ttl2wifi {

struct ModemConfig {
    std::string wifi_ssid;
    std::string wifi_password;
    bool echo = true;
    int flow_mode = 0;    // 0: None (Default), 3: HW RTS/CTS, 4: SW XON/XOFF
    int page_lines = 0;   // 0: continuous
    uint32_t baud = 115200;
    uint32_t char_delay_us = 500;  // 500us inter-char pacing (safe for slow Z180)
    uint32_t line_delay_ms = 20;   // 20ms newline pacing (safe for CP/M screen scroll)

    std::string to_json() const;
    bool from_json(const std::string& json_str);
    void reset_defaults();
};

} // namespace ttl2wifi

