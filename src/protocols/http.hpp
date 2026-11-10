#pragma once

#include <string>
#include "../core/serial_io.hpp"
#include "../core/net_interface.hpp"

namespace ttl2wifi::protocols {

bool http_fetch(const std::string& url, ISerialIO& io, INetwork& net);

} // namespace ttl2wifi::protocols

