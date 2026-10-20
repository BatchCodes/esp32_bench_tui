# Pure C++ component. It must not depend on ESP-IDF, so the host tests can build it.
idf_component_register(
    SRCS "src/pin_model.cpp"
    INCLUDE_DIRS "include"
)
