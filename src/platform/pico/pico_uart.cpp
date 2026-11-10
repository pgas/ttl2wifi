#include "pico_uart.hpp"
#include "hardware/gpio.h"

static ttl2wifi::pico::PicoFlowUART* g_uart_instance = nullptr;

static void uart_irq_handler() {
    if (g_uart_instance) {
        g_uart_instance->on_uart_rx_irq();
    }
}

namespace ttl2wifi::pico {

PicoFlowUART::PicoFlowUART(uart_inst_t* uart, uint baud)
    : uart_(uart), baud_(baud) {
    g_uart_instance = this;
}

void PicoFlowUART::init(int flow_mode) {
    uart_init(uart_, baud_);
    gpio_set_function(UART_TX_PIN, GPIO_FUNC_UART);
    gpio_set_function(UART_RX_PIN, GPIO_FUNC_UART);

    uart_set_format(uart_, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(uart_, true);

    set_flow_mode(flow_mode);

    // Set up interrupt handler for RX
    int uart_irq = (uart_ == uart0) ? UART0_IRQ : UART1_IRQ;
    irq_set_exclusive_handler(uart_irq, uart_irq_handler);
    irq_set_enabled(uart_irq, true);
    uart_set_irq_enables(uart_, true, false);
}

void PicoFlowUART::set_flow_mode(int mode) {
    flow_mode_ = mode;
    if (flow_mode_ == 3) {
        // HW RTS/CTS
        gpio_set_function(UART_CTS_PIN, GPIO_FUNC_UART);
        gpio_set_function(UART_RTS_PIN, GPIO_FUNC_UART);
        uart_set_hw_flow(uart_, true, true);
    } else {
        uart_set_hw_flow(uart_, false, false);
        gpio_set_function(UART_CTS_PIN, GPIO_FUNC_SIO);
        gpio_set_function(UART_RTS_PIN, GPIO_FUNC_SIO);
    }
}

void PicoFlowUART::set_baud(uint baud) {
    baud_ = baud;
    uart_set_baudrate(uart_, baud_);
}

void PicoFlowUART::on_uart_rx_irq() {
    while (uart_is_readable(uart_)) {
        uint8_t ch = uart_getc(uart_);
        size_t next = (head_ + 1) % RING_SIZE;
        if (next != tail_) {
            ring_buf_[head_] = ch;
            head_ = next;
        }
    }
}

int PicoFlowUART::hw_read(uint8_t* buf, size_t max_len) {
    size_t count = 0;
    while (tail_ != head_ && count < max_len) {
        buf[count++] = ring_buf_[tail_];
        tail_ = (tail_ + 1) % RING_SIZE;
    }
    return static_cast<int>(count);
}

void PicoFlowUART::hw_write(const uint8_t* data, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        uart_putc_raw(uart_, data[i]);
    }
}

void PicoFlowUART::sleep_us(uint32_t us) {
    busy_wait_us_32(us);
}

uint32_t PicoFlowUART::ticks_ms() {
    return to_ms_since_boot(get_absolute_time());
}

} // namespace ttl2wifi::pico

