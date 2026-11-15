# Main component. The REQUIRES list must name every IDF component whose
# headers we include - unlike Arduino-as-component there is no catch-all
# dependency that silently pulls everything in.
idf_component_register(
    SRCS
        "main.cpp"
        "bridge.cpp"
        "config.cpp"
        "web.cpp"
        "telemetry.cpp"
        "crashlog.cpp"
        "conlog.cpp"
        "cpustat.cpp"
        "w5500_mac.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_eth              # Ethernet MAC/PHY
        esp_wifi             # Wi-Fi incl. esp_wifi_internal_*
        esp_netif            # management netif, esp_netif_receive
        esp_event
        esp_timer            # millis() in compat.h
        nvs_flash            # configuration storage
        bootloader_support   # temporary hardware entropy for setup secret
        esp_http_server      # portal and status API
        mqtt                 # telemetry
        mbedtls              # provisioning HTTP Basic credential encoding
        app_update           # OTA (esp_ota_*)
        driver               # GPIO
        esp_hw_support
        lwip                 # static telemetry IP stack
        espcoredump          # crash history (crashlog.cpp), /api/coredump
        spi_flash            # esp_flash_read - coredump fingerprint
)
