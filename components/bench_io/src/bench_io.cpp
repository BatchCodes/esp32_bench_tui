#include "bench_io/bench_io.hpp"

#include <cmath>
#include <cstring>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/ledc.h"
#include "driver/uart.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_attr.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "esp_private/esp_gpio_reserve.h"
#include "soc/soc_caps.h"

namespace bench_io {

namespace {

using pin_model::Mode;

constexpr const char* kTag = "pins";
constexpr ledc_mode_t kLedcMode = LEDC_LOW_SPEED_MODE;
constexpr adc_atten_t kAdcAtten = ADC_ATTEN_DB_12;
// Full scale of a 12-bit reading at 12 dB attenuation, for chips with no
// calibration data in eFuse. The value is approximate.
constexpr float kUncalibratedFullScaleMv = 3100.0f;
constexpr float kAdcMaxRaw = 4095.0f;
constexpr int kI2cTimeoutMs = 50;
constexpr int kI2cProbeTimeoutMs = 10;
constexpr int kI2cFirstAddress = 0x08;
constexpr int kI2cLastAddress = 0x77;
constexpr int kUartRxBuffer = 2048;
constexpr int kUartTxBuffer = 1024;
// The console uses UART0, so pins get UART1 and up.
constexpr int kFirstPinUart = 1;
constexpr int kMaxUartBlocks = 8;

// 1-Wire slot times in microseconds. Source: Analog Devices (Maxim)
// application note 126, "1-Wire Communication Through Software", standard speed.
constexpr uint32_t kOneWireResetLowUs = 480;
constexpr uint32_t kOneWirePresenceWaitUs = 70;
constexpr uint32_t kOneWireResetEndUs = 410;
constexpr uint32_t kOneWireWrite1LowUs = 6;
constexpr uint32_t kOneWireWrite1HighUs = 64;
constexpr uint32_t kOneWireWrite0LowUs = 60;
constexpr uint32_t kOneWireWrite0HighUs = 10;
constexpr uint32_t kOneWireReadLowUs = 6;
constexpr uint32_t kOneWireReadSampleUs = 9;
constexpr uint32_t kOneWireReadEndUs = 55;
constexpr uint8_t kDs18b20SkipRom = 0xCC;
constexpr uint8_t kDs18b20Convert = 0x44;
constexpr uint8_t kDs18b20ReadScratchpad = 0xBE;
constexpr uint32_t kDs18b20ConversionMs = 750;

// DHT start signal: at least 18 ms low for a DHT11, at least 1 ms for a DHT22.
constexpr uint32_t kDht11StartMs = 20;
constexpr uint32_t kDht22StartMs = 2;
constexpr int64_t kDhtResponseTimeoutUs = 120;
// A data bit is 26 to 28 us high for 0 and 70 us high for 1.
constexpr int64_t kDhtOneThresholdUs = 45;

portMUX_TYPE bitbang_lock = portMUX_INITIALIZER_UNLOCKED;

void IRAM_ATTR count_edge(void* arg) {
    auto* edges = static_cast<volatile uint32_t*>(arg);
    *edges = *edges + 1;
}

i2c_master_bus_handle_t bus_handle(void* handle) {
    return static_cast<i2c_master_bus_handle_t>(handle);
}

adc_oneshot_unit_handle_t unit_handle(void* handle) {
    return static_cast<adc_oneshot_unit_handle_t>(handle);
}

adc_cali_handle_t cali_handle(void* handle) {
    return static_cast<adc_cali_handle_t>(handle);
}

void* create_calibration(adc_unit_t unit, adc_channel_t channel) {
    adc_cali_handle_t handle = nullptr;
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    adc_cali_curve_fitting_config_t config = {};
    config.unit_id = unit;
    config.chan = channel;
    config.atten = kAdcAtten;
    config.bitwidth = ADC_BITWIDTH_DEFAULT;
    if (adc_cali_create_scheme_curve_fitting(&config, &handle) != ESP_OK) {
        handle = nullptr;
    }
#elif ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
    (void)channel;
    adc_cali_line_fitting_config_t config = {};
    config.unit_id = unit;
    config.atten = kAdcAtten;
    config.bitwidth = ADC_BITWIDTH_DEFAULT;
    if (adc_cali_create_scheme_line_fitting(&config, &handle) != ESP_OK) {
        handle = nullptr;
    }
#else
    (void)unit;
    (void)channel;
#endif
    return handle;
}

void delete_calibration(void* handle) {
    if (handle == nullptr) {
        return;
    }
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    adc_cali_delete_scheme_curve_fitting(cali_handle(handle));
#elif ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
    adc_cali_delete_scheme_line_fitting(cali_handle(handle));
#endif
}

// Sets a pin up as open drain with the internal pull-up, released (high).
const char* setup_open_drain(int gpio) {
    gpio_config_t io = {};
    io.pin_bit_mask = BIT64(gpio);
    io.mode = GPIO_MODE_INPUT_OUTPUT_OD;
    io.pull_up_en = GPIO_PULLUP_ENABLE;
    io.intr_type = GPIO_INTR_DISABLE;
    if (gpio_config(&io) != ESP_OK) {
        return "gpio_config failed";
    }
    gpio_set_level(static_cast<gpio_num_t>(gpio), 1);
    return nullptr;
}

bool onewire_reset(gpio_num_t pin) {
    gpio_set_level(pin, 0);
    esp_rom_delay_us(kOneWireResetLowUs);
    taskENTER_CRITICAL(&bitbang_lock);
    gpio_set_level(pin, 1);
    esp_rom_delay_us(kOneWirePresenceWaitUs);
    const bool present = gpio_get_level(pin) == 0;
    taskEXIT_CRITICAL(&bitbang_lock);
    esp_rom_delay_us(kOneWireResetEndUs);
    return present;
}

void onewire_write_byte(gpio_num_t pin, uint8_t byte) {
    for (int bit = 0; bit < 8; ++bit) {
        const bool one = (byte >> bit) & 0x01;
        taskENTER_CRITICAL(&bitbang_lock);
        gpio_set_level(pin, 0);
        esp_rom_delay_us(one ? kOneWireWrite1LowUs : kOneWireWrite0LowUs);
        gpio_set_level(pin, 1);
        taskEXIT_CRITICAL(&bitbang_lock);
        esp_rom_delay_us(one ? kOneWireWrite1HighUs : kOneWireWrite0HighUs);
    }
}

uint8_t onewire_read_byte(gpio_num_t pin) {
    uint8_t byte = 0;
    for (int bit = 0; bit < 8; ++bit) {
        taskENTER_CRITICAL(&bitbang_lock);
        gpio_set_level(pin, 0);
        esp_rom_delay_us(kOneWireReadLowUs);
        gpio_set_level(pin, 1);
        esp_rom_delay_us(kOneWireReadSampleUs);
        const int level = gpio_get_level(pin);
        taskEXIT_CRITICAL(&bitbang_lock);
        byte |= static_cast<uint8_t>(level << bit);
        esp_rom_delay_us(kOneWireReadEndUs);
    }
    return byte;
}

// Waits while the pin has level. Returns the time in us, or -1 on timeout.
// Call it with interrupts off.
int64_t wait_while(gpio_num_t pin, int level, int64_t timeout_us) {
    const int64_t start = esp_timer_get_time();
    while (gpio_get_level(pin) == level) {
        const int64_t elapsed = esp_timer_get_time() - start;
        if (elapsed > timeout_us) {
            return -1;
        }
    }
    return esp_timer_get_time() - start;
}

// Releases the line after the start signal and reads the 5 data bytes.
bool dht_read_bytes(gpio_num_t pin, uint8_t* data) {
    bool ok = true;
    taskENTER_CRITICAL(&bitbang_lock);
    gpio_set_level(pin, 1);
    // The sensor answers with 80 us low, then 80 us high.
    if (wait_while(pin, 1, kDhtResponseTimeoutUs) < 0 ||
        wait_while(pin, 0, kDhtResponseTimeoutUs) < 0 ||
        wait_while(pin, 1, kDhtResponseTimeoutUs) < 0) {
        ok = false;
    }
    for (int bit = 0; ok && bit < 40; ++bit) {
        if (wait_while(pin, 0, kDhtResponseTimeoutUs) < 0) {
            ok = false;
            break;
        }
        const int64_t high_us = wait_while(pin, 1, kDhtResponseTimeoutUs);
        if (high_us < 0) {
            ok = false;
            break;
        }
        data[bit / 8] = static_cast<uint8_t>(data[bit / 8] << 1 | (high_us > kDhtOneThresholdUs));
    }
    taskEXIT_CRITICAL(&bitbang_lock);
    return ok;
}

}  // namespace

esp_err_t PinBank::init(int blocked_gpio_a, int blocked_gpio_b) {
    blocked_gpio_a_ = blocked_gpio_a;
    blocked_gpio_b_ = blocked_gpio_b;
    // The flash and PSRAM pins are reserved at boot. Since ESP-IDF 6 the GPIO
    // driver also reserves each pin that it sets up as an output, until
    // gpio_reset_pin. So the boot state, not the live state, says which pins
    // are never usable.
    boot_reserved_ = 0;
    for (int gpio = 0; gpio < 64; ++gpio) {
        if (GPIO_IS_VALID_GPIO(gpio) && esp_gpio_is_reserved(BIT64(gpio))) {
            boot_reserved_ |= BIT64(gpio);
        }
    }
    ledc_ = pin_model::LedcAllocator(LEDC_TIMER_MAX, SOC_LEDC_CHANNEL_NUM);
    esp_err_t result = gpio_install_isr_service(0);
    ESP_RETURN_ON_FALSE(result == ESP_OK || result == ESP_ERR_INVALID_STATE, result, kTag,
                        "GPIO interrupt service install failed");
    return ESP_OK;
}

size_t PinBank::apply(const pin_model::Config& config, const char* const* pin_errors,
                      bench_protocol::PinError* errors) {
    release_all();
    size_t error_count = 0;
    for (size_t index = 0; index < config.pin_count; ++index) {
        ActivePin& pin = pins_[pin_count_];
        std::memset(&pin, 0, sizeof(pin));
        pin.config = config.pins[index];
        pin.adc_unit = -1;
        pin.uart_port = -1;
        const char* error = pin_errors[index];
        if (error == nullptr) {
            error = setup_pin(&pin);
        }
        if (error != nullptr) {
            ESP_LOGW(kTag, "pin '%s' (GPIO %d): %s", pin.config.id, pin.config.gpio, error);
            errors[error_count].id = config.pins[index].id;
            errors[error_count].error = error;
            ++error_count;
            release_pin(&pin);
            continue;
        }
        pin.active = true;
        ++pin_count_;
    }
    ESP_LOGI(kTag, "configured %u pins, %u errors", static_cast<unsigned>(pin_count_),
             static_cast<unsigned>(error_count));
    return error_count;
}

const char* PinBank::setup_pin(ActivePin* pin) {
    const pin_model::PinConfig& config = pin->config;
    const int gpio = config.gpio;
    // The HX711 clock, the I2C lines, the UART TX and the sensor data lines
    // need an output driver.
    const bool output_first = pin_model::is_output(config.mode) || config.mode == Mode::I2c ||
                              config.mode == Mode::Uart || config.mode == Mode::Hx711 ||
                              pin_model::is_sensor(config.mode);
    const char* gpio_error = check_gpio(gpio, output_first);
    if (gpio_error != nullptr) {
        return gpio_error;
    }
    if (pin_model::uses_two_gpios(config.mode)) {
        gpio_error = check_gpio(config.gpio2, config.mode == Mode::I2c);
        if (gpio_error != nullptr) {
            return gpio_error;
        }
    }
    if (config.mode == Mode::Hx711 && config.gpio3 >= 0) {
        gpio_error = check_gpio(config.gpio3, false);
        if (gpio_error != nullptr) {
            return gpio_error;
        }
    }

    switch (config.mode) {
        case Mode::DigitalIn: {
            if (config.pull != pin_model::Pull::None && !GPIO_IS_VALID_OUTPUT_GPIO(gpio)) {
                return "gpio has no internal pull resistor";
            }
            gpio_config_t io = {};
            io.pin_bit_mask = BIT64(gpio);
            io.mode = GPIO_MODE_INPUT;
            io.pull_up_en =
                config.pull == pin_model::Pull::Up ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE;
            io.pull_down_en = config.pull == pin_model::Pull::Down ? GPIO_PULLDOWN_ENABLE
                                                                   : GPIO_PULLDOWN_DISABLE;
            io.intr_type = GPIO_INTR_ANYEDGE;
            if (gpio_config(&io) != ESP_OK) {
                return "gpio_config failed";
            }
            if (gpio_isr_handler_add(static_cast<gpio_num_t>(gpio), count_edge,
                                     const_cast<uint32_t*>(&pin->edges)) != ESP_OK) {
                return "gpio interrupt setup failed";
            }
            return nullptr;
        }
        case Mode::DigitalOut: {
            gpio_config_t io = {};
            io.pin_bit_mask = BIT64(gpio);
            // Input and output, so that a read shows the real pin level.
            io.mode = GPIO_MODE_INPUT_OUTPUT;
            io.intr_type = GPIO_INTR_DISABLE;
            if (gpio_config(&io) != ESP_OK) {
                return "gpio_config failed";
            }
            return write_output(pin, config.initial);
        }
        case Mode::Adc: {
            adc_unit_t unit = ADC_UNIT_1;
            adc_channel_t channel = ADC_CHANNEL_0;
            if (adc_oneshot_io_to_channel(gpio, &unit, &channel) != ESP_OK) {
                return "gpio has no ADC channel";
            }
            const int unit_index = unit == ADC_UNIT_1 ? 0 : 1;
            if (adc_units_[unit_index] == nullptr) {
                adc_oneshot_unit_init_cfg_t unit_config = {};
                unit_config.unit_id = unit;
                adc_oneshot_unit_handle_t handle = nullptr;
                if (adc_oneshot_new_unit(&unit_config, &handle) != ESP_OK) {
                    return "ADC unit setup failed";
                }
                adc_units_[unit_index] = handle;
            }
            adc_oneshot_chan_cfg_t channel_config = {};
            channel_config.atten = kAdcAtten;
            channel_config.bitwidth = ADC_BITWIDTH_DEFAULT;
            if (adc_oneshot_config_channel(unit_handle(adc_units_[unit_index]), channel,
                                           &channel_config) != ESP_OK) {
                return "ADC channel setup failed";
            }
            pin->adc_unit = unit_index;
            pin->adc_channel = channel;
            pin->adc_cali = create_calibration(unit, channel);
            pin->value = read_adc(*pin);
            return nullptr;
        }
        case Mode::Pwm:
        case Mode::Servo: {
            const uint32_t freq_hz = pin_model::ledc_freq_hz(config);
            const char* error = ledc_.allocate(freq_hz, &pin->slot);
            if (error != nullptr) {
                return error;
            }
            pin->duty_bits = pin_model::duty_resolution_bits(freq_hz);
            if (ledc_.timer_is_new()) {
                ledc_timer_config_t timer = {};
                timer.speed_mode = kLedcMode;
                timer.duty_resolution = static_cast<ledc_timer_bit_t>(pin->duty_bits);
                timer.timer_num = static_cast<ledc_timer_t>(pin->slot.timer);
                timer.freq_hz = freq_hz;
                timer.clk_cfg = LEDC_AUTO_CLK;
                if (ledc_timer_config(&timer) != ESP_OK) {
                    return "LEDC timer setup failed for this frequency";
                }
            }
            ledc_channel_config_t channel = {};
            channel.gpio_num = gpio;
            channel.speed_mode = kLedcMode;
            channel.channel = static_cast<ledc_channel_t>(pin->slot.channel);
            channel.timer_sel = static_cast<ledc_timer_t>(pin->slot.timer);
            channel.duty = 0;
            channel.hpoint = 0;
            if (ledc_channel_config(&channel) != ESP_OK) {
                return "LEDC channel setup failed";
            }
            return write_output(pin, config.initial);
        }
        case Mode::I2c: {
            i2c_master_bus_config_t bus = {};
            bus.i2c_port = -1;
            bus.sda_io_num = static_cast<gpio_num_t>(gpio);
            bus.scl_io_num = static_cast<gpio_num_t>(config.gpio2);
            bus.clk_source = I2C_CLK_SRC_DEFAULT;
            bus.glitch_ignore_cnt = 7;
            // The internal pull-ups (about 45 kOhm) are weak. Modules usually
            // have their own; use 4.7 kOhm resistors for a bare chip.
            bus.flags.enable_internal_pullup = true;
            i2c_master_bus_handle_t handle = nullptr;
            if (i2c_new_master_bus(&bus, &handle) != ESP_OK) {
                return "no free I2C controller";
            }
            pin->i2c_bus = handle;
            pin->value = NAN;
            return nullptr;
        }
        case Mode::Uart: {
            int port = -1;
            for (int index = kFirstPinUart; index < SOC_UART_HP_NUM && index < 4; ++index) {
                if (!uart_in_use_[index]) {
                    port = index;
                    break;
                }
            }
            if (port < 0) {
                return "no free UART";
            }
            uart_config_t uart = {};
            uart.baud_rate = static_cast<int>(config.baud);
            uart.data_bits = UART_DATA_8_BITS;
            uart.parity = UART_PARITY_DISABLE;
            uart.stop_bits = UART_STOP_BITS_1;
            uart.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
            uart.source_clk = UART_SCLK_DEFAULT;
            const auto uart_port = static_cast<uart_port_t>(port);
            if (uart_driver_install(uart_port, kUartRxBuffer, kUartTxBuffer, 0, nullptr, 0) !=
                ESP_OK) {
                return "UART driver install failed";
            }
            uart_in_use_[port] = true;
            pin->uart_port = port;
            if (uart_param_config(uart_port, &uart) != ESP_OK ||
                uart_set_pin(uart_port, gpio, config.gpio2, UART_PIN_NO_CHANGE,
                             UART_PIN_NO_CHANGE) != ESP_OK) {
                return "UART setup failed";
            }
            return nullptr;
        }
        case Mode::Ds18b20:
        case Mode::Dht11:
        case Mode::Dht22: {
            const char* error = setup_open_drain(gpio);
            if (error != nullptr) {
                return error;
            }
            pin->value = NAN;
            pin->humidity = NAN;
            pin->sensor_step = 0;
            pin->sensor_due_ms = 0;
            return nullptr;
        }
        case Mode::Hx711: {
            // The clock idles low. A clock that stays high for more than
            // 60 us powers the HX711 down. Source: HX711 datasheet, "Power
            // down control".
            gpio_config_t clock = {};
            clock.pin_bit_mask = BIT64(gpio);
            clock.mode = GPIO_MODE_OUTPUT;
            clock.intr_type = GPIO_INTR_DISABLE;
            if (gpio_config(&clock) != ESP_OK) {
                return "gpio_config failed for the clock";
            }
            gpio_set_level(static_cast<gpio_num_t>(gpio), 0);
            // The pull-up makes a missing HX711 read as "not ready" (high)
            // instead of a floating input.
            gpio_config_t data = {};
            data.pin_bit_mask = BIT64(config.gpio2);
            if (config.gpio3 >= 0) {
                data.pin_bit_mask |= BIT64(config.gpio3);
            }
            data.mode = GPIO_MODE_INPUT;
            data.pull_up_en = GPIO_PULLUP_ENABLE;
            data.intr_type = GPIO_INTR_DISABLE;
            if (gpio_config(&data) != ESP_OK) {
                return "gpio_config failed for the data pins";
            }
            const uint32_t now = static_cast<uint32_t>(esp_timer_get_time() / 1000);
            for (int channel = 0; channel < 2; ++channel) {
                pin->hx711_raw[channel] = NAN;
                pin->hx711_ready[channel] = false;
                pin->hx711_timeouts[channel] = 0;
                pin->hx711_last_data_ms[channel] = now;
            }
            pin->hx711_last_read_ms = now;
            pin->hx711_reads = 0;
            pin->value = NAN;
            return nullptr;
        }
    }
    return "unknown mode";
}

const char* PinBank::check_gpio(int gpio, bool needs_output) const {
    if (!GPIO_IS_VALID_GPIO(gpio)) {
        return "gpio does not exist on this chip";
    }
    if (gpio == blocked_gpio_a_ || gpio == blocked_gpio_b_) {
        return "gpio is used by the bench agent link";
    }
    if ((boot_reserved_ & BIT64(gpio)) != 0) {
        return "gpio is reserved for flash or PSRAM";
    }
    if (needs_output && !GPIO_IS_VALID_OUTPUT_GPIO(gpio)) {
        return "gpio is input-only";
    }
    return nullptr;
}

const char* PinBank::write_output(ActivePin* pin, float value) {
    const pin_model::PinConfig& config = pin->config;
    switch (config.mode) {
        case Mode::DigitalOut: {
            const bool level = pin_model::physical_level(value >= 0.5f, config.invert);
            if (gpio_set_level(static_cast<gpio_num_t>(config.gpio), level ? 1 : 0) != ESP_OK) {
                return "gpio_set_level failed";
            }
            break;
        }
        case Mode::Pwm:
        case Mode::Servo: {
            const uint32_t duty = config.mode == Mode::Pwm
                                      ? pin_model::pwm_duty(value, pin->duty_bits)
                                      : pin_model::servo_duty(config, value, pin->duty_bits);
            const auto channel = static_cast<ledc_channel_t>(pin->slot.channel);
            if (ledc_set_duty(kLedcMode, channel, duty) != ESP_OK ||
                ledc_update_duty(kLedcMode, channel) != ESP_OK) {
                return "LEDC duty update failed";
            }
            break;
        }
        default:
            return "pin is not an output";
    }
    pin->value = value;
    return nullptr;
}

const char* PinBank::set(const char* id, float value) {
    for (size_t index = 0; index < pin_count_; ++index) {
        ActivePin& pin = pins_[index];
        if (std::strcmp(pin.config.id, id) != 0) {
            continue;
        }
        const char* error = pin_model::validate_output_value(pin.config, value);
        if (error != nullptr) {
            return error;
        }
        return write_output(&pin, value);
    }
    return "pin is not configured";
}

float PinBank::read_adc(const ActivePin& pin) {
    int raw = 0;
    if (adc_oneshot_read(unit_handle(adc_units_[pin.adc_unit]),
                         static_cast<adc_channel_t>(pin.adc_channel), &raw) != ESP_OK) {
        return NAN;
    }
    if (pin.adc_cali != nullptr) {
        int millivolts = 0;
        if (adc_cali_raw_to_voltage(cali_handle(pin.adc_cali), raw, &millivolts) == ESP_OK) {
            return static_cast<float>(millivolts);
        }
    }
    return raw * kUncalibratedFullScaleMv / kAdcMaxRaw;
}

size_t PinBank::read(bench_protocol::PinValue* values) {
    for (size_t index = 0; index < pin_count_; ++index) {
        ActivePin& pin = pins_[index];
        const pin_model::PinConfig& config = pin.config;
        if (config.mode == Mode::DigitalIn) {
            const bool level = gpio_get_level(static_cast<gpio_num_t>(config.gpio)) != 0;
            pin.value = (level != config.invert) ? 1.0f : 0.0f;
        } else if (config.mode == Mode::DigitalOut) {
            const bool level = gpio_get_level(static_cast<gpio_num_t>(config.gpio)) != 0;
            pin.value = (level != config.invert) ? 1.0f : 0.0f;
        } else if (config.mode == Mode::Adc) {
            pin.value = read_adc(pin);
        }
        values[index].id = config.id;
        values[index].mode = config.mode;
        values[index].value = config.mode == Mode::Uart ? static_cast<float>(pin.uart_rx_bytes)
                                                        : pin.value;
        values[index].extra = pin.humidity;
        values[index].edges = pin.edges;
        if (config.mode == Mode::Hx711) {
            values[index].value = pin.hx711_raw[0];
            values[index].extra = pin.hx711_raw[1];
            values[index].has_second = config.gpio3 >= 0;
            for (int channel = 0; channel < 2; ++channel) {
                values[index].ready[channel] = pin.hx711_ready[channel];
                values[index].timeouts[channel] = pin.hx711_timeouts[channel];
            }
            values[index].reads = pin.hx711_reads;
        }
    }
    return pin_count_;
}

void PinBank::stop_outputs() {
    for (size_t index = 0; index < pin_count_; ++index) {
        ActivePin& pin = pins_[index];
        if (pin_model::is_output(pin.config.mode)) {
            write_output(&pin, pin.config.initial);
        }
    }
}

bool PinBank::has_outputs() const {
    for (size_t index = 0; index < pin_count_; ++index) {
        if (pin_model::is_output(pins_[index].config.mode)) {
            return true;
        }
    }
    return false;
}

void PinBank::release_pin(ActivePin* pin) {
    const pin_model::PinConfig& config = pin->config;
    if (check_gpio(config.gpio, false) != nullptr) {
        return;
    }
    switch (config.mode) {
        case Mode::DigitalIn:
            gpio_isr_handler_remove(static_cast<gpio_num_t>(config.gpio));
            break;
        case Mode::Pwm:
        case Mode::Servo:
            if (pin->duty_bits > 0) {
                ledc_stop(kLedcMode, static_cast<ledc_channel_t>(pin->slot.channel), 0);
            }
            break;
        case Mode::Adc:
            delete_calibration(pin->adc_cali);
            pin->adc_cali = nullptr;
            break;
        case Mode::I2c:
            if (pin->i2c_bus != nullptr) {
                i2c_del_master_bus(bus_handle(pin->i2c_bus));
                pin->i2c_bus = nullptr;
            }
            break;
        case Mode::Uart:
            if (pin->uart_port > 0) {
                uart_driver_delete(static_cast<uart_port_t>(pin->uart_port));
                uart_in_use_[pin->uart_port] = false;
                pin->uart_port = -1;
            }
            break;
        case Mode::DigitalOut:
        case Mode::Ds18b20:
        case Mode::Dht11:
        case Mode::Dht22:
        case Mode::Hx711:
            break;
    }
    gpio_reset_pin(static_cast<gpio_num_t>(config.gpio));
    if (pin_model::uses_two_gpios(config.mode) && check_gpio(config.gpio2, false) == nullptr) {
        gpio_reset_pin(static_cast<gpio_num_t>(config.gpio2));
    }
    if (config.mode == Mode::Hx711 && config.gpio3 >= 0 && check_gpio(config.gpio3, false) == nullptr) {
        gpio_reset_pin(static_cast<gpio_num_t>(config.gpio3));
    }
    pin->active = false;
}

void PinBank::release_all() {
    for (size_t index = 0; index < pin_count_; ++index) {
        release_pin(&pins_[index]);
    }
    pin_count_ = 0;
    ledc_.reset();
    for (void*& unit : adc_units_) {
        if (unit != nullptr) {
            adc_oneshot_del_unit(unit_handle(unit));
            unit = nullptr;
        }
    }
}

PinBank::ActivePin* PinBank::find(const char* id, Mode mode, const char** error) {
    for (size_t index = 0; index < pin_count_; ++index) {
        ActivePin& pin = pins_[index];
        if (std::strcmp(pin.config.id, id) != 0) {
            continue;
        }
        if (pin.config.mode != mode) {
            *error = mode == Mode::I2c ? "pin is not an i2c pin" : "pin is not a uart pin";
            return nullptr;
        }
        return &pin;
    }
    *error = "pin is not configured";
    return nullptr;
}

const char* PinBank::i2c_scan(const char* id, uint8_t* addresses, size_t* count) {
    const char* error = nullptr;
    ActivePin* pin = find(id, Mode::I2c, &error);
    if (pin == nullptr) {
        return error;
    }
    *count = 0;
    for (int address = kI2cFirstAddress; address <= kI2cLastAddress; ++address) {
        if (i2c_master_probe(bus_handle(pin->i2c_bus), static_cast<uint16_t>(address),
                             kI2cProbeTimeoutMs) == ESP_OK) {
            addresses[(*count)++] = static_cast<uint8_t>(address);
        }
    }
    pin->value = static_cast<float>(*count);
    return nullptr;
}

namespace {

// Adds a device for one transfer. The new I2C driver needs a device handle
// for each address.
const char* with_device(void* bus, int address, uint32_t freq_hz,
                        i2c_master_dev_handle_t* device) {
    i2c_device_config_t config = {};
    config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    config.device_address = static_cast<uint16_t>(address);
    config.scl_speed_hz = freq_hz;
    if (i2c_master_bus_add_device(bus_handle(bus), &config, device) != ESP_OK) {
        return "I2C device setup failed";
    }
    return nullptr;
}

}  // namespace

const char* PinBank::i2c_read(const char* id, int address, int reg, uint8_t* data,
                              size_t length) {
    const char* error = nullptr;
    ActivePin* pin = find(id, Mode::I2c, &error);
    if (pin == nullptr) {
        return error;
    }
    i2c_master_dev_handle_t device = nullptr;
    error = with_device(pin->i2c_bus, address, pin->config.freq_hz, &device);
    if (error != nullptr) {
        return error;
    }
    esp_err_t result = ESP_OK;
    if (reg >= 0) {
        const uint8_t reg_byte = static_cast<uint8_t>(reg);
        result = i2c_master_transmit_receive(device, &reg_byte, 1, data, length, kI2cTimeoutMs);
    } else {
        result = i2c_master_receive(device, data, length, kI2cTimeoutMs);
    }
    i2c_master_bus_rm_device(device);
    return result == ESP_OK ? nullptr : "no answer from the I2C device";
}

const char* PinBank::i2c_write(const char* id, int address, int reg, const uint8_t* data,
                               size_t length) {
    const char* error = nullptr;
    ActivePin* pin = find(id, Mode::I2c, &error);
    if (pin == nullptr) {
        return error;
    }
    uint8_t buffer[bench_protocol::kMaxI2cTransfer + 1];
    size_t total = 0;
    if (reg >= 0) {
        buffer[total++] = static_cast<uint8_t>(reg);
    }
    std::memcpy(buffer + total, data, length);
    total += length;
    if (total == 0) {
        return "nothing to write";
    }
    i2c_master_dev_handle_t device = nullptr;
    error = with_device(pin->i2c_bus, address, pin->config.freq_hz, &device);
    if (error != nullptr) {
        return error;
    }
    const esp_err_t result = i2c_master_transmit(device, buffer, total, kI2cTimeoutMs);
    i2c_master_bus_rm_device(device);
    return result == ESP_OK ? nullptr : "no answer from the I2C device";
}

const char* PinBank::uart_send(const char* id, const uint8_t* data, size_t length) {
    const char* error = nullptr;
    ActivePin* pin = find(id, Mode::Uart, &error);
    if (pin == nullptr) {
        return error;
    }
    const int written =
        uart_write_bytes(static_cast<uart_port_t>(pin->uart_port), data, length);
    return written == static_cast<int>(length) ? nullptr : "UART write failed";
}

void PinBank::poll_uarts(UartEmit emit) {
    uint8_t block[bench_protocol::kMaxDataBytes];
    for (size_t index = 0; index < pin_count_; ++index) {
        ActivePin& pin = pins_[index];
        if (pin.config.mode != Mode::Uart || pin.uart_port <= 0) {
            continue;
        }
        for (int count = 0; count < kMaxUartBlocks; ++count) {
            const int length = uart_read_bytes(static_cast<uart_port_t>(pin.uart_port), block,
                                               sizeof(block), 0);
            if (length <= 0) {
                break;
            }
            pin.uart_rx_bytes += static_cast<uint32_t>(length);
            emit(pin.config.id, block, static_cast<size_t>(length));
        }
    }
}

void PinBank::service_sensors(uint32_t now_ms) {
    for (size_t index = 0; index < pin_count_; ++index) {
        ActivePin& pin = pins_[index];
        if (static_cast<int32_t>(now_ms - pin.sensor_due_ms) < 0) {
            continue;
        }
        if (pin.config.mode == Mode::Ds18b20) {
            service_ds18b20(&pin, now_ms);
        } else if (pin.config.mode == Mode::Dht11 || pin.config.mode == Mode::Dht22) {
            service_dht(&pin, now_ms);
        } else if (pin.config.mode == Mode::Hx711) {
            service_hx711(&pin, now_ms);
        }
    }
}

void PinBank::service_hx711(ActivePin* pin, uint32_t now_ms) {
    const pin_model::PinConfig& config = pin->config;
    const auto clock = static_cast<gpio_num_t>(config.gpio);
    const gpio_num_t data[2] = {static_cast<gpio_num_t>(config.gpio2),
                                static_cast<gpio_num_t>(config.gpio3 >= 0 ? config.gpio3 : config.gpio2)};
    const int channels = config.gpio3 >= 0 ? 2 : 1;
    // A low data line means that the HX711 has a new conversion ready.
    bool ready[2] = {false, false};
    bool all_ready = true;
    bool any_ready = false;
    for (int channel = 0; channel < channels; ++channel) {
        ready[channel] = gpio_get_level(data[channel]) == 0;
        all_ready = all_ready && ready[channel];
        any_ready = any_ready || ready[channel];
    }
    // Read when every channel is ready, the same way as one shared-clock
    // read in the Gaggiuino. If one channel stays silent, still read the
    // others after the timeout, so a dead HX711 does not hide a good one.
    const bool waited = now_ms - pin->hx711_last_read_ms >= pin_model::kHx711TimeoutMs;
    if (all_ready || (any_ready && waited)) {
        uint32_t bits[2] = {0, 0};
        const int pulses = pin_model::hx711_gain_pulses(config.gain);
        taskENTER_CRITICAL(&bitbang_lock);
        for (int bit = 0; bit < 24; ++bit) {
            gpio_set_level(clock, 1);
            esp_rom_delay_us(1);
            for (int channel = 0; channel < channels; ++channel) {
                bits[channel] = bits[channel] << 1 | static_cast<uint32_t>(gpio_get_level(data[channel]));
            }
            gpio_set_level(clock, 0);
            esp_rom_delay_us(1);
        }
        for (int pulse = 0; pulse < pulses; ++pulse) {
            gpio_set_level(clock, 1);
            esp_rom_delay_us(1);
            gpio_set_level(clock, 0);
            esp_rom_delay_us(1);
        }
        taskEXIT_CRITICAL(&bitbang_lock);
        for (int channel = 0; channel < channels; ++channel) {
            if (ready[channel]) {
                pin->hx711_raw[channel] = static_cast<float>(pin_model::hx711_decode(bits[channel]));
                pin->hx711_ready[channel] = true;
                pin->hx711_last_data_ms[channel] = now_ms;
            }
        }
        pin->hx711_reads++;
        pin->hx711_last_read_ms = now_ms;
    }
    for (int channel = 0; channel < channels; ++channel) {
        if (now_ms - pin->hx711_last_data_ms[channel] >= pin_model::kHx711TimeoutMs) {
            // One timeout for each timeout period with no data.
            pin->hx711_timeouts[channel]++;
            pin->hx711_ready[channel] = false;
            pin->hx711_last_data_ms[channel] = now_ms;
        }
    }
}

void PinBank::service_ds18b20(ActivePin* pin, uint32_t now_ms) {
    const auto gpio = static_cast<gpio_num_t>(pin->config.gpio);
    if (pin->sensor_step == 0) {
        pin->sensor_started_ms = now_ms;
        if (!onewire_reset(gpio)) {
            pin->value = NAN;
            pin->sensor_due_ms = now_ms + pin_model::kDs18b20ReadPeriodMs;
            return;
        }
        onewire_write_byte(gpio, kDs18b20SkipRom);
        onewire_write_byte(gpio, kDs18b20Convert);
        pin->sensor_step = 1;
        pin->sensor_due_ms = now_ms + kDs18b20ConversionMs;
        return;
    }
    pin->sensor_step = 0;
    pin->sensor_due_ms = pin->sensor_started_ms + pin_model::kDs18b20ReadPeriodMs;
    if (!onewire_reset(gpio)) {
        pin->value = NAN;
        return;
    }
    onewire_write_byte(gpio, kDs18b20SkipRom);
    onewire_write_byte(gpio, kDs18b20ReadScratchpad);
    uint8_t scratchpad[9] = {};
    for (uint8_t& byte : scratchpad) {
        byte = onewire_read_byte(gpio);
    }
    float celsius = NAN;
    pin->value = pin_model::ds18b20_decode(scratchpad, &celsius) ? celsius : NAN;
}

void PinBank::service_dht(ActivePin* pin, uint32_t now_ms) {
    const auto gpio = static_cast<gpio_num_t>(pin->config.gpio);
    const bool dht22 = pin->config.mode == Mode::Dht22;
    if (pin->sensor_step == 0) {
        pin->sensor_started_ms = now_ms;
        gpio_set_level(gpio, 0);
        pin->sensor_step = 1;
        pin->sensor_due_ms = now_ms + (dht22 ? kDht22StartMs : kDht11StartMs);
        return;
    }
    pin->sensor_step = 0;
    pin->sensor_due_ms = pin->sensor_started_ms + pin_model::kDhtReadPeriodMs;
    uint8_t data[5] = {};
    float celsius = NAN;
    float humidity = NAN;
    if (dht_read_bytes(gpio, data) && pin_model::dht_decode(data, dht22, &celsius, &humidity)) {
        pin->value = celsius;
        pin->humidity = humidity;
        return;
    }
    gpio_set_level(gpio, 1);
    pin->value = NAN;
    pin->humidity = NAN;
}

}  // namespace bench_io
