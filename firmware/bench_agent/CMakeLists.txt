cmake_minimum_required(VERSION 3.22)

set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../components")
set(PROJECT_VER "0.1.0")

# Optional local settings that git ignores. Copy sdkconfig.local.example to
# sdkconfig.local. CI and explicit -D SDKCONFIG_DEFAULTS builds do not use it.
if(NOT DEFINED SDKCONFIG_DEFAULTS AND EXISTS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.local")
    set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.local")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
idf_build_set_property(MINIMAL_BUILD ON)
project(bench_agent)
