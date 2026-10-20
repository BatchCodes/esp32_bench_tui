idf_component_register(
    SRCS "test_main.cpp" "test_pin_model.cpp" "test_bench_protocol.cpp"
    PRIV_REQUIRES unity pin_model bench_protocol
    WHOLE_ARCHIVE
)
