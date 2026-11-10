#include "posix_io.hpp"
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <thread>
#include <termios.h>

namespace ttl2wifi::desktop {

PosixSerialIO::PosixSerialIO()
    : start_time_(std::chrono::steady_clock::now()) {}

PosixSerialIO::~PosixSerialIO() {
    close();
}

bool PosixSerialIO::open_socket(const std::string& host, uint16_t port) {
    close();
    int s = ::socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) return false;

    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, host.c_str(), &addr.sin_addr);

    if (::connect(s, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        ::close(s);
        return false;
    }

    // Set non-blocking
    int flags = fcntl(s, F_GETFL, 0);
    fcntl(s, F_SETFL, flags | O_NONBLOCK);

    fd_ = s;
    is_socket_ = true;
    return true;
}

bool PosixSerialIO::open_stdio() {
    close();
    fd_ = STDIN_FILENO;
    is_socket_ = false;

    int flags = fcntl(fd_, F_GETFL, 0);
    fcntl(fd_, F_SETFL, flags | O_NONBLOCK);
    return true;
}

void PosixSerialIO::close() {
    if (fd_ >= 0) {
        if (is_socket_) {
            ::close(fd_);
        }
        fd_ = -1;
    }
}

int PosixSerialIO::hw_read(uint8_t* buf, size_t max_len) {
    if (fd_ < 0) return -1;
    ssize_t n = ::read(fd_, buf, max_len);
    if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            return 0;
        }
        return -1;
    }
    return static_cast<int>(n);
}

void PosixSerialIO::hw_write(const uint8_t* data, size_t len) {
    int out_fd = (is_socket_ || fd_ < 0) ? fd_ : STDOUT_FILENO;
    if (out_fd < 0) return;
    size_t written = 0;
    while (written < len) {
        ssize_t n = ::write(out_fd, data + written, len - written);
        if (n > 0) {
            written += n;
        } else if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        } else {
            break;
        }
    }
}

void PosixSerialIO::sleep_us(uint32_t us) {
    std::this_thread::sleep_for(std::chrono::microseconds(us));
}

uint32_t PosixSerialIO::ticks_ms() {
    auto now = std::chrono::steady_clock::now();
    return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(now - start_time_).count());
}

} // namespace ttl2wifi::desktop

