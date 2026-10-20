# Pure C++ component. It must not depend on ESP-IDF, so the host tests can build it.
# cJSON comes from the IDF Component Manager (idf_component.yml).
idf_component_register(
    SRCS "src/bench_protocol.cpp"
    INCLUDE_DIRS "include"
    REQUIRES pin_model
)
