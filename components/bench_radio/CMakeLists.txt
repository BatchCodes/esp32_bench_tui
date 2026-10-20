# Wi-Fi and Bluetooth Low Energy features of the bench agent: scan, connect,
# channel sniffer and BLE scan. They start only when the host asks for them.
idf_component_register(
    SRCS "src/bench_radio.cpp"
    INCLUDE_DIRS "include"
    REQUIRES bench_protocol
    PRIV_REQUIRES esp_wifi esp_netif esp_event nvs_flash bt log freertos
)
