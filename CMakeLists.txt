cmake_minimum_required(VERSION 3.20)

# Check if building for Raspberry Pi Pico W
if (DEFINED PICO_BOARD OR DEFINED ENV{PICO_BOARD})
    if (NOT DEFINED PICO_TOOLCHAIN_PATH AND NOT DEFINED ENV{PICO_TOOLCHAIN_PATH})
        if (EXISTS "${CMAKE_CURRENT_LIST_DIR}/external/arm-toolchain")
            set(PICO_TOOLCHAIN_PATH "${CMAKE_CURRENT_LIST_DIR}/external/arm-toolchain")
        endif()
    endif()

    include(pico_sdk_import.cmake)
    project(ttl2wifi C CXX ASM)

    set(CMAKE_C_STANDARD 11)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)

    pico_sdk_init()

    set(PICO_MBEDTLS_CONFIG_FILE "${CMAKE_CURRENT_LIST_DIR}/src/platform/pico/mbedtls_config.h")

    # Shared C++ core & protocols
    add_library(ttl2wifi_core STATIC
        src/core/serial_io.cpp
        src/core/config.cpp
        src/core/modem.cpp
        src/protocols/gopher.cpp
        src/protocols/gemini.cpp
        src/protocols/http.cpp
        src/protocols/xmodem.cpp
        src/protocols/ntp.cpp
    )
    target_include_directories(ttl2wifi_core PUBLIC src/core src/protocols src/platform/pico)
    target_link_libraries(ttl2wifi_core PUBLIC
        pico_stdlib
        hardware_rtc
        pico_cyw43_arch_lwip_threadsafe_background
        pico_lwip_mbedtls
        pico_mbedtls
    )

    # Pico W executable
    add_executable(ttl2wifi
        src/platform/pico/main.cpp
        src/platform/pico/pico_uart.cpp
        src/platform/pico/pico_net.cpp
        src/platform/pico/pico_flash.cpp
    )

    pico_enable_stdio_uart(ttl2wifi 0)
    pico_enable_stdio_usb(ttl2wifi 0)

    target_include_directories(ttl2wifi PUBLIC src/platform/pico)
    target_link_libraries(ttl2wifi PRIVATE
        ttl2wifi_core
        pico_stdlib
        hardware_uart
        hardware_gpio
        hardware_flash
        hardware_sync
        hardware_rtc
        pico_cyw43_arch_lwip_threadsafe_background
        pico_lwip_mbedtls
        pico_mbedtls
    )

    pico_add_extra_outputs(ttl2wifi)

else()
    # Desktop simulator target (macOS / Linux)
    project(ttl2wifi C CXX)

    set(CMAKE_C_STANDARD 11)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)

    # Check for OpenSSL
    if (APPLE AND EXISTS "/opt/homebrew/opt/openssl")
        set(OPENSSL_ROOT_DIR "/opt/homebrew/opt/openssl")
    endif()
    find_package(OpenSSL REQUIRED)

    set(PICO_MBEDTLS_CONFIG_FILE "${CMAKE_CURRENT_LIST_DIR}/src/platform/pico/mbedtls_config.h")

    # Shared C++ core & protocols
    add_library(ttl2wifi_core STATIC
        src/core/serial_io.cpp
        src/core/config.cpp
        src/core/modem.cpp
        src/protocols/gopher.cpp
        src/protocols/gemini.cpp
        src/protocols/http.cpp
        src/protocols/xmodem.cpp
        src/protocols/ntp.cpp
    )
    target_include_directories(ttl2wifi_core PUBLIC src/core src/protocols)

    # Desktop simulator executable
    add_executable(ttl2wifi_sim
        src/platform/desktop/main.cpp
        src/platform/desktop/posix_io.cpp
        src/platform/desktop/posix_net.cpp
    )
    target_include_directories(ttl2wifi_sim PRIVATE src/platform/desktop)
    target_link_libraries(ttl2wifi_sim PRIVATE
        ttl2wifi_core
        OpenSSL::SSL
        OpenSSL::Crypto
    )
endif()
