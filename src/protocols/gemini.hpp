#pragma once

#include <string>
#include "../core/serial_io.hpp"
#include "../core/net_interface.hpp"
#include "../core/nav_history.hpp"

namespace ttl2wifi::protocols {

bool gemini_fetch(const std::string& url, ISerialIO& io, INetwork& net, NavHistory& nav, bool push_history = true, int max_redirects = 5);

} // namespace ttl2wifi::protocols

