#pragma once

#include <cstdint>
#include <cstddef>
#include <string>
#include <vector>
#include <deque>

namespace ttl2wifi {

constexpr uint8_t ASCII_XON  = 0x11; // Ctrl-Q
constexpr uint8_t ASCII_XOFF = 0x13; // Ctrl-S
constexpr uint8_t ASCII_ETX  = 0x03; // Ctrl-C
constexpr uint8_t ASCII_BS   = 0x08; // Backspace
constexpr uint8_t ASCII_DEL  = 0x7F; // Delete

class ISerialIO {
public:
    virtual ~ISerialIO() = default;

    // Platform-specific hooks
    virtual int hw_read(uint8_t* buf, size_t max_len) = 0;
    virtual void hw_write(const uint8_t* data, size_t len) = 0;
    virtual void sleep_us(uint32_t us) = 0;
    virtual uint32_t ticks_ms() = 0;

    // Pager & Flow control settings
    void set_page_lines(int lines) { page_lines_ = lines; }
    int page_lines() const { return page_lines_; }
    void reset_pager() { cur_line_ = 0; aborted_ = false; }
    bool is_aborted() const { return aborted_; }
    void set_aborted(bool val) { aborted_ = val; }

    // Character / text output
    void write(const std::string& str);
    void write(const uint8_t* data, size_t len);
    void write_paced(const std::string& str);
    void write_paced(const uint8_t* data, size_t len);
    void write_paced_bytes(const uint8_t* data, size_t len, uint32_t delay_us = 250);
    bool write_line_paged(const std::string& line_str);

    // Character / byte input
    bool check_abort();
    int read_raw_byte(uint32_t timeout_ms = 1000);
    std::string read_line(bool echo = true);
    std::string read_hidden_line(const std::string& prompt);
    void flush_rx();

    // Direct buffer manipulation for state machines
    void push_rx(uint8_t byte) { rx_queue_.push_back(byte); }
    bool has_rx() const { return !rx_queue_.empty(); }
    uint8_t pop_rx();

protected:
    void drain_hw_rx(bool intercept_ctrl_c = false);

    int page_lines_ = 0;
    int cur_line_ = 0;
    bool aborted_ = false;
    std::deque<uint8_t> rx_queue_;
};

} // namespace ttl2wifi

