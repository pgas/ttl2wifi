#pragma once

#include <string>
#include <vector>
#include <memory>
#include "serial_io.hpp"
#include "net_interface.hpp"
#include "nav_history.hpp"
#include "config.hpp"

namespace ttl2wifi {

enum class ModemMode {
    COMMAND,
    ONLINE
};

class AtModem {
public:
    static constexpr const char* VERSION = "2.0.0-cpp";

    AtModem(ISerialIO& io, INetwork& net);
    virtual ~AtModem() = default;

    void init();
    void tick(); // Call periodically in main loop

    void handle_command(const std::string& line);
    void reply(const std::string& text = "OK");
    void write_info();
    std::string banner() const;
    std::string flow_desc() const;

    // Platform hooks
    virtual void save_config() = 0;
    virtual void load_config() = 0;
    virtual void apply_flow_mode(int mode) = 0;

    ModemMode mode() const { return mode_; }
    ModemConfig& config() { return config_; }
    NavHistory& nav() { return nav_; }

protected:
    void dial_stream(const std::string& target, bool use_tls);
    void close_socket();
    void follow_url(const std::string& url, const std::string& query = "", bool push_history = true);

    // Helpers
    static std::vector<std::string> parse_quoted_args(const std::string& s);
    static bool parse_host_port(const std::string& target, uint16_t def_port, std::string& host_out, uint16_t& port_out);

    ISerialIO& io_;
    INetwork& net_;
    ModemConfig config_;
    NavHistory nav_;
    ModemMode mode_ = ModemMode::COMMAND;

    std::unique_ptr<ISocket> active_sock_;
    std::string peer_desc_;

    // Command line buffer in COMMAND mode
    std::string cmd_buf_;

    // Escape sequence state machine for ONLINE mode ('+++')
    int plus_count_ = 0;
    uint32_t last_rx_ms_ = 0;
    uint32_t last_plus_ms_ = 0;
};

} // namespace ttl2wifi

