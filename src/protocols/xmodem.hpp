#pragma once

#include <string>
#include <cstdint>
#include "../core/serial_io.hpp"
#include "../core/net_interface.hpp"

namespace ttl2wifi::protocols {

bool xmodem_send_stream(const uint8_t* data, size_t len, ISerialIO& io, uint32_t delay_us = 250);
bool xmodem_download_and_send(const std::string& url, ISerialIO& io, INetwork& net, uint32_t delay_us = 250);

} // namespace ttl2wifi::protocols

