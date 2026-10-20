#include "bench_transport/bench_transport.hpp"

#include <cstdarg>
#include <cstdio>

#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "sdkconfig.h"

#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#else
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "soc/uart_pins.h"
#endif

namespace bench_transport {

namespace {

constexpr const char* kTag = "transport";
constexpr size_t kRxBufferSize = 4096;
constexpr size_t kTxBufferSize = 4096;
constexpr size_t kLogLineSize = 256;
constexpr TickType_t kWriteTimeout = pdMS_TO_TICKS(50);

SemaphoreHandle_t write_lock = nullptr;
bool at_line_start = true;

#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG

void write_bytes(const char* data, size_t length) {
    usb_serial_jtag_write_bytes(data, length, kWriteTimeout);
}

esp_err_t install_driver() {
    usb_serial_jtag_driver_config_t config = {};
    config.rx_buffer_size = kRxBufferSize;
    config.tx_buffer_size = kTxBufferSize;
    ESP_RETURN_ON_ERROR(usb_serial_jtag_driver_install(&config), kTag,
                        "USB-Serial-JTAG driver install failed");
    usb_serial_jtag_vfs_use_driver();
    return ESP_OK;
}

#else

constexpr uart_port_t kPort = static_cast<uart_port_t>(CONFIG_ESP_CONSOLE_UART_NUM);

void write_bytes(const char* data, size_t length) {
    uart_write_bytes(kPort, data, length);
}

esp_err_t install_driver() {
    ESP_RETURN_ON_ERROR(uart_driver_install(kPort, kRxBufferSize, kTxBufferSize, 0, nullptr, 0),
                        kTag, "UART driver install failed");
    uart_vfs_dev_use_driver(kPort);
    return ESP_OK;
}

#endif

void write_locked(const char* data, size_t length) {
    if (length == 0) {
        return;
    }
    write_bytes(data, length);
    at_line_start = data[length - 1] == '\n';
}

// The ESP-IDF log can call this more than once for one log line, so the
// message writer checks at_line_start before each message.
int log_vprintf(const char* format, va_list args) {
    char line[kLogLineSize];
    int length = vsnprintf(line, sizeof(line), format, args);
    if (length < 0) {
        return length;
    }
    size_t count = static_cast<size_t>(length) < sizeof(line) ? length : sizeof(line) - 1;
    if (xSemaphoreTake(write_lock, portMAX_DELAY) == pdTRUE) {
        write_locked(line, count);
        xSemaphoreGive(write_lock);
    }
    return length;
}

}  // namespace

esp_err_t init() {
    write_lock = xSemaphoreCreateMutex();
    ESP_RETURN_ON_FALSE(write_lock != nullptr, ESP_ERR_NO_MEM, kTag, "no memory for the lock");
    ESP_RETURN_ON_ERROR(install_driver(), kTag, "transport driver failed");
    esp_log_set_vprintf(log_vprintf);
    return ESP_OK;
}

void write_message(const std::string& line) {
    if (xSemaphoreTake(write_lock, portMAX_DELAY) != pdTRUE) {
        return;
    }
    if (!at_line_start) {
        write_locked("\n", 1);
    }
    write_locked(line.data(), line.size());
    xSemaphoreGive(write_lock);
}

size_t read(char* buffer, size_t size, uint32_t timeout_ms) {
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    int count = usb_serial_jtag_read_bytes(buffer, size, pdMS_TO_TICKS(timeout_ms));
#else
    int count = uart_read_bytes(kPort, buffer, size, pdMS_TO_TICKS(timeout_ms));
#endif
    return count > 0 ? static_cast<size_t>(count) : 0;
}

int tx_gpio() {
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    return -1;
#else
    return CONFIG_ESP_CONSOLE_UART_NUM == 0 ? U0TXD_GPIO_NUM : -1;
#endif
}

int rx_gpio() {
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    return -1;
#else
    return CONFIG_ESP_CONSOLE_UART_NUM == 0 ? U0RXD_GPIO_NUM : -1;
#endif
}

}  // namespace bench_transport
