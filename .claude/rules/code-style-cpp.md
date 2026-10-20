---
paths:
  - "**/*.cpp"
  - "**/*.hpp"
  - "**/*.h"
  - "**/*.c"
  - "**/CMakeLists.txt"
  - "**/Kconfig*"
---

# C++ and ESP-IDF Rules

The bench agent firmware is C++ on ESP-IDF, at the version in `scripts/esp_idf_version.txt`.

- Format C++ with `clang-format` and the project file `.clang-format`.
- The project has no licence yet. Do not add SPDX header lines until the licence is chosen. When it is chosen, start each source file with `// SPDX-License-Identifier: <licence>`, and use `#` in `CMakeLists.txt` and `Kconfig` files.
- Naming: PascalCase for types, snake_case for functions and variables, `kPascalCase` for constants, a trailing underscore for private members (`config_`), and one namespace per component that matches the component name.
- Keep `bench_protocol` and `pin_model` free of ESP-IDF headers. The host tests in `tests/host/` build them on the ESP-IDF `linux` target. Put hardware access in separate components, such as `bench_gpio` and `bench_transport`.
- Add a host test in `tests/host/main/` for each change to a pure component. Run `./scripts/run_host_tests.sh` before you commit.
- Build the bench agent for each target that a change touches. The build must have no warnings from this repo's code. ESP-IDF builds with `-Werror`.
- The firmware must not hard-code board pins. The host sends the pin list at run time. Check each pin against the chip's limits in the firmware too, so a bad message cannot damage the board.
- Put timing values in Kconfig options with documented defaults. Do not hard-code them.
- Return `esp_err_t` from functions that can fail on hardware, and use `ESP_RETURN_ON_ERROR` with a log message. Do not use exceptions. The app builds with C++ exceptions and RTTI turned off.
- Value-initialise ESP-IDF configuration structs (`gpio_config_t config = {};`) and set the fields one by one. Designated initialisers fail with `-Wmissing-field-initializers` when a struct has more fields than you set.
- Every change to the wire protocol must update `docs/protocol.md`, the host link in `host/bench/link.py` and the protocol version number in the same change.
- Write a comment only for a reason or a fact that the code cannot show, for example a datasheet value or a chip quirk. Name the source of a register map or a magic value.
