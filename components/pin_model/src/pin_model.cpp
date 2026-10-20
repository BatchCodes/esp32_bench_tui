#include "pin_model/pin_model.hpp"

#include <cmath>
#include <cstring>

namespace pin_model {

namespace {

struct ModeName {
    Mode mode;
    const char* name;
};

constexpr ModeName kModeNames[] = {
    {Mode::DigitalIn, "digital_in"}, {Mode::DigitalOut, "digital_out"}, {Mode::Adc, "adc"},
    {Mode::Pwm, "pwm"},
    {Mode::Servo, "servo"},
    {Mode::I2c, "i2c"},
    {Mode::Uart, "uart"},
    {Mode::Ds18b20, "ds18b20"},
    {Mode::Dht11, "dht11"},
    {Mode::Dht22, "dht22"},
    {Mode::Hx711, "hx711"},
};

struct PullName {
    Pull pull;
    const char* name;
};

constexpr PullName kPullNames[] = {
    {Pull::None, "none"},
    {Pull::Up, "up"},
    {Pull::Down, "down"},
};

}  // namespace

const char* mode_name(Mode mode) {
    for (const auto& entry : kModeNames) {
        if (entry.mode == mode) {
            return entry.name;
        }
    }
    return "unknown";
}

bool parse_mode(const char* text, Mode* mode) {
    for (const auto& entry : kModeNames) {
        if (std::strcmp(entry.name, text) == 0) {
            *mode = entry.mode;
            return true;
        }
    }
    return false;
}

const char* pull_name(Pull pull) {
    for (const auto& entry : kPullNames) {
        if (entry.pull == pull) {
            return entry.name;
        }
    }
    return "unknown";
}

bool parse_pull(const char* text, Pull* pull) {
    for (const auto& entry : kPullNames) {
        if (std::strcmp(entry.name, text) == 0) {
            *pull = entry.pull;
            return true;
        }
    }
    return false;
}

bool is_output(Mode mode) {
    return mode == Mode::DigitalOut || mode == Mode::Pwm || mode == Mode::Servo;
}

bool uses_two_gpios(Mode mode) {
    return mode == Mode::I2c || mode == Mode::Uart || mode == Mode::Hx711;
}

size_t pin_gpios(const PinConfig& pin, int* gpios) {
    size_t count = 0;
    gpios[count++] = pin.gpio;
    if (uses_two_gpios(pin.mode) && pin.gpio2 >= 0) {
        gpios[count++] = pin.gpio2;
    }
    if (pin.mode == Mode::Hx711 && pin.gpio3 >= 0) {
        gpios[count++] = pin.gpio3;
    }
    return count;
}

int hx711_gain_pulses(uint8_t gain) {
    switch (gain) {
        case 32:
            return 2;
        case 64:
            return 3;
        default:
            return 1;
    }
}

int32_t hx711_decode(uint32_t bits) {
    bits &= 0xFFFFFF;
    if ((bits & 0x800000) != 0) {
        return static_cast<int32_t>(bits | 0xFF000000u);
    }
    return static_cast<int32_t>(bits);
}

bool is_sensor(Mode mode) {
    return mode == Mode::Ds18b20 || mode == Mode::Dht11 || mode == Mode::Dht22;
}

float default_initial(Mode mode) {
    return mode == Mode::Servo ? kDefaultServoAngle : 0.0f;
}

void apply_defaults(PinConfig* pin) {
    if (!uses_two_gpios(pin->mode)) {
        pin->gpio2 = -1;
    }
    if (pin->mode != Mode::Hx711) {
        pin->gpio3 = -1;
    }
    pin->gain = kDefaultHx711Gain;
    pin->pull = Pull::None;
    pin->invert = false;
    pin->initial = default_initial(pin->mode);
    pin->freq_hz = pin->mode == Mode::Servo  ? kServoFreqHz
                   : pin->mode == Mode::I2c ? kDefaultI2cFreqHz
                                            : kDefaultPwmFreqHz;
    pin->baud = kDefaultUartBaud;
    pin->min_us = kDefaultServoMinUs;
    pin->max_us = kDefaultServoMaxUs;
}

const char* validate_pin(const PinConfig& pin) {
    if (pin.id[0] == '\0') {
        return "id is empty";
    }
    if (pin.gpio < 0 || pin.gpio > 63) {
        return "gpio is out of range";
    }
    if (uses_two_gpios(pin.mode)) {
        if (pin.gpio2 < 0 || pin.gpio2 > 63) {
            return pin.mode == Mode::I2c ? "scl is out of range" : "rx is out of range";
        }
        if (pin.gpio2 == pin.gpio) {
            return "the two GPIOs must differ";
        }
    }
    if (pin.mode == Mode::Hx711) {
        if (pin.gpio3 > 63 || pin.gpio3 == pin.gpio || pin.gpio3 == pin.gpio2) {
            return "data2 must be another GPIO";
        }
        if (pin.gain != 128 && pin.gain != 64 && pin.gain != 32) {
            return "gain must be 128, 64 or 32";
        }
    }
    switch (pin.mode) {
        case Mode::DigitalOut:
            if (pin.initial != 0.0f && pin.initial != 1.0f) {
                return "initial must be 0 or 1";
            }
            break;
        case Mode::Pwm:
            if (pin.freq_hz < 1 || pin.freq_hz > kMaxPwmFreqHz) {
                return "freq_hz is out of range";
            }
            if (duty_resolution_bits(pin.freq_hz) == 0) {
                return "freq_hz is too high for the LEDC clock";
            }
            if (!(pin.initial >= 0.0f && pin.initial <= 1.0f)) {
                return "initial duty must be 0.0 to 1.0";
            }
            break;
        case Mode::Servo:
            if (pin.min_us < 100 || pin.min_us >= pin.max_us || pin.max_us > 3000) {
                return "servo pulse must satisfy 100 <= min_us < max_us <= 3000";
            }
            if (!(pin.initial >= 0.0f && pin.initial <= kMaxServoAngle)) {
                return "initial angle must be 0 to 180";
            }
            break;
        case Mode::I2c:
            if (pin.freq_hz < kMinI2cFreqHz || pin.freq_hz > kMaxI2cFreqHz) {
                return "I2C freq_hz must be 1000 to 1000000";
            }
            break;
        case Mode::Uart:
            if (pin.baud < kMinUartBaud || pin.baud > kMaxUartBaud) {
                return "baud must be 300 to 2000000";
            }
            break;
        case Mode::DigitalIn:
        case Mode::Adc:
        case Mode::Ds18b20:
        case Mode::Dht11:
        case Mode::Dht22:
        case Mode::Hx711:
            break;
    }
    return nullptr;
}

const char* validate_config(const Config& config) {
    if (config.report_period_ms < kMinReportPeriodMs ||
        config.report_period_ms > kMaxReportPeriodMs) {
        return "report_period_ms must be 20 to 10000";
    }
    if (config.pin_count > kMaxPins) {
        return "too many pins";
    }
    for (size_t first = 0; first < config.pin_count; ++first) {
        for (size_t second = first + 1; second < config.pin_count; ++second) {
            if (std::strcmp(config.pins[first].id, config.pins[second].id) == 0) {
                return "pin ids must be unique";
            }
            int first_gpios[3];
            int second_gpios[3];
            const size_t first_count = pin_gpios(config.pins[first], first_gpios);
            const size_t second_count = pin_gpios(config.pins[second], second_gpios);
            bool clash = false;
            for (size_t one = 0; one < first_count; ++one) {
                for (size_t two = 0; two < second_count; ++two) {
                    clash = clash || first_gpios[one] == second_gpios[two];
                }
            }
            if (clash) {
                return "gpio numbers must be unique";
            }
        }
    }
    return nullptr;
}

const char* validate_output_value(const PinConfig& pin, float value) {
    switch (pin.mode) {
        case Mode::DigitalOut:
            if (value != 0.0f && value != 1.0f) {
                return "value must be 0 or 1";
            }
            return nullptr;
        case Mode::Pwm:
            if (!(value >= 0.0f && value <= 1.0f)) {
                return "duty must be 0.0 to 1.0";
            }
            return nullptr;
        case Mode::Servo:
            if (!(value >= 0.0f && value <= kMaxServoAngle)) {
                return "angle must be 0 to 180";
            }
            return nullptr;
        default:
            return "pin is not an output";
    }
}

bool physical_level(bool logical, bool invert) {
    return logical != invert;
}

uint32_t duty_resolution_bits(uint32_t freq_hz, uint32_t clock_hz) {
    if (freq_hz == 0) {
        return 0;
    }
    uint32_t divider = clock_hz / freq_hz;
    uint32_t bits = 0;
    while (divider > 1 && bits < kMaxDutyBits) {
        divider >>= 1;
        ++bits;
    }
    return bits;
}

uint32_t pwm_duty(float fraction, uint32_t bits) {
    const uint32_t full = 1u << bits;
    if (!(fraction > 0.0f)) {
        return 0;
    }
    if (fraction >= 1.0f) {
        return full;
    }
    return static_cast<uint32_t>(std::lround(static_cast<double>(fraction) * full));
}

uint32_t servo_pulse_us(const PinConfig& pin, float angle) {
    float clamped = angle;
    if (!(clamped >= 0.0f)) {
        clamped = 0.0f;
    }
    if (clamped > kMaxServoAngle) {
        clamped = kMaxServoAngle;
    }
    const float span = static_cast<float>(pin.max_us - pin.min_us);
    return pin.min_us + static_cast<uint32_t>(std::lround(span * clamped / kMaxServoAngle));
}

uint32_t servo_duty(const PinConfig& pin, float angle, uint32_t bits) {
    const uint64_t full = 1ull << bits;
    return static_cast<uint32_t>((servo_pulse_us(pin, angle) * full + kServoPeriodUs / 2) /
                                 kServoPeriodUs);
}

uint8_t onewire_crc8(const uint8_t* data, size_t length) {
    uint8_t crc = 0;
    for (size_t index = 0; index < length; ++index) {
        uint8_t byte = data[index];
        for (int bit = 0; bit < 8; ++bit) {
            const bool mix = ((crc ^ byte) & 0x01) != 0;
            crc >>= 1;
            if (mix) {
                crc ^= 0x8C;
            }
            byte >>= 1;
        }
    }
    return crc;
}

bool ds18b20_decode(const uint8_t* scratchpad, float* celsius) {
    if (onewire_crc8(scratchpad, 9) != 0) {
        return false;
    }
    const int16_t raw = static_cast<int16_t>(scratchpad[1] << 8 | scratchpad[0]);
    *celsius = raw / 16.0f;
    return true;
}

bool dht_decode(const uint8_t* data, bool dht22, float* celsius, float* humidity) {
    const uint8_t sum = static_cast<uint8_t>(data[0] + data[1] + data[2] + data[3]);
    if (sum != data[4]) {
        return false;
    }
    if (dht22) {
        *humidity = (data[0] << 8 | data[1]) / 10.0f;
        const float magnitude = ((data[2] & 0x7F) << 8 | data[3]) / 10.0f;
        *celsius = (data[2] & 0x80) != 0 ? -magnitude : magnitude;
    } else {
        *humidity = data[0] + data[1] / 10.0f;
        const float magnitude = data[2] + (data[3] & 0x7F) / 10.0f;
        *celsius = (data[3] & 0x80) != 0 ? -magnitude : magnitude;
    }
    return true;
}

uint32_t ledc_freq_hz(const PinConfig& pin) {
    return pin.mode == Mode::Servo ? kServoFreqHz : pin.freq_hz;
}

LedcAllocator::LedcAllocator(int timer_count, int channel_count)
    : timer_count_(timer_count < kMaxTimers ? timer_count : kMaxTimers),
      channel_count_(channel_count) {}

void LedcAllocator::reset() {
    next_channel_ = 0;
    used_timers_ = 0;
    timer_is_new_ = false;
}

const char* LedcAllocator::allocate(uint32_t freq_hz, LedcSlot* slot) {
    timer_is_new_ = false;
    if (next_channel_ >= channel_count_) {
        return "no free LEDC channel";
    }
    int timer = -1;
    for (int index = 0; index < used_timers_; ++index) {
        if (timer_freq_hz_[index] == freq_hz) {
            timer = index;
            break;
        }
    }
    if (timer < 0) {
        if (used_timers_ >= timer_count_) {
            return "no free LEDC timer: too many different PWM frequencies";
        }
        timer = used_timers_++;
        timer_freq_hz_[timer] = freq_hz;
        timer_is_new_ = true;
    }
    slot->timer = timer;
    slot->channel = next_channel_++;
    return nullptr;
}

void HostWatchdog::feed(uint32_t now_ms) {
    last_feed_ms_ = now_ms;
    fed_ = true;
    tripped_ = false;
}

bool HostWatchdog::check(uint32_t now_ms) {
    if (!fed_ || tripped_) {
        return false;
    }
    if (now_ms - last_feed_ms_ < timeout_ms_) {
        return false;
    }
    tripped_ = true;
    return true;
}

}  // namespace pin_model
