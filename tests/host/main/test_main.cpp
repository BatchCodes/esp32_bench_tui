#include "tests.hpp"
#include "unity.h"

extern "C" void setUp() {}
extern "C" void tearDown() {}

int main() {
    UNITY_BEGIN();
    run_pin_model_tests();
    run_bench_protocol_tests();
    return UNITY_END();
}
