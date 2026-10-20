#pragma once

#include <cstddef>
#include <cstdint>

// The pin configuration of the bench agent and the rules that need no hardware:
// value ranges, PWM and servo duty conversion, LEDC timer allocation and the
// host watchdog. Refer to docs/protocol.md for the meaning of each field.
namespace pin_model {

constexpr size_t kMaxPins = 48;
constexpr size_t kMaxIdLength = 23;
constexpr uint32_t kDefaultReportPeriodMs = 100;
constexpr uint32_t kMinReportPeriodMs = 20;
constexpr uint32_t kMaxReportPeriodMs = 10000;
constexpr uint32_t kDefaultPwmFreqHz = 1000;
constexpr uint32_t kMaxPwmFreqHz = 40000000;
constexpr uint32_t kServoFreqHz = 50;
constexpr uint32_t kServoPeriodUs = 1000000 / kServoFreqHz;
constexpr uint16_t kDefaultServoMinUs = 500;
constexpr uint16_t kDefaultServoMaxUs = 2500;
constexpr float kDefaultServoAngle = 90.0f;
constexpr uint32_t kDefaultI2cFreqHz = 100000;
constexpr uint32_t kMinI2cFreqHz = 1000;
constexpr uint32_t kMaxI2cFreqHz = 1000000;
constexpr uint32_t kDefaultUartBaud = 9600;
constexpr uint32_t kMinUartBaud = 300;
constexpr uint32_t kMaxUartBaud = 2000000;
// DHT sensors need at least 1 s (DHT11) or 2 s (DHT22) between reads.
constexpr uint32_t kDhtReadPeriodMs = 2000;
// A DS18B20 conversion at 12 bits takes up to 750 ms.
constexpr uint32_t kDs18b20ReadPeriodMs = 1000;
constexpr uint8_t kDefaultHx711Gain = 128;
// An HX711 converts at 10 or 80 samples per second, so a ready chip pulls its
// data line low within 100 ms. After this time with no data the read counts
// as a timeout.
constexpr uint32_t kHx711TimeoutMs = 400;
constexpr float kMaxServoAngle = 180.0f;
// The LEDC duty resolution is at most 14 bits on the ESP32-S3, C3 and C6.
// The classic ESP32 allows 20, but one limit keeps the behaviour the same.
constexpr uint32_t kMaxDutyBits = 14;
// The LEDC timers run from the 80 MHz APB or PLL clock on all supported chips.
constexpr uint32_t kLedcClockHz = 80000000;

enum class Mode : uint8_t {
    DigitalIn,
    DigitalOut,
    Adc,
    Pwm,
    Servo,
    I2c,
    Uart,
    Ds18b20,
    Dht11,
    Dht22,
    // HX711 load cell amplifier: gpio is the clock, gpio2 the data of the
    // first HX711, gpio3 the data of an optional second HX711 on the same
    // clock.
    Hx711,
};
enum class Pull : uint8_t { None, Up, Down };

struct PinConfig {
    char id[kMaxIdLength + 1];
    // The only GPIO, or SDA for I2C and TX for a UART.
    int gpio;
    // SCL for I2C, RX for a UART, the first data pin for HX711. -1 for
    // single-GPIO modes.
    int gpio2;
    // The second HX711 data pin, or -1.
    int gpio3;
    // HX711 gain and channel: 128 or 64 (channel A) or 32 (channel B).
    uint8_t gain;
    Mode mode;
    Pull pull;
    bool invert;
    float initial;
    // PWM frequency, or I2C clock.
    uint32_t freq_hz;
    uint32_t baud;
    uint16_t min_us;
    uint16_t max_us;
};

struct Config {
    uint32_t report_period_ms;
    size_t pin_count;
    PinConfig pins[kMaxPins];
};

const char* mode_name(Mode mode);
bool parse_mode(const char* text, Mode* mode);
const char* pull_name(Pull pull);
bool parse_pull(const char* text, Pull* pull);

bool is_output(Mode mode);
bool uses_two_gpios(Mode mode);

// The GPIOs of a pin: gpio, then gpio2 and gpio3 when they are used.
// Returns the number of GPIOs.
size_t pin_gpios(const PinConfig& pin, int* gpios);

// The number of extra clock pulses after the 24 data bits, which select the
// gain of the next conversion. Source: HX711 datasheet, table 3.
int hx711_gain_pulses(uint8_t gain);

// The signed value of the 24 data bits of an HX711, most significant bit first.
int32_t hx711_decode(uint32_t bits);
bool is_sensor(Mode mode);
float default_initial(Mode mode);

// Fills a pin with the defaults of its mode. The id, gpio and, for two-GPIO
// modes, gpio2 are not changed. Single-GPIO modes get gpio2 = -1.
void apply_defaults(PinConfig* pin);

// Returns nullptr if the pin fields are in range, or a static error text.
const char* validate_pin(const PinConfig& pin);

// Returns nullptr if the report period, ids and GPIOs are valid and unique, or
// a static error text. Pin field errors are reported per pin by validate_pin.
const char* validate_config(const Config& config);

// Returns nullptr if value is a valid output value for the pin, or a static error text.
const char* validate_output_value(const PinConfig& pin, float value);

// The physical pin level for a logical level.
bool physical_level(bool logical, bool invert);

// The LEDC duty resolution for a timer frequency, or 0 if the frequency is too high.
uint32_t duty_resolution_bits(uint32_t freq_hz, uint32_t clock_hz = kLedcClockHz);

// The LEDC duty value for a duty cycle from 0.0 to 1.0.
uint32_t pwm_duty(float fraction, uint32_t bits);

// The servo pulse width for an angle from 0 to 180 degrees.
uint32_t servo_pulse_us(const PinConfig& pin, float angle);

// The LEDC duty value at 50 Hz for a servo angle.
uint32_t servo_duty(const PinConfig& pin, float angle, uint32_t bits);

// The Dallas/Maxim 1-Wire CRC-8 (polynomial x^8 + x^5 + x^4 + 1). The CRC of
// data that ends with its own CRC byte is 0.
uint8_t onewire_crc8(const uint8_t* data, size_t length);

// Decodes a 9-byte DS18B20 scratchpad. Returns false if the CRC is wrong.
// Source: DS18B20 datasheet, "Memory" and "Operation - Measuring Temperature".
bool ds18b20_decode(const uint8_t* scratchpad, float* celsius);

// Decodes the 5 data bytes of a DHT11 or DHT22. Returns false if the checksum
// is wrong. Source: Aosong DHT11 and AM2302 (DHT22) datasheets.
bool dht_decode(const uint8_t* data, bool dht22, float* celsius, float* humidity);

// The LEDC frequency that a pin needs: freq_hz for PWM, 50 Hz for a servo.
uint32_t ledc_freq_hz(const PinConfig& pin);

struct LedcSlot {
    int timer;
    int channel;
};

// Gives each PWM or servo pin an LEDC channel, and shares one timer between
// all pins with the same frequency.
class LedcAllocator {
public:
    static constexpr int kMaxTimers = 4;

    LedcAllocator(int timer_count, int channel_count);

    void reset();

    // Returns nullptr and sets slot, or returns a static error text.
    const char* allocate(uint32_t freq_hz, LedcSlot* slot);

    // True when allocate gave this timer for the first time in its last call,
    // so the caller must configure the timer.
    bool timer_is_new() const { return timer_is_new_; }

private:
    int timer_count_;
    int channel_count_;
    int next_channel_ = 0;
    int used_timers_ = 0;
    uint32_t timer_freq_hz_[kMaxTimers] = {};
    bool timer_is_new_ = false;
};

// Trips when the host sends nothing for timeout_ms.
class HostWatchdog {
public:
    explicit HostWatchdog(uint32_t timeout_ms) : timeout_ms_(timeout_ms) {}

    void feed(uint32_t now_ms);

    // Returns true one time, at the first check after the timeout. Feeding the
    // watchdog arms it again.
    bool check(uint32_t now_ms);

    bool tripped() const { return tripped_; }

private:
    uint32_t timeout_ms_;
    uint32_t last_feed_ms_ = 0;
    bool fed_ = false;
    bool tripped_ = false;
};

}  // namespace pin_model
