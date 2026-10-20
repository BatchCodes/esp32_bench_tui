idf_component_register(
    SRCS "main.cpp"
    PRIV_REQUIRES bench_protocol bench_transport bench_io bench_radio pin_model esp_app_format esp_timer
                  esp_hw_support spi_flash log freertos
)
