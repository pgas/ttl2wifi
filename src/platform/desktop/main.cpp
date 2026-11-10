#include <iostream>
#include <fstream>
#include <thread>
#include <chrono>
#include <csignal>
#include "../../core/modem.hpp"
#include "posix_io.hpp"
#include "posix_net.hpp"

namespace ttl2wifi::desktop {

class DesktopModem : public AtModem {
public:
    DesktopModem(ISerialIO& io, INetwork& net, const std::string& cfg_path = "build/sim/config.json")
        : AtModem(io, net), cfg_path_(cfg_path) {}

    void save_config() override {
        std::ofstream ofs(cfg_path_);
        if (ofs.is_open()) {
            ofs << config_.to_json();
        }
    }

    void load_config() override {
        std::ifstream ifs(cfg_path_);
        if (ifs.is_open()) {
            std::string content((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
            config_.from_json(content);
        } else {
            config_.reset_defaults();
        }
    }

    void apply_flow_mode(int) override {
        // No-op for desktop socket/stdio
    }

private:
    std::string cfg_path_;
};

} // namespace ttl2wifi::desktop

static bool g_running = true;

static void sig_handler(int) {
    g_running = false;
}

int main(int argc, char** argv) {
    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);
    signal(SIGPIPE, SIG_IGN);

    std::string connect_target = "127.0.0.1:8823";
    bool use_stdio = false;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--stdio") {
            use_stdio = true;
        } else if (arg == "--connect" && i + 1 < argc) {
            connect_target = argv[++i];
        }
    }

    ttl2wifi::desktop::PosixSerialIO io;
    ttl2wifi::desktop::PosixNetwork net;
    ttl2wifi::desktop::DesktopModem modem(io, net);

    if (use_stdio) {
        std::cout << "[Desktop] Running in stdio mode" << std::endl;
        if (!io.open_stdio()) {
            std::cerr << "Failed to open stdio" << std::endl;
            return 1;
        }
        modem.init();
        io.write_paced(modem.banner());
        while (g_running) {
            modem.tick();
            std::this_thread::sleep_for(std::chrono::microseconds(500));
        }
    } else {
        std::string host = "127.0.0.1";
        uint16_t port = 8823;
        size_t colon = connect_target.find(':');
        if (colon != std::string::npos) {
            host = connect_target.substr(0, colon);
            port = static_cast<uint16_t>(std::stoi(connect_target.substr(colon + 1)));
        }

        std::cout << "[Desktop] Connecting to SimH M2SIO bridge at " << host << ":" << port << "..." << std::endl;
        while (g_running) {
            if (!io.is_open()) {
                if (io.open_socket(host, port)) {
                    std::cout << "[Desktop] Connected to " << host << ":" << port << std::endl;
                    modem.init();
                    io.write_paced(modem.banner());
                } else {
                    std::this_thread::sleep_for(std::chrono::milliseconds(500));
                    continue;
                }
            }

            modem.tick();
            std::this_thread::sleep_for(std::chrono::microseconds(500));
        }
    }

    std::cout << "\n[Desktop] Exiting..." << std::endl;
    return 0;
}

