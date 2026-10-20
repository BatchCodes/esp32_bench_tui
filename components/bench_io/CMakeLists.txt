# Hardware access of the bench agent: GPIO, ADC and LEDC.
idf_component_register(
    SRCS "src/bench_io.cpp"
    INCLUDE_DIRS "include"
    REQUIRES pin_model bench_protocol
    PRIV_REQUIRES esp_driver_gpio esp_driver_ledc esp_driver_i2c esp_driver_uart esp_adc esp_hw_support esp_timer esp_rom freertos log
)
