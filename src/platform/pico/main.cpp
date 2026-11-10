#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "../../core/modem.hpp"
#include "pico_uart.hpp"
#include "pico_net.hpp"
#include "pico_flash.hpp"

namespace ttl2wifi::pico {

class PicoModem : public AtModem {
public:
    PicoModem(PicoFlowUART& uart, PicoNetwork& net)
        : AtModem(uart, net), uart_ref_(uart) {}

    void save_config() override {
        flash_save_config(config_.to_json());
    }

    void load_config() override {
        std::string json_str = flash_load_config();
        if (!json_str.empty()) {
            config_.from_json(json_str);
        } else {
            config_.reset_defaults();
        }
    }

    void apply_flow_mode(int mode) override {
        uart_ref_.set_flow_mode(mode);
    }

private:
    PicoFlowUART& uart_ref_;
};

} // namespace ttl2wifi::pico

int main() {
    ttl2wifi::pico::PicoFlowUART uart(uart0, 115200);
    ttl2wifi::pico::PicoNetwork net;

    uart.init(0); // Default None (HW flow control off)
    net.init();

    ttl2wifi::pico::PicoModem modem(uart, net);
    modem.init();

    // Auto-connect Wi-Fi if SSID is saved
    if (!modem.config().wifi_ssid.empty()) {
        cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1);
        net.wifi_join(modem.config().wifi_ssid, modem.config().wifi_password);
        cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 0);
    }

    uart.write_paced(modem.banner());

    while (true) {
        modem.tick();
        cyw43_arch_poll();
        sleep_us(250);
    }

    return 0;
}

