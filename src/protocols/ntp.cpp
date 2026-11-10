#include "ntp.hpp"
#include <ctime>
#include <cstring>

#if defined(PICO_ON_DEVICE) || defined(PICO_RP2040) || defined(__arm__)
// Pico W embedded implementation
#include "pico/stdlib.h"
#include "hardware/rtc.h"
#include "lwip/udp.h"
#include "lwip/dns.h"
#include "pico/cyw43_arch.h"

namespace ttl2wifi::protocols {

static constexpr uint32_t NTP_DELTA = 2208988800UL;

struct NtpState {
    uint32_t unix_time = 0;
    bool done = false;
    bool success = false;
};

static void ntp_recv_cb(void* arg, struct udp_pcb*, struct pbuf* p, const ip_addr_t*, u16_t) {
    auto* state = static_cast<NtpState*>(arg);
    if (p && p->tot_len >= 48) {
        uint8_t packet[48];
        pbuf_copy_partial(p, packet, sizeof(packet), 0);
        uint32_t ntp_sec = (static_cast<uint32_t>(packet[40]) << 24) |
                           (static_cast<uint32_t>(packet[41]) << 16) |
                           (static_cast<uint32_t>(packet[42]) << 8)  |
                           (static_cast<uint32_t>(packet[43]));
        if (ntp_sec >= NTP_DELTA) {
            state->unix_time = ntp_sec - NTP_DELTA;
            state->success = true;
        }
    }
    if (p) pbuf_free(p);
    state->done = true;
}

std::string ntp_sync_host(const std::string& host, NtpDateTime* dt_out) {
    ip_addr_t server_ip;
    cyw43_arch_lwip_begin();
    err_t err = dns_gethostbyname(host.c_str(), &server_ip, nullptr, nullptr);
    cyw43_arch_lwip_end();

    if (err != ERR_OK) {
        return "";
    }

    NtpState state;
    cyw43_arch_lwip_begin();
    struct udp_pcb* pcb = udp_new();
    if (!pcb) {
        cyw43_arch_lwip_end();
        return "";
    }

    udp_recv(pcb, ntp_recv_cb, &state);

    struct pbuf* p = pbuf_alloc(PBUF_TRANSPORT, 48, PBUF_RAM);
    if (p) {
        std::memset(p->payload, 0, 48);
        reinterpret_cast<uint8_t*>(p->payload)[0] = 0x1B;
        udp_sendto(pcb, p, &server_ip, 123);
        pbuf_free(p);
    }
    cyw43_arch_lwip_end();

    uint32_t start = to_ms_since_boot(get_absolute_time());
    while (!state.done) {
        cyw43_arch_poll();
        sleep_us(100);
        if ((to_ms_since_boot(get_absolute_time()) - start) > 5000) {
            break;
        }
    }

    cyw43_arch_lwip_begin();
    udp_remove(pcb);
    cyw43_arch_lwip_end();

    if (!state.success) {
        return "";
    }

    time_t raw_time = static_cast<time_t>(state.unix_time);
    struct tm* tm = gmtime(&raw_time);
    if (!tm) return "";

    if (dt_out) {
        dt_out->year = tm->tm_year + 1900;
        dt_out->month = tm->tm_mon + 1;
        dt_out->day = tm->tm_mday;
        dt_out->dotw = tm->tm_wday;
        dt_out->hour = tm->tm_hour;
        dt_out->min = tm->tm_min;
        dt_out->sec = tm->tm_sec;
        dt_out->unix_time = state.unix_time;
    }

    datetime_t rtc_dt = {
        .year  = static_cast<int16_t>(tm->tm_year + 1900),
        .month = static_cast<int8_t>(tm->tm_mon + 1),
        .day   = static_cast<int8_t>(tm->tm_mday),
        .dotw  = static_cast<int8_t>(tm->tm_wday),
        .hour  = static_cast<int8_t>(tm->tm_hour),
        .min   = static_cast<int8_t>(tm->tm_min),
        .sec   = static_cast<int8_t>(tm->tm_sec)
    };
    rtc_init();
    rtc_set_datetime(&rtc_dt);

    char buf[64];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d UTC",
             tm->tm_year + 1900, tm->tm_mon + 1, tm->tm_mday,
             tm->tm_hour, tm->tm_min, tm->tm_sec);
    return std::string(buf);
}

} // namespace ttl2wifi::protocols

#else
// Desktop POSIX implementation
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>
#include <poll.h>

namespace ttl2wifi::protocols {

static constexpr uint32_t NTP_DELTA = 2208988800UL;

std::string ntp_sync_host(const std::string& host, NtpDateTime* dt_out) {
    struct addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_DGRAM;

    if (getaddrinfo(host.c_str(), "123", &hints, &res) != 0 || !res) {
        return "";
    }

    int s = ::socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (s < 0) {
        freeaddrinfo(res);
        return "";
    }

    uint8_t packet[48];
    std::memset(packet, 0, sizeof(packet));
    packet[0] = 0x1B;

    if (::sendto(s, packet, sizeof(packet), 0, res->ai_addr, res->ai_addrlen) < 0) {
        freeaddrinfo(res);
        ::close(s);
        return "";
    }
    freeaddrinfo(res);

    struct pollfd pfd{};
    pfd.fd = s;
    pfd.events = POLLIN;
    int pr = ::poll(&pfd, 1, 5000);
    if (pr <= 0) {
        ::close(s);
        return "";
    }

    ssize_t n = ::recv(s, packet, sizeof(packet), 0);
    ::close(s);

    if (n < 48) {
        return "";
    }

    uint32_t ntp_sec = (static_cast<uint32_t>(packet[40]) << 24) |
                       (static_cast<uint32_t>(packet[41]) << 16) |
                       (static_cast<uint32_t>(packet[42]) << 8)  |
                       (static_cast<uint32_t>(packet[43]));

    if (ntp_sec < NTP_DELTA) {
        return "";
    }

    uint32_t unix_time = ntp_sec - NTP_DELTA;
    time_t raw_time = static_cast<time_t>(unix_time);
    struct tm* tm = gmtime(&raw_time);
    if (!tm) return "";

    if (dt_out) {
        dt_out->year = tm->tm_year + 1900;
        dt_out->month = tm->tm_mon + 1;
        dt_out->day = tm->tm_mday;
        dt_out->dotw = tm->tm_wday;
        dt_out->hour = tm->tm_hour;
        dt_out->min = tm->tm_min;
        dt_out->sec = tm->tm_sec;
        dt_out->unix_time = unix_time;
    }

    char buf[64];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d UTC",
             tm->tm_year + 1900, tm->tm_mon + 1, tm->tm_mday,
             tm->tm_hour, tm->tm_min, tm->tm_sec);
    return std::string(buf);
}

} // namespace ttl2wifi::protocols

#endif
