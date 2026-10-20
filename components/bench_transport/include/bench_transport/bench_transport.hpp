#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "esp_err.h"

// The serial link of the bench agent. It uses the port of the ESP-IDF console:
// the console UART, or the USB-Serial-JTAG port when the console is there. The
// log output goes through the same lock as the protocol messages, so a message
// line never mixes with a log line.
namespace bench_transport {

// Installs the driver and sends the ESP-IDF log output through this transport.
esp_err_t init();

// Writes one message line. Writes a newline first if the last log output did
// not end with one.
void write_message(const std::string& line);

// Reads at most size bytes. Waits at most timeout_ms for the first byte.
// Returns the number of bytes read.
size_t read(char* buffer, size_t size, uint32_t timeout_ms);

// The GPIOs that the transport uses. Returns -1 for a pin that is not used.
int tx_gpio();
int rx_gpio();

}  // namespace bench_transport
