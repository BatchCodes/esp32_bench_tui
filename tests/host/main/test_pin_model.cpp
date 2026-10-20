#include <cstring>
#include <initializer_list>

#include "pin_model/pin_model.hpp"
#include "tests.hpp"
#include "unity.h"

using namespace pin_model;

namespace {

PinConfig make_pin(const char* id, int gpio, Mode mode) {
    PinConfig pin = {};
    std::strncpy(pin.id, id, kMaxIdLength);
    pin.gpio = gpio;
    pin.mode = mode;
    pin.gpio2 = -1;
    pin.gpio3 = -1;
    apply_defaults(&pin);
    return pin;
}

void test_mode_names_round_trip() {
    for (Mode mode : {Mode::DigitalIn, Mode::DigitalOut, Mode::Adc, Mode::Pwm, Mode::Servo}) {
        Mode parsed = Mode::Adc;
        TEST_ASSERT_TRUE(parse_mode(mode_name(mode), &parsed));
        TEST_ASSERT_EQUAL(static_cast<int>(mode), static_cast<int>(parsed));
    }
    Mode unused = Mode::Adc;
    TEST_ASSERT_FALSE(parse_mode("motor", &unused));
    Pull pull = Pull::None;
    TEST_ASSERT_TRUE(parse_pull("down", &pull));
    TEST_ASSERT_EQUAL(static_cast<int>(Pull::Down), static_cast<int>(pull));
}

void test_defaults() {
    PinConfig servo = make_pin("arm", 13, Mode::Servo);
    TEST_ASSERT_EQUAL_FLOAT(90.0f, servo.initial);
    TEST_ASSERT_EQUAL_UINT32(50, ledc_freq_hz(servo));
    PinConfig pwm = make_pin("fan", 4, Mode::Pwm);
    TEST_ASSERT_EQUAL_UINT32(1000, ledc_freq_hz(pwm));
    TEST_ASSERT_NULL(validate_pin(servo));
    TEST_ASSERT_NULL(validate_pin(pwm));
}

void test_validate_pin() {
    PinConfig pin = make_pin("led", 2, Mode::DigitalOut);
    pin.initial = 0.5f;
    TEST_ASSERT_NOT_NULL(validate_pin(pin));
    pin = make_pin("fan", 4, Mode::Pwm);
    pin.freq_hz = 50000000;
    TEST_ASSERT_NOT_NULL(validate_pin(pin));
    pin = make_pin("arm", 13, Mode::Servo);
    pin.min_us = 2500;
    pin.max_us = 500;
    TEST_ASSERT_NOT_NULL(validate_pin(pin));
    pin = make_pin("", 13, Mode::Adc);
    TEST_ASSERT_NOT_NULL(validate_pin(pin));
}

void test_validate_config() {
    Config config = {};
    config.report_period_ms = 100;
    config.pin_count = 2;
    config.pins[0] = make_pin("a", 2, Mode::DigitalOut);
    config.pins[1] = make_pin("b", 4, Mode::DigitalIn);
    TEST_ASSERT_NULL(validate_config(config));
    config.pins[1].gpio = 2;
    TEST_ASSERT_NOT_NULL(validate_config(config));
    config.pins[1] = make_pin("a", 4, Mode::DigitalIn);
    TEST_ASSERT_NOT_NULL(validate_config(config));
    config.pins[1] = make_pin("b", 4, Mode::DigitalIn);
    config.report_period_ms = 5;
    TEST_ASSERT_NOT_NULL(validate_config(config));
}

void test_output_values() {
    PinConfig led = make_pin("led", 2, Mode::DigitalOut);
    TEST_ASSERT_NULL(validate_output_value(led, 1.0f));
    TEST_ASSERT_NOT_NULL(validate_output_value(led, 2.0f));
    PinConfig fan = make_pin("fan", 4, Mode::Pwm);
    TEST_ASSERT_NULL(validate_output_value(fan, 0.5f));
    TEST_ASSERT_NOT_NULL(validate_output_value(fan, 1.5f));
    PinConfig arm = make_pin("arm", 13, Mode::Servo);
    TEST_ASSERT_NULL(validate_output_value(arm, 180.0f));
    TEST_ASSERT_NOT_NULL(validate_output_value(arm, -1.0f));
    PinConfig button = make_pin("button", 0, Mode::DigitalIn);
    TEST_ASSERT_NOT_NULL(validate_output_value(button, 1.0f));
}

void test_physical_level() {
    TEST_ASSERT_TRUE(physical_level(true, false));
    TEST_ASSERT_FALSE(physical_level(true, true));
    TEST_ASSERT_TRUE(physical_level(false, true));
}

void test_duty_resolution() {
    TEST_ASSERT_EQUAL_UINT32(14, duty_resolution_bits(50));
    TEST_ASSERT_EQUAL_UINT32(14, duty_resolution_bits(1000));
    TEST_ASSERT_EQUAL_UINT32(11, duty_resolution_bits(25000));
    TEST_ASSERT_EQUAL_UINT32(1, duty_resolution_bits(40000000));
    TEST_ASSERT_EQUAL_UINT32(0, duty_resolution_bits(0));
}

void test_pwm_duty() {
    TEST_ASSERT_EQUAL_UINT32(0, pwm_duty(0.0f, 10));
    TEST_ASSERT_EQUAL_UINT32(512, pwm_duty(0.5f, 10));
    TEST_ASSERT_EQUAL_UINT32(1024, pwm_duty(1.0f, 10));
    TEST_ASSERT_EQUAL_UINT32(0, pwm_duty(-0.5f, 10));
}

void test_servo() {
    PinConfig arm = make_pin("arm", 13, Mode::Servo);
    TEST_ASSERT_EQUAL_UINT32(500, servo_pulse_us(arm, 0.0f));
    TEST_ASSERT_EQUAL_UINT32(1500, servo_pulse_us(arm, 90.0f));
    TEST_ASSERT_EQUAL_UINT32(2500, servo_pulse_us(arm, 180.0f));
    TEST_ASSERT_EQUAL_UINT32(2500, servo_pulse_us(arm, 270.0f));
    // 1500 us of a 20000 us period at 14 bits: 16384 * 0.075 = 1228.8.
    TEST_ASSERT_EQUAL_UINT32(1229, servo_duty(arm, 90.0f, 14));
}

void test_ledc_allocator() {
    LedcAllocator allocator(2, 3);
    LedcSlot slot = {};
    TEST_ASSERT_NULL(allocator.allocate(50, &slot));
    TEST_ASSERT_TRUE(allocator.timer_is_new());
    TEST_ASSERT_EQUAL(0, slot.timer);
    TEST_ASSERT_EQUAL(0, slot.channel);
    TEST_ASSERT_NULL(allocator.allocate(50, &slot));
    TEST_ASSERT_FALSE(allocator.timer_is_new());
    TEST_ASSERT_EQUAL(0, slot.timer);
    TEST_ASSERT_EQUAL(1, slot.channel);
    TEST_ASSERT_NULL(allocator.allocate(1000, &slot));
    TEST_ASSERT_EQUAL(1, slot.timer);
    TEST_ASSERT_NOT_NULL(allocator.allocate(1000, &slot));
    allocator.reset();
    TEST_ASSERT_NULL(allocator.allocate(25000, &slot));
    TEST_ASSERT_EQUAL(0, slot.timer);
    TEST_ASSERT_NULL(allocator.allocate(50, &slot));
    TEST_ASSERT_EQUAL(1, slot.timer);
    TEST_ASSERT_EQUAL(1, slot.channel);
}

void test_ledc_allocator_timer_limit() {
    LedcAllocator allocator(2, 8);
    LedcSlot slot = {};
    TEST_ASSERT_NULL(allocator.allocate(50, &slot));
    TEST_ASSERT_NULL(allocator.allocate(1000, &slot));
    TEST_ASSERT_NOT_NULL(allocator.allocate(2000, &slot));
}

void test_two_gpio_modes() {
    PinConfig bus = make_pin("bus", 21, Mode::I2c);
    bus.gpio2 = 22;
    TEST_ASSERT_TRUE(uses_two_gpios(bus.mode));
    TEST_ASSERT_EQUAL_UINT32(100000, bus.freq_hz);
    TEST_ASSERT_NULL(validate_pin(bus));
    bus.gpio2 = 21;
    TEST_ASSERT_NOT_NULL(validate_pin(bus));
    bus.gpio2 = 22;
    bus.freq_hz = 5000000;
    TEST_ASSERT_NOT_NULL(validate_pin(bus));

    PinConfig gps = make_pin("gps", 17, Mode::Uart);
    gps.gpio2 = 16;
    TEST_ASSERT_EQUAL_UINT32(9600, gps.baud);
    TEST_ASSERT_NULL(validate_pin(gps));
    gps.baud = 100;
    TEST_ASSERT_NOT_NULL(validate_pin(gps));

    PinConfig water = make_pin("water", 4, Mode::Ds18b20);
    TEST_ASSERT_EQUAL(-1, water.gpio2);
    TEST_ASSERT_TRUE(is_sensor(water.mode));
    TEST_ASSERT_NOT_NULL(validate_output_value(water, 1.0f));

    Config config = {};
    config.report_period_ms = 100;
    config.pin_count = 2;
    config.pins[0] = make_pin("bus", 21, Mode::I2c);
    config.pins[0].gpio2 = 22;
    config.pins[1] = make_pin("led", 22, Mode::DigitalOut);
    TEST_ASSERT_NOT_NULL(validate_config(config));
    config.pins[1].gpio = 23;
    TEST_ASSERT_NULL(validate_config(config));
}

void test_onewire_crc8() {
    uint8_t scratchpad[9] = {0x91, 0x01, 0x4B, 0x46, 0x7F, 0xFF, 0x0C, 0x10, 0x00};
    scratchpad[8] = onewire_crc8(scratchpad, 8);
    TEST_ASSERT_EQUAL_HEX8(0x70, scratchpad[8]);
    TEST_ASSERT_EQUAL_HEX8(0x00, onewire_crc8(scratchpad, 9));
}

void test_ds18b20_decode() {
    // 0x0191 is +25.0625 C, the example in the DS18B20 datasheet table 1.
    uint8_t scratchpad[9] = {0x91, 0x01, 0x4B, 0x46, 0x7F, 0xFF, 0x0C, 0x10, 0x70};
    float celsius = 0.0f;
    TEST_ASSERT_TRUE(ds18b20_decode(scratchpad, &celsius));
    TEST_ASSERT_EQUAL_FLOAT(25.0625f, celsius);
    // 0xFF5E is -10.125 C.
    uint8_t negative[9] = {0x5E, 0xFF, 0x4B, 0x46, 0x7F, 0xFF, 0x0C, 0x10, 0x6A};
    TEST_ASSERT_TRUE(ds18b20_decode(negative, &celsius));
    TEST_ASSERT_EQUAL_FLOAT(-10.125f, celsius);
    negative[0] ^= 0x01;
    TEST_ASSERT_FALSE(ds18b20_decode(negative, &celsius));
}

void test_dht_decode() {
    float celsius = 0.0f;
    float humidity = 0.0f;
    // AM2302 datasheet example: 65.2 %RH, 35.1 C.
    const uint8_t dht22[5] = {0x02, 0x8C, 0x01, 0x5F, 0xEE};
    TEST_ASSERT_TRUE(dht_decode(dht22, true, &celsius, &humidity));
    TEST_ASSERT_EQUAL_FLOAT(65.2f, humidity);
    TEST_ASSERT_EQUAL_FLOAT(35.1f, celsius);
    // -10.1 C.
    const uint8_t cold[5] = {0x02, 0x8C, 0x80, 0x65, 0x73};
    TEST_ASSERT_TRUE(dht_decode(cold, true, &celsius, &humidity));
    TEST_ASSERT_EQUAL_FLOAT(-10.1f, celsius);
    const uint8_t dht11[5] = {40, 0, 23, 5, 68};
    TEST_ASSERT_TRUE(dht_decode(dht11, false, &celsius, &humidity));
    TEST_ASSERT_EQUAL_FLOAT(40.0f, humidity);
    TEST_ASSERT_EQUAL_FLOAT(23.5f, celsius);
    const uint8_t bad[5] = {40, 0, 23, 5, 69};
    TEST_ASSERT_FALSE(dht_decode(bad, false, &celsius, &humidity));
}

void test_hx711() {
    TEST_ASSERT_EQUAL_INT32(0, hx711_decode(0x000000));
    TEST_ASSERT_EQUAL_INT32(8388607, hx711_decode(0x7FFFFF));
    TEST_ASSERT_EQUAL_INT32(-8388608, hx711_decode(0x800000));
    TEST_ASSERT_EQUAL_INT32(-1, hx711_decode(0xFFFFFF));
    TEST_ASSERT_EQUAL(1, hx711_gain_pulses(128));
    TEST_ASSERT_EQUAL(3, hx711_gain_pulses(64));
    TEST_ASSERT_EQUAL(2, hx711_gain_pulses(32));

    PinConfig scales = make_pin("scales", 18, Mode::Hx711);
    scales.gpio2 = 19;
    scales.gpio3 = 21;
    TEST_ASSERT_TRUE(uses_two_gpios(scales.mode));
    TEST_ASSERT_EQUAL(128, scales.gain);
    TEST_ASSERT_NULL(validate_pin(scales));
    int gpios[3];
    TEST_ASSERT_EQUAL_size_t(3, pin_gpios(scales, gpios));
    TEST_ASSERT_EQUAL(21, gpios[2]);
    scales.gpio3 = 19;
    TEST_ASSERT_NOT_NULL(validate_pin(scales));
    scales.gpio3 = 21;
    scales.gain = 100;
    TEST_ASSERT_NOT_NULL(validate_pin(scales));

    Config config = {};
    config.report_period_ms = 100;
    config.pin_count = 2;
    config.pins[0] = make_pin("scales", 18, Mode::Hx711);
    config.pins[0].gpio2 = 19;
    config.pins[0].gpio3 = 21;
    config.pins[1] = make_pin("led", 21, Mode::DigitalOut);
    TEST_ASSERT_NOT_NULL(validate_config(config));
    config.pins[1].gpio = 22;
    TEST_ASSERT_NULL(validate_config(config));
}

void test_watchdog() {
    HostWatchdog watchdog(2000);
    TEST_ASSERT_FALSE(watchdog.check(100000));
    watchdog.feed(1000);
    TEST_ASSERT_FALSE(watchdog.check(2999));
    TEST_ASSERT_TRUE(watchdog.check(3000));
    TEST_ASSERT_TRUE(watchdog.tripped());
    TEST_ASSERT_FALSE(watchdog.check(4000));
    watchdog.feed(5000);
    TEST_ASSERT_FALSE(watchdog.tripped());
    TEST_ASSERT_TRUE(watchdog.check(7000));
}

void test_watchdog_wraps() {
    HostWatchdog watchdog(2000);
    watchdog.feed(0xFFFFFF00u);
    TEST_ASSERT_FALSE(watchdog.check(0x00000100u));
    TEST_ASSERT_TRUE(watchdog.check(0x00000800u));
}

}  // namespace

void run_pin_model_tests() {
    RUN_TEST(test_mode_names_round_trip);
    RUN_TEST(test_defaults);
    RUN_TEST(test_validate_pin);
    RUN_TEST(test_validate_config);
    RUN_TEST(test_output_values);
    RUN_TEST(test_physical_level);
    RUN_TEST(test_duty_resolution);
    RUN_TEST(test_pwm_duty);
    RUN_TEST(test_servo);
    RUN_TEST(test_ledc_allocator);
    RUN_TEST(test_ledc_allocator_timer_limit);
    RUN_TEST(test_two_gpio_modes);
    RUN_TEST(test_onewire_crc8);
    RUN_TEST(test_ds18b20_decode);
    RUN_TEST(test_dht_decode);
    RUN_TEST(test_hx711);
    RUN_TEST(test_watchdog);
    RUN_TEST(test_watchdog_wraps);
}
