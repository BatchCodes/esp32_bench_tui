# The serial link of the bench agent: the console UART or the USB-Serial-JTAG port.
idf_component_register(
    SRCS "src/bench_transport.cpp"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES esp_driver_uart esp_driver_usb_serial_jtag vfs freertos log
)
