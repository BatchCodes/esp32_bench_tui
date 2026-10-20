#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "bench_protocol/bench_protocol.hpp"
#include "esp_err.h"
#include "pin_model/pin_model.hpp"

// Sets up the configured pins on the hardware, reads the inputs and drives the
// outputs. Only one PinBank exists, because the GPIO interrupt service and the
// LEDC timers are global.
namespace bench_io {

class PinBank {
public:
    // GPIOs that no configuration may use, for example the link UART pins.
    // Pass -1 for an unused entry.
    esp_err_t init(int blocked_gpio_a, int blocked_gpio_b);

    // Releases the pins of the previous configuration and sets up each pin of
    // config. pin_errors holds the parse error of each pin, or nullptr. Fills
    // errors with one entry for each pin that was not set up, and returns the
    // number of entries.
    size_t apply(const pin_model::Config& config, const char* const* pin_errors,
                 bench_protocol::PinError* errors);

    // Sets an output. Returns nullptr, or an error text.
    const char* set(const char* id, float value);

    // Reads every active pin. Returns the number of values.
    size_t read(bench_protocol::PinValue* values);

    // Sets every output to its initial value.
    void stop_outputs();

    bool has_outputs() const;

    // I2C requests on an i2c pin. Each returns nullptr, or an error text.
    const char* i2c_scan(const char* id, uint8_t* addresses, size_t* count);
    const char* i2c_read(const char* id, int address, int reg, uint8_t* data, size_t length);
    const char* i2c_write(const char* id, int address, int reg, const uint8_t* data,
                          size_t length);

    // Sends bytes on a uart pin. Returns nullptr, or an error text.
    const char* uart_send(const char* id, const uint8_t* data, size_t length);

    // Calls emit for each block of bytes that a uart pin received.
    using UartEmit = void (*)(const char* id, const uint8_t* data, size_t length);
    void poll_uarts(UartEmit emit);

    // Runs the DS18B20 and DHT read steps that are due. Call it often. One
    // call blocks for at most about 7 ms.
    void service_sensors(uint32_t now_ms);

    void release_all();

private:
    struct ActivePin {
        pin_model::PinConfig config;
        bool active;
        float value;
        volatile uint32_t edges;
        pin_model::LedcSlot slot;
        uint32_t duty_bits;
        int adc_unit;
        int adc_channel;
        void* adc_cali;
        void* i2c_bus;
        int uart_port;
        uint32_t uart_rx_bytes;
        // DS18B20 and DHT: the read step, when it is due, and the humidity.
        int sensor_step;
        uint32_t sensor_due_ms;
        uint32_t sensor_started_ms;
        float humidity;
        // HX711: the last raw value, the ready flag and the timeout count of
        // each channel, the time each channel last had data, and the reads.
        float hx711_raw[2];
        bool hx711_ready[2];
        uint32_t hx711_timeouts[2];
        uint32_t hx711_last_data_ms[2];
        uint32_t hx711_last_read_ms;
        uint32_t hx711_reads;
    };

    void service_ds18b20(ActivePin* pin, uint32_t now_ms);
    void service_dht(ActivePin* pin, uint32_t now_ms);
    void service_hx711(ActivePin* pin, uint32_t now_ms);

    ActivePin* find(const char* id, pin_model::Mode mode, const char** error);
    const char* check_gpio(int gpio, bool needs_output) const;

    const char* setup_pin(ActivePin* pin);
    const char* write_output(ActivePin* pin, float value);
    float read_adc(const ActivePin& pin);
    void release_pin(ActivePin* pin);

    ActivePin pins_[pin_model::kMaxPins] = {};
    size_t pin_count_ = 0;
    int blocked_gpio_a_ = -1;
    int blocked_gpio_b_ = -1;
    // GPIOs that were reserved at boot (flash, PSRAM), as a bit mask.
    uint64_t boot_reserved_ = 0;
    pin_model::LedcAllocator ledc_{0, 0};
    void* adc_units_[2] = {};
    bool uart_in_use_[4] = {};
};

}  // namespace bench_io
