#include <cstdio>
#include <cstring>

#include "bench_io/bench_io.hpp"
#include "bench_protocol/bench_protocol.hpp"
#include "bench_radio/bench_radio.hpp"
#include "bench_transport/bench_transport.hpp"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "pin_model/pin_model.hpp"
#include "sdkconfig.h"

namespace {

constexpr const char* kTag = "bench_agent";
constexpr size_t kReadChunk = 256;

// Large objects live here, not on the main task stack.
bench_protocol::HostMessage message;
bench_protocol::LineReader reader;
bench_io::PinBank bank;
bench_protocol::PinError pin_errors[pin_model::kMaxPins];
bench_protocol::PinValue pin_values[pin_model::kMaxPins];
pin_model::HostWatchdog watchdog(CONFIG_BENCH_HOST_TIMEOUT_MS);
uint32_t report_period_ms = 0;
char mac_text[18] = {};
int flash_mb = 0;

uint32_t now_ms() {
    return static_cast<uint32_t>(esp_timer_get_time() / 1000);
}

void read_chip_facts() {
    uint8_t mac[6] = {};
    esp_read_mac(mac, ESP_MAC_BASE);
    snprintf(mac_text, sizeof(mac_text), "%02x:%02x:%02x:%02x:%02x:%02x", mac[0], mac[1], mac[2],
             mac[3], mac[4], mac[5]);
    uint32_t flash_size = 0;
    if (esp_flash_get_size(nullptr, &flash_size) == ESP_OK) {
        flash_mb = static_cast<int>(flash_size / (1024 * 1024));
    }
}

void send_hello(uint32_t seq) {
    esp_chip_info_t chip = {};
    esp_chip_info(&chip);
    bench_protocol::AgentInfo info = {};
    info.agent_version = esp_app_get_description()->version;
    info.chip = CONFIG_IDF_TARGET;
    info.revision = chip.revision;
    info.cores = chip.cores;
    info.mac = mac_text;
    info.flash_mb = flash_mb;
    info.free_heap = esp_get_free_heap_size();
    bench_transport::write_message(bench_protocol::encode_hello(seq, info));
}

void handle_config() {
    const size_t error_count = bank.apply(message.config, message.pin_errors, pin_errors);
    report_period_ms = message.config.report_period_ms;
    bench_transport::write_message(
        bench_protocol::encode_config_ack(message.seq, pin_errors, error_count));
}

void handle_i2c() {
    const char* error = nullptr;
    std::string reply;
    if (message.type == bench_protocol::HostMessageType::I2cScan) {
        uint8_t addresses[128];
        size_t count = 0;
        error = bank.i2c_scan(message.target_id, addresses, &count);
        if (error == nullptr) {
            reply = bench_protocol::encode_i2c_scan_result(message.seq, message.target_id,
                                                           addresses, count);
        }
    } else if (message.type == bench_protocol::HostMessageType::I2cRead) {
        uint8_t data[bench_protocol::kMaxI2cTransfer];
        error = bank.i2c_read(message.target_id, message.i2c_address, message.i2c_register, data,
                              message.read_length);
        if (error == nullptr) {
            reply = bench_protocol::encode_i2c_data(message.seq, message.target_id,
                                                    message.i2c_address, message.i2c_register,
                                                    data, message.read_length);
        }
    } else {
        error = bank.i2c_write(message.target_id, message.i2c_address, message.i2c_register,
                               message.data, message.data_length);
        if (error == nullptr) {
            reply = bench_protocol::encode_ack(message.seq);
        }
    }
    bench_transport::write_message(
        error == nullptr ? reply : bench_protocol::encode_error(message.seq, error));
}

// Sends ack, or error with the text.
void reply(const char* error) {
    bench_transport::write_message(error == nullptr
                                       ? bench_protocol::encode_ack(message.seq)
                                       : bench_protocol::encode_error(message.seq, error));
}

void emit_uart_data(const char* id, const uint8_t* data, size_t length) {
    bench_transport::write_message(bench_protocol::encode_uart_data(id, data, length));
}

void handle_line(const char* line, size_t length) {
    // Text that is not a message, for example an echo of a terminal, is ignored.
    if (line[0] != '{') {
        return;
    }
    const bench_protocol::ParseResult result =
        bench_protocol::parse_host_message(line, length, &message);
    if (!result.ok) {
        bench_transport::write_message(bench_protocol::encode_error(result.seq, result.error));
        return;
    }
    watchdog.feed(now_ms());
    switch (message.type) {
        case bench_protocol::HostMessageType::Hello:
            send_hello(message.seq);
            break;
        case bench_protocol::HostMessageType::Config:
            handle_config();
            break;
        case bench_protocol::HostMessageType::Set: {
            const char* error = bank.set(message.target_id, message.set_value);
            bench_transport::write_message(error == nullptr
                                               ? bench_protocol::encode_ack(message.seq)
                                               : bench_protocol::encode_error(message.seq, error));
            break;
        }
        case bench_protocol::HostMessageType::I2cScan:
        case bench_protocol::HostMessageType::I2cRead:
        case bench_protocol::HostMessageType::I2cWrite:
            handle_i2c();
            break;
        case bench_protocol::HostMessageType::UartSend: {
            const char* error = bank.uart_send(message.target_id, message.data, message.data_length);
            bench_transport::write_message(error == nullptr
                                               ? bench_protocol::encode_ack(message.seq)
                                               : bench_protocol::encode_error(message.seq, error));
            break;
        }
        case bench_protocol::HostMessageType::Radio:
            reply(bench_radio::configure(message.wifi_scan_ms, message.sniffer, message.ble_scan,
                                        message.ble_active));
            break;
        case bench_protocol::HostMessageType::WifiConnect:
            reply(bench_radio::connect(message.ssid, message.password));
            // The password stays in the Wi-Fi driver only.
            std::memset(message.password, 0, sizeof(message.password));
            break;
        case bench_protocol::HostMessageType::WifiDisconnect:
            reply(bench_radio::disconnect());
            break;
        case bench_protocol::HostMessageType::Ping:
            bench_transport::write_message(
                bench_protocol::encode_pong(message.seq, now_ms(), esp_get_free_heap_size()));
            break;
    }
}

void send_state() {
    const size_t count = bank.read(pin_values);
    if (count == 0) {
        return;
    }
    bench_transport::write_message(bench_protocol::encode_state(now_ms(), pin_values, count));
}

void run() {
    char chunk[kReadChunk];
    uint32_t next_report_ms = now_ms();
    while (true) {
        const size_t count =
            bench_transport::read(chunk, sizeof(chunk), CONFIG_BENCH_READ_POLL_MS);
        for (size_t index = 0; index < count; ++index) {
            if (reader.push(chunk[index])) {
                handle_line(reader.line(), reader.length());
            }
        }
        if (reader.overflowed()) {
            bench_transport::write_message(bench_protocol::encode_error(0, "line is too long"));
        }

        const uint32_t now = now_ms();
        bank.service_sensors(now);
        bench_radio::service(now);
        if (watchdog.check(now)) {
            ESP_LOGW(kTag, "no message from the host, outputs set to their initial values");
            bank.stop_outputs();
            bench_radio::stop_scans();
            bench_transport::write_message(bench_protocol::encode_event("watchdog"));
        }
        if (report_period_ms > 0 && static_cast<int32_t>(now - next_report_ms) >= 0) {
            bank.poll_uarts(emit_uart_data);
            send_state();
            next_report_ms = now + report_period_ms;
        }
    }
}

}  // namespace

extern "C" void app_main() {
    ESP_ERROR_CHECK(bench_transport::init());
    ESP_ERROR_CHECK(bank.init(bench_transport::tx_gpio(), bench_transport::rx_gpio()));
    ESP_ERROR_CHECK(bench_radio::init(bench_transport::write_message));
    read_chip_facts();
    ESP_LOGI(kTag, "bench agent %s on %s, protocol %d", esp_app_get_description()->version,
             CONFIG_IDF_TARGET, bench_protocol::kProtocolVersion);
    send_hello(0);
    run();
}
