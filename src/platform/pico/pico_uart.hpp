#pragma once

#include "../../core/serial_io.hpp"
#include "pico/stdlib.h"
#include "hardware/uart.h"
#include "hardware/irq.h"

namespace ttl2wifi::pico {

constexpr uint UART_TX_PIN = 0;
constexpr uint UART_RX_PIN = 1;
constexpr uint UART_CTS_PIN = 2;
constexpr uint UART_RTS_PIN = 3;

class PicoFlowUART : public ISerialIO {
public:
    PicoFlowUART(uart_inst_t* uart = uart0, uint baud = 115200);
    ~PicoFlowUART() override = default;

    void init(int flow_mode = 3);
    void set_flow_mode(int mode);
    void set_baud(uint baud);

    int hw_read(uint8_t* buf, size_t max_len) override;
    void hw_write(const uint8_t* data, size_t len) override;
    void sleep_us(uint32_t us) override;
    uint32_t ticks_ms() override;

    void on_uart_rx_irq();

private:
    uart_inst_t* uart_;
    uint baud_;
    int flow_mode_ = 3;

    static constexpr size_t RING_SIZE = 1024;
    uint8_t ring_buf_[RING_SIZE];
    volatile size_t head_ = 0;
    volatile size_t tail_ = 0;
};

} // namespace ttl2wifi::pico

