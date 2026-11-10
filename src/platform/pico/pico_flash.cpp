#include "pico_flash.hpp"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include <cstring>
#include <vector>

namespace ttl2wifi::pico {

static constexpr uint32_t MAGIC = 0x54325731; // 'T2W1'

struct FlashHeader {
    uint32_t magic;
    uint32_t length;
};

bool flash_save_config(const std::string& json_str) {
    if (json_str.size() > (FLASH_SECTOR_SIZE - sizeof(FlashHeader))) {
        return false;
    }

    std::vector<uint8_t> buffer(FLASH_SECTOR_SIZE, 0xFF);
    auto* hdr = reinterpret_cast<FlashHeader*>(buffer.data());
    hdr->magic = MAGIC;
    hdr->length = static_cast<uint32_t>(json_str.size());
    std::memcpy(buffer.data() + sizeof(FlashHeader), json_str.data(), json_str.size());

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, buffer.data(), FLASH_SECTOR_SIZE);
    restore_interrupts(ints);

    return true;
}

std::string flash_load_config() {
    const uint8_t* flash_target_contents = reinterpret_cast<const uint8_t*>(XIP_BASE + FLASH_CONFIG_OFFSET);
    const auto* hdr = reinterpret_cast<const FlashHeader*>(flash_target_contents);

    if (hdr->magic != MAGIC || hdr->length > (FLASH_SECTOR_SIZE - sizeof(FlashHeader))) {
        return "";
    }

    return std::string(reinterpret_cast<const char*>(flash_target_contents + sizeof(FlashHeader)), hdr->length);
}

} // namespace ttl2wifi::pico

