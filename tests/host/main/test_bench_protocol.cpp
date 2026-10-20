#include <cmath>
#include <cstring>
#include <string>

#include "bench_protocol/bench_protocol.hpp"
#include "tests.hpp"
#include "unity.h"

using namespace bench_protocol;
using pin_model::Mode;

namespace {

HostMessage message;

ParseResult parse(const char* line) {
    std::memset(&message, 0, sizeof(message));
    return parse_host_message(line, std::strlen(line), &message);
}

void assert_message_line(const std::string& line) {
    TEST_ASSERT_EQUAL_INT(0, line.compare(0, std::strlen(kMessagePrefix), kMessagePrefix));
    TEST_ASSERT_EQUAL_CHAR('\n', line.back());
    TEST_ASSERT_EQUAL_size_t(line.size() - 1, line.find('\n'));
}

void test_parse_hello_and_ping() {
    ParseResult result = parse(R"({"type":"hello","seq":1})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_EQUAL(static_cast<int>(HostMessageType::Hello), static_cast<int>(message.type));
    TEST_ASSERT_EQUAL_UINT32(1, result.seq);
    result = parse(R"({"type":"ping","seq":42})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_EQUAL(static_cast<int>(HostMessageType::Ping), static_cast<int>(message.type));
    TEST_ASSERT_EQUAL_UINT32(42, message.seq);
}

void test_parse_config() {
    ParseResult result = parse(
        R"({"type":"config","seq":2,"report_period_ms":50,"pins":[)"
        R"({"id":"led","gpio":2,"mode":"digital_out","invert":true,"initial":1},)"
        R"({"id":"button","gpio":0,"mode":"digital_in","pull":"up"},)"
        R"({"id":"pot","gpio":34,"mode":"adc"},)"
        R"({"id":"fan","gpio":4,"mode":"pwm","freq_hz":25000,"initial":0.25},)"
        R"({"id":"arm","gpio":13,"mode":"servo","min_us":600,"max_us":2400}]})");
    TEST_ASSERT_TRUE_MESSAGE(result.ok, result.error.c_str());
    const pin_model::Config& config = message.config;
    TEST_ASSERT_EQUAL_UINT32(50, config.report_period_ms);
    TEST_ASSERT_EQUAL_size_t(5, config.pin_count);
    for (size_t index = 0; index < config.pin_count; ++index) {
        TEST_ASSERT_NULL(message.pin_errors[index]);
    }
    TEST_ASSERT_EQUAL_STRING("led", config.pins[0].id);
    TEST_ASSERT_TRUE(config.pins[0].invert);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, config.pins[0].initial);
    TEST_ASSERT_EQUAL(static_cast<int>(pin_model::Pull::Up), static_cast<int>(config.pins[1].pull));
    TEST_ASSERT_EQUAL(static_cast<int>(Mode::Adc), static_cast<int>(config.pins[2].mode));
    TEST_ASSERT_EQUAL_UINT32(25000, config.pins[3].freq_hz);
    TEST_ASSERT_EQUAL_FLOAT(0.25f, config.pins[3].initial);
    TEST_ASSERT_EQUAL_UINT16(600, config.pins[4].min_us);
    TEST_ASSERT_EQUAL_FLOAT(90.0f, config.pins[4].initial);
}

void test_parse_config_pin_errors() {
    ParseResult result = parse(
        R"({"type":"config","seq":3,"pins":[)"
        R"({"id":"led","gpio":2,"mode":"digital_out"},)"
        R"({"id":"bad","gpio":4,"mode":"motor"},)"
        R"({"id":"fan","gpio":5,"mode":"pwm","initial":3}]})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_EQUAL_UINT32(100, message.config.report_period_ms);
    TEST_ASSERT_NULL(message.pin_errors[0]);
    TEST_ASSERT_NOT_NULL(message.pin_errors[1]);
    TEST_ASSERT_NOT_NULL(message.pin_errors[2]);
}

void test_parse_config_errors() {
    TEST_ASSERT_FALSE(parse(R"({"type":"config","seq":4})").ok);
    ParseResult result = parse(
        R"({"type":"config","seq":5,"pins":[)"
        R"({"id":"a","gpio":2,"mode":"adc"},{"id":"b","gpio":2,"mode":"adc"}]})");
    TEST_ASSERT_FALSE(result.ok);
    TEST_ASSERT_EQUAL_UINT32(5, result.seq);
    std::string many = R"({"type":"config","seq":6,"pins":[)";
    for (int index = 0; index < 49; ++index) {
        many += std::string(index == 0 ? "" : ",") + R"({"id":"p)" + std::to_string(index) +
                R"(","gpio":)" + std::to_string(index) + R"(,"mode":"adc"})";
    }
    many += "]}";
    TEST_ASSERT_FALSE(parse(many.c_str()).ok);
}

void test_parse_set() {
    ParseResult result = parse(R"({"type":"set","seq":7,"id":"fan","value":0.5})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_EQUAL_STRING("fan", message.target_id);
    TEST_ASSERT_EQUAL_FLOAT(0.5f, message.set_value);
    TEST_ASSERT_FALSE(parse(R"({"type":"set","seq":8,"id":"fan"})").ok);
    TEST_ASSERT_FALSE(parse(R"({"type":"set","seq":9,"value":1})").ok);
}

void test_parse_bad_lines() {
    TEST_ASSERT_FALSE(parse("I (123) main: hello").ok);
    TEST_ASSERT_FALSE(parse(R"({"seq":1})").ok);
    ParseResult result = parse(R"({"type":"reboot","seq":10})");
    TEST_ASSERT_FALSE(result.ok);
    TEST_ASSERT_EQUAL_UINT32(10, result.seq);
    TEST_ASSERT_FALSE(parse(R"({"type":"hello","seq":-1})").ok);
}

void test_encode_hello() {
    AgentInfo info = {"0.1.0", "esp32", 301, 2, "24:6f:28:aa:bb:cc", 4, 281000};
    std::string line = encode_hello(1, info);
    assert_message_line(line);
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"hello\",\"seq\":1,\"protocol\":6,\"agent\":\"0.1.0\",\"chip\":\"esp32\","
        "\"revision\":301,\"cores\":2,\"mac\":\"24:6f:28:aa:bb:cc\",\"flash_mb\":4,"
        "\"free_heap\":281000}\n",
        line.c_str());
}

void test_encode_state() {
    PinValue values[] = {
        {"led", Mode::DigitalOut, 1.0f, 0.0f, 0},  {"button", Mode::DigitalIn, 0.0f, 0.0f, 14},
        {"pot", Mode::Adc, 1650.4f, 0.0f, 0},      {"fan", Mode::Pwm, 0.1f, 0.0f, 0},
        {"arm", Mode::Servo, 90.04f, 0.0f, 0},
    };
    std::string line = encode_state(123456, values, 5);
    assert_message_line(line);
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"state\",\"seq\":0,\"uptime_ms\":123456,\"values\":{\"led\":1,\"button\":0,"
        "\"pot\":1650,\"fan\":0.1,\"arm\":90},\"edges\":{\"button\":14}}\n",
        line.c_str());
}

void test_encode_replies() {
    PinError errors[] = {{"pot", "gpio 2 has no ADC channel"}};
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"config_ack\",\"seq\":2,\"ok\":false,\"errors\":[{\"id\":\"pot\",\"error\":"
        "\"gpio 2 has no ADC channel\"}]}\n",
        encode_config_ack(2, errors, 1).c_str());
    TEST_ASSERT_EQUAL_STRING("{\"type\":\"config_ack\",\"seq\":2,\"ok\":true,\"errors\":[]}\n",
                             encode_config_ack(2, nullptr, 0).c_str());
    TEST_ASSERT_EQUAL_STRING("{\"type\":\"ack\",\"seq\":3}\n", encode_ack(3).c_str());
    TEST_ASSERT_EQUAL_STRING("{\"type\":\"error\",\"seq\":3,\"error\":\"say \\\"no\\\"\"}\n",
                             encode_error(3, "say \"no\"").c_str());
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"pong\",\"seq\":4,\"uptime_ms\":124000,\"free_heap\":280512}\n",
        encode_pong(4, 124000, 280512).c_str());
    TEST_ASSERT_EQUAL_STRING("{\"type\":\"event\",\"seq\":0,\"event\":\"watchdog\"}\n",
                             encode_event("watchdog").c_str());
}

void test_line_reader() {
    LineReader reader;
    const char* input = "ab\r\n\ncd\n";
    std::string lines;
    for (const char* byte = input; *byte != '\0'; ++byte) {
        if (reader.push(*byte)) {
            lines += std::string(reader.line(), reader.length()) + "|";
        }
    }
    TEST_ASSERT_EQUAL_STRING("ab|cd|", lines.c_str());
    TEST_ASSERT_FALSE(reader.overflowed());
}

void test_line_reader_overflow() {
    LineReader reader;
    for (size_t index = 0; index < kMaxLineLength + 10; ++index) {
        TEST_ASSERT_FALSE(reader.push('x'));
    }
    TEST_ASSERT_FALSE(reader.push('\n'));
    TEST_ASSERT_TRUE(reader.overflowed());
    TEST_ASSERT_FALSE(reader.overflowed());
    TEST_ASSERT_FALSE(reader.push('o'));
    TEST_ASSERT_FALSE(reader.push('k'));
    TEST_ASSERT_TRUE(reader.push('\n'));
    TEST_ASSERT_EQUAL_STRING("ok", reader.line());
}

void test_parse_two_gpio_pins() {
    ParseResult result = parse(
        R"({"type":"config","seq":2,"pins":[)"
        R"({"id":"bus","mode":"i2c","sda":21,"scl":22,"freq_hz":400000},)"
        R"({"id":"gps","mode":"uart","tx":17,"rx":16,"baud":9600},)"
        R"({"id":"water","gpio":4,"mode":"ds18b20"},)"
        R"({"id":"room","gpio":5,"mode":"dht22"}]})");
    TEST_ASSERT_TRUE_MESSAGE(result.ok, result.error.c_str());
    for (size_t index = 0; index < 4; ++index) {
        TEST_ASSERT_NULL(message.pin_errors[index]);
    }
    const pin_model::Config& config = message.config;
    TEST_ASSERT_EQUAL(21, config.pins[0].gpio);
    TEST_ASSERT_EQUAL(22, config.pins[0].gpio2);
    TEST_ASSERT_EQUAL_UINT32(400000, config.pins[0].freq_hz);
    TEST_ASSERT_EQUAL(17, config.pins[1].gpio);
    TEST_ASSERT_EQUAL(16, config.pins[1].gpio2);
    TEST_ASSERT_EQUAL_UINT32(9600, config.pins[1].baud);
    TEST_ASSERT_EQUAL(-1, config.pins[2].gpio2);
    TEST_ASSERT_EQUAL(static_cast<int>(Mode::Dht22), static_cast<int>(config.pins[3].mode));

    result = parse(
        R"({"type":"config","seq":3,"pins":[)"
        R"({"id":"bus","mode":"i2c","sda":21,"scl":22},{"id":"led","gpio":22,"mode":"digital_out"}]})");
    TEST_ASSERT_FALSE(result.ok);
    result = parse(R"({"type":"config","seq":4,"pins":[{"id":"bus","mode":"i2c","sda":21}]})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_NOT_NULL(message.pin_errors[0]);
}

void test_parse_i2c_and_uart_requests() {
    TEST_ASSERT_TRUE(parse(R"({"type":"i2c_scan","seq":5,"id":"bus"})").ok);
    TEST_ASSERT_EQUAL(static_cast<int>(HostMessageType::I2cScan), static_cast<int>(message.type));
    ParseResult result =
        parse(R"({"type":"i2c_read","seq":6,"id":"bus","address":118,"register":208,"length":2})");
    TEST_ASSERT_TRUE_MESSAGE(result.ok, result.error.c_str());
    TEST_ASSERT_EQUAL(0x76, message.i2c_address);
    TEST_ASSERT_EQUAL(0xD0, message.i2c_register);
    TEST_ASSERT_EQUAL_size_t(2, message.read_length);
    result = parse(R"({"type":"i2c_write","seq":7,"id":"bus","address":60,"data":"00AF"})");
    TEST_ASSERT_TRUE_MESSAGE(result.ok, result.error.c_str());
    TEST_ASSERT_EQUAL(-1, message.i2c_register);
    TEST_ASSERT_EQUAL_size_t(2, message.data_length);
    TEST_ASSERT_EQUAL_HEX8(0xAF, message.data[1]);
    TEST_ASSERT_FALSE(parse(R"({"type":"i2c_read","seq":8,"id":"bus","address":200})").ok);
    TEST_ASSERT_FALSE(parse(R"({"type":"i2c_read","seq":9,"id":"bus","address":60,"length":33})").ok);
    result = parse(R"({"type":"uart_send","seq":10,"id":"gps","data":"48690d0a"})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_EQUAL_size_t(4, message.data_length);
    TEST_ASSERT_FALSE(parse(R"({"type":"uart_send","seq":11,"id":"gps","data":"abc"})").ok);
}

void test_encode_bus_messages() {
    const uint8_t addresses[] = {0x3c, 0x76};
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"i2c_scan_result\",\"seq\":5,\"id\":\"bus\",\"addresses\":[60,118]}\n",
        encode_i2c_scan_result(5, "bus", addresses, 2).c_str());
    const uint8_t data[] = {0x60, 0x0a};
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"i2c_data\",\"seq\":6,\"id\":\"bus\",\"address\":118,\"register\":208,"
        "\"data\":\"600a\"}\n",
        encode_i2c_data(6, "bus", 0x76, 0xD0, data, 2).c_str());
    TEST_ASSERT_EQUAL_STRING("{\"type\":\"uart_data\",\"seq\":0,\"id\":\"gps\",\"data\":\"600a\"}\n",
                             encode_uart_data("gps", data, 2).c_str());
}

void test_encode_sensor_state() {
    PinValue values[] = {
        {"room", Mode::Dht22, 21.456f, 40.04f, 0},
        {"water", Mode::Ds18b20, NAN, 0.0f, 0},
        {"bus", Mode::I2c, 2.0f, 0.0f, 0},
    };
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"state\",\"seq\":0,\"uptime_ms\":1,\"values\":{\"room\":21.46,\"water\":null,"
        "\"bus\":2},\"edges\":{},\"humidity\":{\"room\":40}}\n",
        encode_state(1, values, 3).c_str());
}

void test_hx711_messages() {
    ParseResult result = parse(
        R"({"type":"config","seq":2,"pins":[{"id":"scales","mode":"hx711","clock":18,"data":19,"data2":21}]})");
    TEST_ASSERT_TRUE_MESSAGE(result.ok, result.error.c_str());
    TEST_ASSERT_NULL(message.pin_errors[0]);
    TEST_ASSERT_EQUAL(18, message.config.pins[0].gpio);
    TEST_ASSERT_EQUAL(19, message.config.pins[0].gpio2);
    TEST_ASSERT_EQUAL(21, message.config.pins[0].gpio3);
    TEST_ASSERT_EQUAL(128, message.config.pins[0].gain);
    result = parse(R"({"type":"config","seq":3,"pins":[{"id":"one","mode":"hx711","clock":18,"data":19,"gain":64}]})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_EQUAL(-1, message.config.pins[0].gpio3);
    TEST_ASSERT_EQUAL(64, message.config.pins[0].gain);
    result = parse(R"({"type":"config","seq":4,"pins":[{"id":"bad","mode":"hx711","clock":18}]})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_NOT_NULL(message.pin_errors[0]);

    PinValue value = {};
    value.id = "scales";
    value.mode = Mode::Hx711;
    value.value = -12345.0f;
    value.extra = 6789.0f;
    value.ready[0] = true;
    value.ready[1] = false;
    value.timeouts[1] = 3;
    value.reads = 40;
    value.has_second = true;
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"state\",\"seq\":0,\"uptime_ms\":5,\"values\":{\"scales\":-12345},\"edges\":{},"
        "\"hx711\":{\"scales\":{\"raw2\":6789,\"ready\":[true,false],\"timeouts\":[0,3],\"reads\":40}}}\n",
        encode_state(5, &value, 1).c_str());
}

void test_hex() {
    uint8_t data[4] = {};
    size_t length = 0;
    TEST_ASSERT_TRUE(from_hex("00ffA5", data, sizeof(data), &length));
    TEST_ASSERT_EQUAL_size_t(3, length);
    TEST_ASSERT_EQUAL_STRING("00ffa5", to_hex(data, length).c_str());
    TEST_ASSERT_FALSE(from_hex("0g", data, sizeof(data), &length));
    TEST_ASSERT_FALSE(from_hex("0011223344", data, sizeof(data), &length));
}

void test_parse_radio_messages() {
    ParseResult result =
        parse(R"({"type":"radio","seq":1,"wifi_scan_ms":5000,"sniffer":true,"ble_scan":false,"ble_active":true})");
    TEST_ASSERT_TRUE_MESSAGE(result.ok, result.error.c_str());
    TEST_ASSERT_EQUAL(static_cast<int>(HostMessageType::Radio), static_cast<int>(message.type));
    TEST_ASSERT_EQUAL_UINT32(5000, message.wifi_scan_ms);
    TEST_ASSERT_TRUE(message.sniffer);
    TEST_ASSERT_FALSE(message.ble_scan);
    TEST_ASSERT_TRUE(message.ble_active);
    TEST_ASSERT_TRUE(parse(R"({"type":"radio","seq":2})").ok);
    TEST_ASSERT_EQUAL_UINT32(0, message.wifi_scan_ms);
    TEST_ASSERT_FALSE(parse(R"({"type":"radio","seq":3,"wifi_scan_ms":100})").ok);
    TEST_ASSERT_FALSE(parse(R"({"type":"radio","seq":4,"sniffer":1})").ok);

    result = parse(R"({"type":"wifi_connect","seq":5,"ssid":"bench","password":"secret"})");
    TEST_ASSERT_TRUE(result.ok);
    TEST_ASSERT_EQUAL_STRING("bench", message.ssid);
    TEST_ASSERT_EQUAL_STRING("secret", message.password);
    TEST_ASSERT_TRUE(parse(R"({"type":"wifi_connect","seq":6,"ssid":"open"})").ok);
    TEST_ASSERT_EQUAL_STRING("", message.password);
    TEST_ASSERT_FALSE(parse(R"({"type":"wifi_connect","seq":7,"ssid":""})").ok);
    TEST_ASSERT_FALSE(
        parse(R"({"type":"wifi_connect","seq":8,"ssid":"123456789012345678901234567890123"})").ok);
    TEST_ASSERT_TRUE(parse(R"({"type":"wifi_disconnect","seq":9})").ok);
    TEST_ASSERT_EQUAL(static_cast<int>(HostMessageType::WifiDisconnect),
                      static_cast<int>(message.type));
}

void test_encode_radio_messages() {
    WifiAp ap = {"bench", {0x24, 0x6f, 0x28, 0xaa, 0xbb, 0xcc}, 6, -52, "wpa2", "bgn", true, "above"};
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"wifi_scan_result\",\"seq\":0,\"aps\":[{\"ssid\":\"bench\",\"bssid\":"
        "\"24:6f:28:aa:bb:cc\",\"channel\":6,\"rssi\":-52,\"auth\":\"wpa2\",\"phy\":\"bgn\","
        "\"wps\":true,\"second\":\"above\"}]}\n",
        encode_wifi_scan_result(&ap, 1).c_str());
    WifiStatus status = {"connected", "bench", "192.168.1.20", -50, 6, nullptr};
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"wifi_status\",\"seq\":0,\"state\":\"connected\",\"ssid\":\"bench\",\"ip\":"
        "\"192.168.1.20\",\"rssi\":-50,\"channel\":6,\"reason\":\"\"}\n",
        encode_wifi_status(status).c_str());
    const uint32_t counts[3] = {4, 0, 12};
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"wifi_channels\",\"seq\":0,\"period_ms\":1300,\"counts\":[4,0,12]}\n",
        encode_wifi_channels(counts, 3, 1300).c_str());
    BleDevice device = {};
    const uint8_t address[6] = {0xc0, 0x01, 0x02, 0x03, 0x04, 0x05};
    std::memcpy(device.address, address, 6);
    std::strcpy(device.name, "Tag");
    device.rssi = -70;
    device.company_id = 0x004c;
    device.age_ms = 1200;
    device.address_type = 1;
    device.connectable = true;
    device.adv_count = 42;
    device.tx_power = -8;
    device.appearance = -1;
    device.services[0] = 0x180f;
    device.service_count = 1;
    device.manufacturer[0] = 0x4c;
    device.manufacturer[1] = 0x00;
    device.manufacturer[2] = 0x10;
    device.manufacturer_length = 3;
    TEST_ASSERT_EQUAL_STRING(
        "{\"type\":\"ble_devices\",\"seq\":0,\"devices\":[{\"address\":\"c0:01:02:03:04:05\","
        "\"name\":\"Tag\",\"rssi\":-70,\"company_id\":76,\"age_ms\":1200,\"address_type\":1,"
        "\"connectable\":true,\"adv_count\":42,\"tx_power\":-8,\"services\":[6159],"
        "\"manufacturer\":\"4c0010\"}]}\n",
        encode_ble_devices(&device, 1).c_str());
}

}  // namespace

void run_bench_protocol_tests() {
    RUN_TEST(test_parse_hello_and_ping);
    RUN_TEST(test_parse_config);
    RUN_TEST(test_parse_config_pin_errors);
    RUN_TEST(test_parse_config_errors);
    RUN_TEST(test_parse_set);
    RUN_TEST(test_parse_bad_lines);
    RUN_TEST(test_encode_hello);
    RUN_TEST(test_encode_state);
    RUN_TEST(test_encode_replies);
    RUN_TEST(test_line_reader);
    RUN_TEST(test_parse_two_gpio_pins);
    RUN_TEST(test_parse_i2c_and_uart_requests);
    RUN_TEST(test_encode_bus_messages);
    RUN_TEST(test_encode_sensor_state);
    RUN_TEST(test_hex);
    RUN_TEST(test_hx711_messages);
    RUN_TEST(test_parse_radio_messages);
    RUN_TEST(test_encode_radio_messages);
    RUN_TEST(test_line_reader_overflow);
}
