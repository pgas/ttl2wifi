#include "config.hpp"
#include <sstream>

namespace ttl2wifi {

void ModemConfig::reset_defaults() {
    wifi_ssid.clear();
    wifi_password.clear();
    echo = true;
    flow_mode = 3;
    page_lines = 0;
    baud = 115200;
}

static std::string escape_json(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '"') out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else if (c == '\t') out += "\\t";
        else out += c;
    }
    return out;
}

std::string ModemConfig::to_json() const {
    std::ostringstream ss;
    ss << "{\n"
       << "  \"wifi_ssid\": \"" << escape_json(wifi_ssid) << "\",\n"
       << "  \"wifi_password\": \"" << escape_json(wifi_password) << "\",\n"
       << "  \"echo\": " << (echo ? "true" : "false") << ",\n"
       << "  \"flow_mode\": " << flow_mode << ",\n"
       << "  \"page_lines\": " << page_lines << ",\n"
       << "  \"baud\": " << baud << "\n"
       << "}\n";
    return ss.str();
}

static std::string extract_string_value(const std::string& json, const std::string& key) {
    std::string pattern = "\"" + key + "\":";
    size_t pos = json.find(pattern);
    if (pos == std::string::npos) return "";
    pos += pattern.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' || json[pos] == '\r' || json[pos] == '\n')) {
        pos++;
    }
    if (pos < json.size() && json[pos] == '"') {
        pos++;
        size_t end = json.find('"', pos);
        if (end != std::string::npos) {
            return json.substr(pos, end - pos);
        }
    }
    return "";
}

static long extract_int_value(const std::string& json, const std::string& key, long def_val) {
    std::string pattern = "\"" + key + "\":";
    size_t pos = json.find(pattern);
    if (pos == std::string::npos) return def_val;
    pos += pattern.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' || json[pos] == '\r' || json[pos] == '\n')) {
        pos++;
    }
    char* endptr = nullptr;
    long val = std::strtol(json.c_str() + pos, &endptr, 10);
    return (endptr != json.c_str() + pos) ? val : def_val;
}

static bool extract_bool_value(const std::string& json, const std::string& key, bool def_val) {
    std::string pattern = "\"" + key + "\":";
    size_t pos = json.find(pattern);
    if (pos == std::string::npos) return def_val;
    pos += pattern.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t' || json[pos] == '\r' || json[pos] == '\n')) {
        pos++;
    }
    if (json.compare(pos, 4, "true") == 0) return true;
    if (json.compare(pos, 5, "false") == 0) return false;
    return def_val;
}

bool ModemConfig::from_json(const std::string& json_str) {
    if (json_str.empty()) return false;
    wifi_ssid = extract_string_value(json_str, "wifi_ssid");
    wifi_password = extract_string_value(json_str, "wifi_password");
    echo = extract_bool_value(json_str, "echo", true);
    flow_mode = static_cast<int>(extract_int_value(json_str, "flow_mode", 3));
    page_lines = static_cast<int>(extract_int_value(json_str, "page_lines", 0));
    baud = static_cast<uint32_t>(extract_int_value(json_str, "baud", 115200));
    return true;
}

} // namespace ttl2wifi

