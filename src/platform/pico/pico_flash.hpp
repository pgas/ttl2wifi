#pragma once

#include <string>
#include <cstdint>

namespace ttl2wifi::pico {

// Use the last 4KB sector of 2MB flash for persistent config
constexpr uint32_t FLASH_CONFIG_OFFSET = 0x1FF000;

bool flash_save_config(const std::string& json_str);
std::string flash_load_config();

} // namespace ttl2wifi::pico

