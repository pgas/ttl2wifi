#pragma once

#include <string>
#include "../core/serial_io.hpp"
#include "../core/net_interface.hpp"
#include "../core/nav_history.hpp"

namespace ttl2wifi::protocols {

bool gopher_fetch(const std::string& url, ISerialIO& io, INetwork& net, NavHistory& nav, const std::string& query = "", bool push_history = true);

} // namespace ttl2wifi::protocols

