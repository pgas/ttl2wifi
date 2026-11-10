#pragma once

#include "../../core/serial_io.hpp"
#include <chrono>

namespace ttl2wifi::desktop {

class PosixSerialIO : public ISerialIO {
public:
    PosixSerialIO();
    ~PosixSerialIO() override;

    bool open_socket(const std::string& host, uint16_t port);
    bool open_stdio();
    void close();
    bool is_open() const { return fd_ >= 0; }

    int hw_read(uint8_t* buf, size_t max_len) override;
    void hw_write(const uint8_t* data, size_t len) override;
    void sleep_us(uint32_t us) override;
    uint32_t ticks_ms() override;

private:
    int fd_ = -1;
    bool is_socket_ = false;
    std::chrono::steady_clock::time_point start_time_;
};

} // namespace ttl2wifi::desktop

