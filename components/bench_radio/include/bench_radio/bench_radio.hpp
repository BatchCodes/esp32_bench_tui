#pragma once

#include <cstdint>
#include <string>

#include "esp_err.h"

// The Wi-Fi and Bluetooth Low Energy features of the bench agent. The radio
// drivers start only when the host turns a feature on. Driver callbacks store
// their data, and service() sends the messages from the main loop.
namespace bench_radio {

using Emit = void (*)(const std::string& line);

// Stores the function that sends a message line. Starts no driver.
esp_err_t init(Emit emit);

// Turns the features on or off. Returns nullptr, or an error text.
// ble_active sends scan requests, so the devices send their scan response.
const char* configure(uint32_t wifi_scan_ms, bool sniffer, bool ble_scan, bool ble_active);

// Turns every feature off, for example after a new pin configuration. The
// station stays connected.
void stop_scans();

const char* connect(const char* ssid, const char* password);
const char* disconnect();

// Sends the messages that are due. Call it from the main loop.
void service(uint32_t now_ms);

}  // namespace bench_radio
