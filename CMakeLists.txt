# Project CMakeLists for the pure ESP-IDF build.
# Expected by PlatformIO with framework = espidf.
cmake_minimum_required(VERSION 3.16)
# Pure ESP-IDF does not reliably infer Kconfig flash size from PlatformIO's
# image-header override. Seed the matching WT32 choice before configuration.
if(SDKCONFIG MATCHES "sdkconfig\\.wt32-eth01-4mb$")
    set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.defaults.wt32-4mb")
elseif(SDKCONFIG MATCHES "sdkconfig\\.wt32-eth01$")
    set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.defaults.wt32-8mb")
endif()
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32_wifi_bridge)
