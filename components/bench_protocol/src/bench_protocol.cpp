#include "bench_protocol/bench_protocol.hpp"

#include <cmath>
#include <cstdlib>
#include <cstring>

#include "cJSON.h"

namespace bench_protocol {

namespace {

using pin_model::Mode;

class Json {
public:
    explicit Json(cJSON* root) : root_(root) {}
    ~Json() { cJSON_Delete(root_); }
    Json(const Json&) = delete;
    Json& operator=(const Json&) = delete;

    cJSON* get() const { return root_; }

private:
    cJSON* root_;
};

cJSON* new_message(const char* type, uint32_t seq) {
    cJSON* root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", type);
    cJSON_AddNumberToObject(root, "seq", seq);
    return root;
}

std::string print(cJSON* root) {
    Json owner(root);
    char* text = cJSON_PrintUnformatted(root);
    if (text == nullptr) {
        return {};
    }
    std::string line(text);
    cJSON_free(text);
    line += '\n';
    return line;
}

// cJSON prints a float that went through double with all its digits, for
// example 0.1f as 0.100000001490116. Rounding in double keeps the output short.
double rounded(float value, int decimals) {
    const double scale = std::pow(10.0, decimals);
    return std::round(static_cast<double>(value) * scale) / scale;
}

bool read_uint(const cJSON* object, const char* key, uint32_t* value) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(object, key);
    if (item == nullptr) {
        return true;
    }
    if (!cJSON_IsNumber(item) || item->valuedouble < 0 || item->valuedouble > 4294967295.0) {
        return false;
    }
    *value = static_cast<uint32_t>(item->valuedouble);
    return true;
}

bool read_float(const cJSON* object, const char* key, float* value) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(object, key);
    if (item == nullptr) {
        return true;
    }
    if (!cJSON_IsNumber(item)) {
        return false;
    }
    *value = static_cast<float>(item->valuedouble);
    return true;
}

bool copy_id(const cJSON* item, char* id) {
    if (!cJSON_IsString(item)) {
        return false;
    }
    const size_t length = std::strlen(item->valuestring);
    if (length == 0 || length > pin_model::kMaxIdLength) {
        return false;
    }
    std::memcpy(id, item->valuestring, length + 1);
    return true;
}

// Returns nullptr, or a static error text for the pin.
const char* parse_pin(const cJSON* item, pin_model::PinConfig* pin) {
    std::memset(pin, 0, sizeof(*pin));
    pin->gpio = -1;
    if (!cJSON_IsObject(item)) {
        return "pin is not an object";
    }
    if (!copy_id(cJSON_GetObjectItemCaseSensitive(item, "id"), pin->id)) {
        return "id must be a string of 1 to 23 characters";
    }
    const cJSON* mode = cJSON_GetObjectItemCaseSensitive(item, "mode");
    if (!cJSON_IsString(mode) || !pin_model::parse_mode(mode->valuestring, &pin->mode)) {
        return "mode is not known";
    }
    if (!pin_model::uses_two_gpios(pin->mode)) {
        const cJSON* gpio = cJSON_GetObjectItemCaseSensitive(item, "gpio");
        if (!cJSON_IsNumber(gpio)) {
            return "gpio is missing";
        }
        pin->gpio = gpio->valueint;
    }
    pin->gpio2 = -1;
    pin->gpio3 = -1;
    if (pin_model::uses_two_gpios(pin->mode)) {
        struct Keys {
            Mode mode;
            const char* first;
            const char* second;
            const char* error;
        };
        constexpr Keys kKeys[] = {
            {Mode::I2c, "sda", "scl", "sda and scl are required"},
            {Mode::Uart, "tx", "rx", "tx and rx are required"},
            {Mode::Hx711, "clock", "data", "clock and data are required"},
        };
        const Keys* keys = &kKeys[0];
        for (const auto& entry : kKeys) {
            if (entry.mode == pin->mode) {
                keys = &entry;
            }
        }
        const cJSON* first = cJSON_GetObjectItemCaseSensitive(item, keys->first);
        const cJSON* second = cJSON_GetObjectItemCaseSensitive(item, keys->second);
        if (!cJSON_IsNumber(first) || !cJSON_IsNumber(second)) {
            return keys->error;
        }
        pin->gpio = first->valueint;
        pin->gpio2 = second->valueint;
        const cJSON* third = cJSON_GetObjectItemCaseSensitive(item, "data2");
        if (pin->mode == Mode::Hx711 && third != nullptr) {
            if (!cJSON_IsNumber(third)) {
                return "data2 must be a GPIO number";
            }
            pin->gpio3 = third->valueint;
        }
    }
    pin_model::apply_defaults(pin);

    const cJSON* pull = cJSON_GetObjectItemCaseSensitive(item, "pull");
    if (pull != nullptr &&
        (!cJSON_IsString(pull) || !pin_model::parse_pull(pull->valuestring, &pin->pull))) {
        return "pull must be none, up or down";
    }
    const cJSON* invert = cJSON_GetObjectItemCaseSensitive(item, "invert");
    if (invert != nullptr) {
        if (!cJSON_IsBool(invert)) {
            return "invert must be true or false";
        }
        pin->invert = cJSON_IsTrue(invert);
    }
    if (!read_float(item, "initial", &pin->initial)) {
        return "initial must be a number";
    }
    if ((pin->mode == Mode::Pwm || pin->mode == Mode::I2c) &&
        !read_uint(item, "freq_hz", &pin->freq_hz)) {
        return "freq_hz must be a positive integer";
    }
    if (pin->mode == Mode::Uart && !read_uint(item, "baud", &pin->baud)) {
        return "baud must be a positive integer";
    }
    uint32_t gain = pin->gain;
    if (pin->mode == Mode::Hx711 && (!read_uint(item, "gain", &gain) || gain > 255)) {
        return "gain must be 128, 64 or 32";
    }
    pin->gain = static_cast<uint8_t>(gain);
    uint32_t min_us = pin->min_us;
    uint32_t max_us = pin->max_us;
    if (!read_uint(item, "min_us", &min_us) || !read_uint(item, "max_us", &max_us) ||
        min_us > 65535 || max_us > 65535) {
        return "min_us and max_us must be positive integers";
    }
    pin->min_us = static_cast<uint16_t>(min_us);
    pin->max_us = static_cast<uint16_t>(max_us);
    return pin_model::validate_pin(*pin);
}

ParseResult fail(uint32_t seq, const char* error) {
    return ParseResult{false, seq, error};
}

ParseResult parse_config(const cJSON* root, HostMessage* message) {
    pin_model::Config& config = message->config;
    config.report_period_ms = pin_model::kDefaultReportPeriodMs;
    config.pin_count = 0;
    if (!read_uint(root, "report_period_ms", &config.report_period_ms)) {
        return fail(message->seq, "report_period_ms must be a positive integer");
    }
    const cJSON* pins = cJSON_GetObjectItemCaseSensitive(root, "pins");
    if (!cJSON_IsArray(pins)) {
        return fail(message->seq, "pins must be an array");
    }
    if (static_cast<size_t>(cJSON_GetArraySize(pins)) > pin_model::kMaxPins) {
        return fail(message->seq, "too many pins, the limit is 48");
    }
    const cJSON* item = nullptr;
    cJSON_ArrayForEach(item, pins) {
        const size_t index = config.pin_count++;
        message->pin_errors[index] = parse_pin(item, &config.pins[index]);
    }
    const char* error = pin_model::validate_config(config);
    if (error != nullptr) {
        return fail(message->seq, error);
    }
    return ParseResult{true, message->seq, {}};
}

bool read_target(const cJSON* root, HostMessage* message) {
    return copy_id(cJSON_GetObjectItemCaseSensitive(root, "id"), message->target_id);
}

ParseResult parse_set(const cJSON* root, HostMessage* message) {
    if (!read_target(root, message)) {
        return fail(message->seq, "id must be a string of 1 to 23 characters");
    }
    const cJSON* value = cJSON_GetObjectItemCaseSensitive(root, "value");
    if (!cJSON_IsNumber(value)) {
        return fail(message->seq, "value must be a number");
    }
    message->set_value = static_cast<float>(value->valuedouble);
    return ParseResult{true, message->seq, {}};
}

ParseResult parse_i2c(const cJSON* root, HostMessage* message) {
    if (!read_target(root, message)) {
        return fail(message->seq, "id must be a string of 1 to 23 characters");
    }
    message->i2c_address = -1;
    message->i2c_register = -1;
    message->read_length = 0;
    message->data_length = 0;
    if (message->type == HostMessageType::I2cScan) {
        return ParseResult{true, message->seq, {}};
    }
    const cJSON* address = cJSON_GetObjectItemCaseSensitive(root, "address");
    if (!cJSON_IsNumber(address) || address->valueint < 0x08 || address->valueint > 0x77) {
        return fail(message->seq, "address must be 0x08 to 0x77");
    }
    message->i2c_address = address->valueint;
    const cJSON* reg = cJSON_GetObjectItemCaseSensitive(root, "register");
    if (reg != nullptr) {
        if (!cJSON_IsNumber(reg) || reg->valueint < 0 || reg->valueint > 0xFF) {
            return fail(message->seq, "register must be 0 to 255");
        }
        message->i2c_register = reg->valueint;
    }
    if (message->type == HostMessageType::I2cRead) {
        uint32_t length = 1;
        if (!read_uint(root, "length", &length) || length < 1 || length > kMaxI2cTransfer) {
            return fail(message->seq, "length must be 1 to 32");
        }
        message->read_length = length;
        return ParseResult{true, message->seq, {}};
    }
    const cJSON* data = cJSON_GetObjectItemCaseSensitive(root, "data");
    if (!cJSON_IsString(data) ||
        !from_hex(data->valuestring, message->data, kMaxI2cTransfer, &message->data_length)) {
        return fail(message->seq, "data must be hex text of at most 32 bytes");
    }
    return ParseResult{true, message->seq, {}};
}

bool read_bool(const cJSON* object, const char* key, bool* value) {
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(object, key);
    if (item == nullptr) {
        return true;
    }
    if (!cJSON_IsBool(item)) {
        return false;
    }
    *value = cJSON_IsTrue(item);
    return true;
}

bool copy_text(const cJSON* item, char* text, size_t max_length, bool allow_empty) {
    if (!cJSON_IsString(item)) {
        return false;
    }
    const size_t length = std::strlen(item->valuestring);
    if (length > max_length || (length == 0 && !allow_empty)) {
        return false;
    }
    std::memcpy(text, item->valuestring, length + 1);
    return true;
}

ParseResult parse_radio(const cJSON* root, HostMessage* message) {
    message->wifi_scan_ms = 0;
    message->sniffer = false;
    message->ble_scan = false;
    message->ble_active = false;
    if (!read_uint(root, "wifi_scan_ms", &message->wifi_scan_ms) ||
        (message->wifi_scan_ms != 0 && message->wifi_scan_ms < 2000)) {
        return fail(message->seq, "wifi_scan_ms must be 0 or at least 2000");
    }
    if (!read_bool(root, "sniffer", &message->sniffer) ||
        !read_bool(root, "ble_scan", &message->ble_scan) ||
        !read_bool(root, "ble_active", &message->ble_active)) {
        return fail(message->seq, "sniffer, ble_scan and ble_active must be true or false");
    }
    return ParseResult{true, message->seq, {}};
}

ParseResult parse_wifi_connect(const cJSON* root, HostMessage* message) {
    if (!copy_text(cJSON_GetObjectItemCaseSensitive(root, "ssid"), message->ssid, kMaxSsidLength,
                   false)) {
        return fail(message->seq, "ssid must be 1 to 32 characters");
    }
    message->password[0] = '\0';
    const cJSON* password = cJSON_GetObjectItemCaseSensitive(root, "password");
    if (password != nullptr &&
        !copy_text(password, message->password, kMaxPasswordLength, true)) {
        return fail(message->seq, "password must be at most 64 characters");
    }
    return ParseResult{true, message->seq, {}};
}

ParseResult parse_uart_send(const cJSON* root, HostMessage* message) {
    if (!read_target(root, message)) {
        return fail(message->seq, "id must be a string of 1 to 23 characters");
    }
    const cJSON* data = cJSON_GetObjectItemCaseSensitive(root, "data");
    if (!cJSON_IsString(data) ||
        !from_hex(data->valuestring, message->data, kMaxDataBytes, &message->data_length) ||
        message->data_length == 0) {
        return fail(message->seq, "data must be hex text of 1 to 256 bytes");
    }
    return ParseResult{true, message->seq, {}};
}

void add_value(cJSON* values, const PinValue& pin) {
    switch (pin.mode) {
        case Mode::DigitalIn:
        case Mode::DigitalOut:
        case Mode::Adc:
            cJSON_AddNumberToObject(values, pin.id, std::lround(pin.value));
            break;
        case Mode::Pwm:
            cJSON_AddNumberToObject(values, pin.id, rounded(pin.value, 4));
            break;
        case Mode::Servo:
            cJSON_AddNumberToObject(values, pin.id, rounded(pin.value, 1));
            break;
        case Mode::I2c:
        case Mode::Uart:
            cJSON_AddNumberToObject(values, pin.id, std::lround(pin.value));
            break;
        case Mode::Ds18b20:
        case Mode::Dht11:
        case Mode::Dht22:
            // cJSON writes NaN, a failed read, as null.
            cJSON_AddNumberToObject(values, pin.id, rounded(pin.value, 2));
            break;
        case Mode::Hx711:
            cJSON_AddNumberToObject(values, pin.id, rounded(pin.value, 0));
            break;
    }
}

}  // namespace

ParseResult parse_host_message(const char* line, size_t length, HostMessage* message) {
    message->seq = 0;
    if (length > kMaxLineLength) {
        return fail(0, "line is too long");
    }
    Json root(cJSON_ParseWithLength(line, length));
    if (!cJSON_IsObject(root.get())) {
        return fail(0, "line is not a JSON object");
    }
    if (!read_uint(root.get(), "seq", &message->seq)) {
        return fail(0, "seq must be a positive integer");
    }
    const cJSON* type = cJSON_GetObjectItemCaseSensitive(root.get(), "type");
    if (!cJSON_IsString(type)) {
        return fail(message->seq, "type is missing");
    }
    if (std::strcmp(type->valuestring, "hello") == 0) {
        message->type = HostMessageType::Hello;
        return ParseResult{true, message->seq, {}};
    }
    if (std::strcmp(type->valuestring, "ping") == 0) {
        message->type = HostMessageType::Ping;
        return ParseResult{true, message->seq, {}};
    }
    if (std::strcmp(type->valuestring, "config") == 0) {
        message->type = HostMessageType::Config;
        return parse_config(root.get(), message);
    }
    if (std::strcmp(type->valuestring, "set") == 0) {
        message->type = HostMessageType::Set;
        return parse_set(root.get(), message);
    }
    struct I2cType {
        const char* name;
        HostMessageType type;
    };
    constexpr I2cType kI2cTypes[] = {{"i2c_scan", HostMessageType::I2cScan},
                                     {"i2c_read", HostMessageType::I2cRead},
                                     {"i2c_write", HostMessageType::I2cWrite}};
    for (const auto& entry : kI2cTypes) {
        if (std::strcmp(type->valuestring, entry.name) == 0) {
            message->type = entry.type;
            return parse_i2c(root.get(), message);
        }
    }
    if (std::strcmp(type->valuestring, "uart_send") == 0) {
        message->type = HostMessageType::UartSend;
        return parse_uart_send(root.get(), message);
    }
    if (std::strcmp(type->valuestring, "radio") == 0) {
        message->type = HostMessageType::Radio;
        return parse_radio(root.get(), message);
    }
    if (std::strcmp(type->valuestring, "wifi_connect") == 0) {
        message->type = HostMessageType::WifiConnect;
        return parse_wifi_connect(root.get(), message);
    }
    if (std::strcmp(type->valuestring, "wifi_disconnect") == 0) {
        message->type = HostMessageType::WifiDisconnect;
        return ParseResult{true, message->seq, {}};
    }
    return fail(message->seq, "unknown message type");
}

std::string encode_hello(uint32_t seq, const AgentInfo& info) {
    cJSON* root = new_message("hello", seq);
    cJSON_AddNumberToObject(root, "protocol", kProtocolVersion);
    cJSON_AddStringToObject(root, "agent", info.agent_version);
    cJSON_AddStringToObject(root, "chip", info.chip);
    cJSON_AddNumberToObject(root, "revision", info.revision);
    cJSON_AddNumberToObject(root, "cores", info.cores);
    cJSON_AddStringToObject(root, "mac", info.mac);
    cJSON_AddNumberToObject(root, "flash_mb", info.flash_mb);
    cJSON_AddNumberToObject(root, "free_heap", info.free_heap);
    return print(root);
}

std::string encode_config_ack(uint32_t seq, const PinError* errors, size_t error_count) {
    cJSON* root = new_message("config_ack", seq);
    cJSON_AddBoolToObject(root, "ok", error_count == 0);
    cJSON* list = cJSON_AddArrayToObject(root, "errors");
    for (size_t index = 0; index < error_count; ++index) {
        cJSON* entry = cJSON_CreateObject();
        cJSON_AddStringToObject(entry, "id", errors[index].id);
        cJSON_AddStringToObject(entry, "error", errors[index].error.c_str());
        cJSON_AddItemToArray(list, entry);
    }
    return print(root);
}

std::string encode_state(uint32_t uptime_ms, const PinValue* values, size_t value_count) {
    cJSON* root = new_message("state", 0);
    cJSON_AddNumberToObject(root, "uptime_ms", uptime_ms);
    cJSON* value_object = cJSON_AddObjectToObject(root, "values");
    cJSON* edge_object = cJSON_AddObjectToObject(root, "edges");
    cJSON* humidity_object = nullptr;
    cJSON* hx711_object = nullptr;
    for (size_t index = 0; index < value_count; ++index) {
        const PinValue& value = values[index];
        add_value(value_object, value);
        if (value.mode == Mode::DigitalIn) {
            cJSON_AddNumberToObject(edge_object, value.id, value.edges);
        }
        if (value.mode == Mode::Dht11 || value.mode == Mode::Dht22) {
            if (humidity_object == nullptr) {
                humidity_object = cJSON_AddObjectToObject(root, "humidity");
            }
            cJSON_AddNumberToObject(humidity_object, value.id, rounded(value.extra, 1));
        }
        if (value.mode == Mode::Hx711) {
            if (hx711_object == nullptr) {
                hx711_object = cJSON_AddObjectToObject(root, "hx711");
            }
            cJSON* entry = cJSON_AddObjectToObject(hx711_object, value.id);
            const int channels = value.has_second ? 2 : 1;
            if (value.has_second) {
                cJSON_AddNumberToObject(entry, "raw2", rounded(value.extra, 0));
            }
            cJSON* ready = cJSON_AddArrayToObject(entry, "ready");
            cJSON* timeouts = cJSON_AddArrayToObject(entry, "timeouts");
            for (int channel = 0; channel < channels; ++channel) {
                cJSON_AddItemToArray(ready, cJSON_CreateBool(value.ready[channel]));
                cJSON_AddItemToArray(timeouts, cJSON_CreateNumber(value.timeouts[channel]));
            }
            cJSON_AddNumberToObject(entry, "reads", value.reads);
        }
    }
    return print(root);
}

std::string encode_ack(uint32_t seq) {
    return print(new_message("ack", seq));
}

std::string encode_error(uint32_t seq, const std::string& error) {
    cJSON* root = new_message("error", seq);
    cJSON_AddStringToObject(root, "error", error.c_str());
    return print(root);
}

std::string encode_pong(uint32_t seq, uint32_t uptime_ms, uint32_t free_heap) {
    cJSON* root = new_message("pong", seq);
    cJSON_AddNumberToObject(root, "uptime_ms", uptime_ms);
    cJSON_AddNumberToObject(root, "free_heap", free_heap);
    return print(root);
}

std::string encode_event(const char* event) {
    cJSON* root = new_message("event", 0);
    cJSON_AddStringToObject(root, "event", event);
    return print(root);
}

std::string encode_i2c_scan_result(uint32_t seq, const char* id, const uint8_t* addresses,
                                   size_t count) {
    cJSON* root = new_message("i2c_scan_result", seq);
    cJSON_AddStringToObject(root, "id", id);
    cJSON* list = cJSON_AddArrayToObject(root, "addresses");
    for (size_t index = 0; index < count; ++index) {
        cJSON_AddItemToArray(list, cJSON_CreateNumber(addresses[index]));
    }
    return print(root);
}

std::string encode_i2c_data(uint32_t seq, const char* id, int address, int reg,
                            const uint8_t* data, size_t length) {
    cJSON* root = new_message("i2c_data", seq);
    cJSON_AddStringToObject(root, "id", id);
    cJSON_AddNumberToObject(root, "address", address);
    if (reg >= 0) {
        cJSON_AddNumberToObject(root, "register", reg);
    }
    cJSON_AddStringToObject(root, "data", to_hex(data, length).c_str());
    return print(root);
}

std::string encode_uart_data(const char* id, const uint8_t* data, size_t length) {
    cJSON* root = new_message("uart_data", 0);
    cJSON_AddStringToObject(root, "id", id);
    cJSON_AddStringToObject(root, "data", to_hex(data, length).c_str());
    return print(root);
}

std::string encode_wifi_scan_result(const WifiAp* aps, size_t count) {
    cJSON* root = new_message("wifi_scan_result", 0);
    cJSON* list = cJSON_AddArrayToObject(root, "aps");
    for (size_t index = 0; index < count; ++index) {
        const WifiAp& ap = aps[index];
        cJSON* entry = cJSON_CreateObject();
        cJSON_AddStringToObject(entry, "ssid", ap.ssid);
        cJSON_AddStringToObject(entry, "bssid", format_mac(ap.bssid).c_str());
        cJSON_AddNumberToObject(entry, "channel", ap.channel);
        cJSON_AddNumberToObject(entry, "rssi", ap.rssi);
        cJSON_AddStringToObject(entry, "auth", ap.auth);
        cJSON_AddStringToObject(entry, "phy", ap.phy);
        cJSON_AddBoolToObject(entry, "wps", ap.wps);
        cJSON_AddStringToObject(entry, "second", ap.second != nullptr ? ap.second : "none");
        cJSON_AddItemToArray(list, entry);
    }
    return print(root);
}

std::string encode_wifi_status(const WifiStatus& status) {
    cJSON* root = new_message("wifi_status", 0);
    cJSON_AddStringToObject(root, "state", status.state);
    cJSON_AddStringToObject(root, "ssid", status.ssid != nullptr ? status.ssid : "");
    cJSON_AddStringToObject(root, "ip", status.ip != nullptr ? status.ip : "");
    cJSON_AddNumberToObject(root, "rssi", status.rssi);
    cJSON_AddNumberToObject(root, "channel", status.channel);
    cJSON_AddStringToObject(root, "reason", status.reason != nullptr ? status.reason : "");
    return print(root);
}

std::string encode_wifi_channels(const uint32_t* counts, size_t channel_count, uint32_t period_ms) {
    cJSON* root = new_message("wifi_channels", 0);
    cJSON_AddNumberToObject(root, "period_ms", period_ms);
    cJSON* list = cJSON_AddArrayToObject(root, "counts");
    for (size_t index = 0; index < channel_count; ++index) {
        cJSON_AddItemToArray(list, cJSON_CreateNumber(counts[index]));
    }
    return print(root);
}

std::string encode_ble_devices(const BleDevice* devices, size_t count) {
    cJSON* root = new_message("ble_devices", 0);
    cJSON* list = cJSON_AddArrayToObject(root, "devices");
    for (size_t index = 0; index < count; ++index) {
        const BleDevice& device = devices[index];
        cJSON* entry = cJSON_CreateObject();
        cJSON_AddStringToObject(entry, "address", format_mac(device.address).c_str());
        cJSON_AddStringToObject(entry, "name", device.name);
        cJSON_AddNumberToObject(entry, "rssi", device.rssi);
        cJSON_AddNumberToObject(entry, "company_id", device.company_id);
        cJSON_AddNumberToObject(entry, "age_ms", device.age_ms);
        cJSON_AddNumberToObject(entry, "address_type", device.address_type);
        cJSON_AddBoolToObject(entry, "connectable", device.connectable);
        cJSON_AddNumberToObject(entry, "adv_count", device.adv_count);
        if (device.tx_power != 127) {
            cJSON_AddNumberToObject(entry, "tx_power", device.tx_power);
        }
        if (device.appearance >= 0) {
            cJSON_AddNumberToObject(entry, "appearance", device.appearance);
        }
        cJSON* services = cJSON_AddArrayToObject(entry, "services");
        for (size_t service = 0; service < device.service_count; ++service) {
            cJSON_AddItemToArray(services, cJSON_CreateNumber(device.services[service]));
        }
        cJSON_AddStringToObject(entry, "manufacturer",
                                to_hex(device.manufacturer, device.manufacturer_length).c_str());
        cJSON_AddItemToArray(list, entry);
    }
    return print(root);
}

std::string format_mac(const uint8_t* address) {
    std::string text = to_hex(address, 1);
    for (size_t index = 1; index < 6; ++index) {
        text += ':';
        text += to_hex(address + index, 1);
    }
    return text;
}

std::string to_hex(const uint8_t* data, size_t length) {
    constexpr char kDigits[] = "0123456789abcdef";
    std::string text;
    text.reserve(length * 2);
    for (size_t index = 0; index < length; ++index) {
        text += kDigits[data[index] >> 4];
        text += kDigits[data[index] & 0x0F];
    }
    return text;
}

namespace {

int hex_digit(char digit) {
    if (digit >= '0' && digit <= '9') {
        return digit - '0';
    }
    if (digit >= 'a' && digit <= 'f') {
        return digit - 'a' + 10;
    }
    if (digit >= 'A' && digit <= 'F') {
        return digit - 'A' + 10;
    }
    return -1;
}

}  // namespace

bool from_hex(const char* text, uint8_t* data, size_t capacity, size_t* length) {
    const size_t digits = std::strlen(text);
    if (digits % 2 != 0 || digits / 2 > capacity) {
        return false;
    }
    for (size_t index = 0; index < digits / 2; ++index) {
        const int high = hex_digit(text[2 * index]);
        const int low = hex_digit(text[2 * index + 1]);
        if (high < 0 || low < 0) {
            return false;
        }
        data[index] = static_cast<uint8_t>(high << 4 | low);
    }
    *length = digits / 2;
    return true;
}

bool LineReader::push(char byte) {
    if (complete_) {
        complete_ = false;
        length_ = 0;
    }
    if (byte == '\r') {
        return false;
    }
    if (byte == '\n') {
        if (discarding_) {
            discarding_ = false;
            length_ = 0;
            return false;
        }
        if (length_ == 0) {
            return false;
        }
        buffer_[length_] = '\0';
        complete_ = true;
        return true;
    }
    if (discarding_) {
        return false;
    }
    if (length_ >= kMaxLineLength) {
        discarding_ = true;
        overflowed_ = true;
        length_ = 0;
        return false;
    }
    buffer_[length_++] = byte;
    return false;
}

bool LineReader::overflowed() {
    const bool result = overflowed_;
    overflowed_ = false;
    return result;
}

}  // namespace bench_protocol
