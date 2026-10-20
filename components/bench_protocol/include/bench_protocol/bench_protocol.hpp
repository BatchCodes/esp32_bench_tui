#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "pin_model/pin_model.hpp"

// Parser for host messages and encoder for agent messages of the bench wire
// protocol. Refer to docs/protocol.md.
namespace bench_protocol {

constexpr int kProtocolVersion = 6;
// The most bytes in one I2C transfer, UART send or uart_data message.
constexpr size_t kMaxDataBytes = 256;
constexpr size_t kMaxI2cTransfer = 32;
constexpr size_t kMaxSsidLength = 32;
constexpr size_t kMaxPasswordLength = 64;
constexpr size_t kMaxBleNameLength = 31;
constexpr size_t kMaxBleServices = 6;
constexpr size_t kMaxBleManufacturerBytes = 24;
constexpr size_t kMaxLineLength = 6144;
// Every message line starts with this text. Other lines are log output.
constexpr const char* kMessagePrefix = "{\"type\":\"";

enum class HostMessageType {
    Hello,
    Config,
    Set,
    Ping,
    I2cScan,
    I2cRead,
    I2cWrite,
    UartSend,
    Radio,
    WifiConnect,
    WifiDisconnect,
};

struct HostMessage {
    HostMessageType type;
    uint32_t seq;
    // Config: the pins. pin_errors holds a static error text for each pin
    // that has a bad field, or nullptr. Such a pin must not be set up.
    pin_model::Config config;
    const char* pin_errors[pin_model::kMaxPins];
    // Set, I2C and UART requests: the pin id.
    char target_id[pin_model::kMaxIdLength + 1];
    // Set: the value.
    float set_value;
    // I2C requests: the 7-bit address, the register (-1 for none) and the
    // number of bytes to read.
    int i2c_address;
    int i2c_register;
    size_t read_length;
    // I2C write and UART send: the bytes.
    uint8_t data[kMaxDataBytes];
    size_t data_length;
    // Radio: the Wi-Fi scan period (0 is off), the channel sniffer and the
    // BLE scan.
    uint32_t wifi_scan_ms;
    bool sniffer;
    bool ble_scan;
    // Active BLE scan: scan requests, so devices send their scan response,
    // which often holds the name.
    bool ble_active;
    // Wi-Fi connect.
    char ssid[kMaxSsidLength + 1];
    char password[kMaxPasswordLength + 1];
};

struct ParseResult {
    bool ok;
    // The seq of the message, or 0 if the parser could not read it.
    uint32_t seq;
    std::string error;
};

ParseResult parse_host_message(const char* line, size_t length, HostMessage* message);

struct AgentInfo {
    const char* agent_version;
    const char* chip;
    int revision;
    int cores;
    const char* mac;
    int flash_mb;
    uint32_t free_heap;
};

struct PinError {
    const char* id;
    std::string error;
};

struct PinValue {
    const char* id;
    pin_model::Mode mode;
    float value;
    // dht11 and dht22: relative humidity in %. hx711: the raw value of the
    // second channel.
    float extra;
    // digital_in: level changes.
    uint32_t edges;
    // hx711: whether each channel answered within the timeout, its timeout
    // count, the number of reads, and whether a second channel exists.
    bool ready[2] = {};
    uint32_t timeouts[2] = {};
    uint32_t reads = 0;
    bool has_second = false;
};

std::string encode_hello(uint32_t seq, const AgentInfo& info);
std::string encode_config_ack(uint32_t seq, const PinError* errors, size_t error_count);
std::string encode_state(uint32_t uptime_ms, const PinValue* values, size_t value_count);
std::string encode_ack(uint32_t seq);
std::string encode_error(uint32_t seq, const std::string& error);
std::string encode_pong(uint32_t seq, uint32_t uptime_ms, uint32_t free_heap);
std::string encode_event(const char* event);
std::string encode_i2c_scan_result(uint32_t seq, const char* id, const uint8_t* addresses,
                                   size_t count);
std::string encode_i2c_data(uint32_t seq, const char* id, int address, int reg,
                            const uint8_t* data, size_t length);
std::string encode_uart_data(const char* id, const uint8_t* data, size_t length);

struct WifiAp {
    char ssid[kMaxSsidLength + 1];
    uint8_t bssid[6];
    int channel;
    int rssi;
    const char* auth;
    // The 802.11 modes, for example "bgn".
    char phy[8];
    bool wps;
    // The second channel of a 40 MHz access point: "above", "below" or "none".
    const char* second;
};

struct WifiStatus {
    // off, idle, connecting, connected or failed.
    const char* state;
    const char* ssid;
    const char* ip;
    int rssi;
    int channel;
    const char* reason;
};

struct BleDevice {
    uint8_t address[6];
    char name[kMaxBleNameLength + 1];
    int rssi;
    // The Bluetooth SIG company ID from the manufacturer data, or -1.
    int company_id;
    uint32_t age_ms;
    // 0 public, 1 random, 2 public identity, 3 random identity.
    int address_type;
    bool connectable;
    uint32_t adv_count;
    // TX power in dBm, or 127 if the device does not send it.
    int tx_power;
    // The GAP appearance value, or -1.
    int appearance;
    uint16_t services[kMaxBleServices];
    size_t service_count;
    uint8_t manufacturer[kMaxBleManufacturerBytes];
    size_t manufacturer_length;
};

std::string encode_wifi_scan_result(const WifiAp* aps, size_t count);
std::string encode_wifi_status(const WifiStatus& status);
std::string encode_wifi_channels(const uint32_t* counts, size_t channel_count, uint32_t period_ms);
std::string encode_ble_devices(const BleDevice* devices, size_t count);

// Address text, for example 24:6f:28:aa:bb:cc.
std::string format_mac(const uint8_t* address);

// Hex text, two lower-case digits for each byte.
std::string to_hex(const uint8_t* data, size_t length);
// Returns false if text is not an even number of hex digits or is too long.
bool from_hex(const char* text, uint8_t* data, size_t capacity, size_t* length);

// Splits a byte stream into lines. Drops a line that is longer than
// kMaxLineLength, and overflowed() reports it one time.
class LineReader {
public:
    // Adds one byte. Returns true when a complete, non-empty line is ready in
    // line(). The line stays valid until the next call of push.
    bool push(char byte);

    const char* line() const { return buffer_; }
    size_t length() const { return length_; }

    bool overflowed();

private:
    char buffer_[kMaxLineLength + 1] = {};
    size_t length_ = 0;
    bool complete_ = false;
    bool discarding_ = false;
    bool overflowed_ = false;
};

}  // namespace bench_protocol
