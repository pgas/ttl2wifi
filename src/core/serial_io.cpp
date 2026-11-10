#include "serial_io.hpp"
#include <algorithm>

namespace ttl2wifi {

void ISerialIO::write(const std::string& str) {
    hw_write(reinterpret_cast<const uint8_t*>(str.data()), str.size());
}

void ISerialIO::write(const uint8_t* data, size_t len) {
    hw_write(data, len);
}

void ISerialIO::write_paced(const std::string& str) {
    write_paced(reinterpret_cast<const uint8_t*>(str.data()), str.size());
}

void ISerialIO::write_paced(const uint8_t* data, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        uint8_t b = data[i];
        hw_write(&b, 1);
        if (b == 0x0A) {
            sleep_us(10000); // 10ms delay on newline for vintage terminal scrolling
        } else {
            sleep_us(250);   // 250us inter-byte delay (~3000 cps)
        }
    }
}

void ISerialIO::write_paced_bytes(const uint8_t* data, size_t len, uint32_t delay_us) {
    if (delay_us == 0) {
        hw_write(data, len);
        return;
    }
    for (size_t i = 0; i < len; ++i) {
        hw_write(&data[i], 1);
        sleep_us(delay_us);
    }
}

void ISerialIO::drain_hw_rx(bool intercept_ctrl_c) {
    uint8_t buf[64];
    while (true) {
        int n = hw_read(buf, sizeof(buf));
        if (n <= 0) {
            break;
        }
        for (int i = 0; i < n; ++i) {
            if (intercept_ctrl_c && buf[i] == ASCII_ETX) {
                aborted_ = true;
            }
            rx_queue_.push_back(buf[i]);
        }
    }
}

bool ISerialIO::check_abort() {
    drain_hw_rx(true);
    if (aborted_) {
        aborted_ = false;
        return true;
    }
    return false;
}

uint8_t ISerialIO::pop_rx() {
    if (rx_queue_.empty()) return 0;
    uint8_t b = rx_queue_.front();
    rx_queue_.pop_front();
    return b;
}

int ISerialIO::read_raw_byte(uint32_t timeout_ms) {
    uint32_t t0 = ticks_ms();
    while (true) {
        if (!rx_queue_.empty()) {
            return pop_rx();
        }
        uint8_t b = 0;
        int n = hw_read(&b, 1);
        if (n > 0) {
            return b;
        }
        if ((ticks_ms() - t0) > timeout_ms) {
            return -1;
        }
        sleep_us(2000); // 2ms polling sleep
    }
}

void ISerialIO::flush_rx() {
    rx_queue_.clear();
    uint8_t buf[64];
    while (hw_read(buf, sizeof(buf)) > 0) {
        // discard
    }
}

bool ISerialIO::write_line_paged(const std::string& line_str) {
    write_paced(line_str + "\r\n");
    if (page_lines_ > 0) {
        cur_line_++;
        if (cur_line_ >= page_lines_) {
            const std::string prompt = "\r\n-- More (Space: Page, Enter: Line, Q: Abort) --";
            write(prompt);
            int ch = -1;
            while (ch < 0) {
                ch = read_raw_byte(5000);
            }
            // Clear prompt line
            std::string clear_str = "\r";
            clear_str.append(prompt.size(), ' ');
            clear_str += "\r";
            write(clear_str);

            if (ch == ' ' ) {
                cur_line_ = 0;
            } else if (ch == '\r' || ch == '\n') {
                cur_line_ = page_lines_ - 1; // pause on next line
            } else if (ch == 'q' || ch == 'Q' || ch == ASCII_ETX) {
                aborted_ = true;
                return false;
            } else {
                cur_line_ = 0;
            }
        }
    }
    return true;
}

std::string ISerialIO::read_line(bool echo) {
    std::string line;
    while (true) {
        int c = read_raw_byte(100);
        if (c < 0) continue;
        if (c == '\r' || c == '\n') {
            if (echo) write("\r\n");
            break;
        }
        if (c == ASCII_BS || c == ASCII_DEL) {
            if (!line.empty()) {
                line.pop_back();
                if (echo) write("\b \b");
            }
            continue;
        }
        if (c == ASCII_ETX) {
            aborted_ = true;
            if (echo) write("^C\r\n");
            return "";
        }
        if (c >= 32 && c <= 126) {
            line.push_back(static_cast<char>(c));
            if (echo) {
                uint8_t ch = static_cast<uint8_t>(c);
                hw_write(&ch, 1);
            }
        }
    }
    return line;
}

std::string ISerialIO::read_hidden_line(const std::string& prompt) {
    write(prompt);
    std::string s = read_line(/*echo=*/false);
    write("\r\n");
    return s;
}

} // namespace ttl2wifi

