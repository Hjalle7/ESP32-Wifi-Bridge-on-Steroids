# WT32 4 MB deployment: first implementation slice

## Build and flash capacity

WT32-ETH01 is the primary target. Use `pio run -e wt32-eth01-4mb` (also the default environment). The original `wt32-eth01` remains an explicit 8 MB reference-board target. The actual purchased board has not been inspected: read its flash ID before initial installation. Do not flash an 8 MB header/partition layout onto a 4 MB device.

The 4 MB layout uses the same addresses as the existing C5 target: 24 KB NVS at 0x9000, 8 KB OTA metadata at 0xF000, two 1920 KB app slots at 0x20000 and 0x200000, and 64 KB coredump at 0x3E0000. The final 64 KB is reserved. Both Kconfig defaults and application/bootloader image headers must say 4 MB. After building, run `python scripts/check_flash_layout.py wt32-eth01-4mb 4` to verify the headers, generated binary partition table and firmware fit. First installation or partition changes require a cable; ordinary OTA updates only replace an app slot. Existing devices migrating from 8 MB need a deliberate cable migration with configuration backup, not an app-only OTA.

## Setup access and recovery

Connect WT32 IO14 to GND for at least three seconds at boot to enter provisioning. During normal operation, hold it low for at least three seconds and release: the main loop requests a planned reboot into setup. A short press does nothing. C5 uses IO4 for the same behavior. Do not use IO0/BOOT. Input timing and the actual board wiring still need device verification.

This gesture never clears saved Wi-Fi, IP or MQTT settings. Factory erase is a separate serial-tool operation for now; there is no new factory-reset portal endpoint in this patch. A full flash erase also removes the device-local AP password and requires obtaining the new one locally.

The setup AP has a 32-character per-device random password, stored independently from BridgeConfig in NVS. Obtain it over local serial before installation. It is printed directly through the ROM console, bypassing the web-visible console ring and MQTT. If generation/persistence fails, the AP is not started with a shared fallback. In provisioning, APSTA mode enables scanning; the STA is not deliberately associated to an upstream network. HTTP is reachable on the setup AP at 192.168.4.1. The existing inactivity return to normal operation remains.

HTTP, including OTA and diagnostics, does not start in normal bridge mode. `web_start(false)` also refuses startup. NetBIOS and SNTP startup have been removed. The static STA IP and existing frame routing remain for outgoing MQTT and reply packets. OTA through `scripts/ota_flash.sh` now defaults to the 4 MB environment and requires entering provisioning first; capture the AP credential and ensure local recovery before updating an installed board.

OTA confirmation requires 30 continuous seconds with active bridge, Wi-Fi association and Ethernet link, independently of MQTT/client traffic. Configured devices stuck in provisioning do not confirm the new image; unconfigured provisioning remains a valid initial-commissioning state. These local checks cannot prove end-to-end connectivity or full datapath health.

## Hardware assumptions

The planned antenna solution is an external connector/antenna modification; RF continuity and link stability need validation on the modified board. Supply the 5 V input from a regulated source. A potential 24 V equipment output must first be identified as AC/DC and checked for voltage tolerance and available current; choose the conversion accordingly. An alternative is an appropriately installed isolated mains-to-5 V supply. No supply or antenna has been physically verified.

## Remaining work

This is not the completed production architecture. Watchdog and profile selection still use gateway ping. MQTT publishing is not yet isolated from main-loop/watchdog calls. Static DNS configuration, stricter validation/transactional persistence, TLS policy, universal provisioning API authentication, maximum provisioning duration and a portal factory-reset action remain open. Existing optional admin-key guards still apply to only some endpoints; the AP secret does not replace per-request authentication. There is no claim of an outbound-only packet filter or verified zero listening ports until socket scans/captures are done.

Before deployment, test DHCP/ARP and bidirectional Modbus, MAC replacement, physical setup without data loss, unique-secret persistence and serial-only visibility, broker outage, cable/Wi-Fi recovery, OTA rollback (including link loss), antenna/power stability and an unattended soak. See [implementation-design.md](implementation-design.md) for the remaining design and acceptance criteria.

## Build verification

The first WT32 4 MB and 8 MB builds both succeeded with the pinned PlatformIO platform and ESP-IDF 5.5.1. The padded firmware image is 968720 bytes: 49.3% of a 1966080-byte slot on 4 MB, or 30.8% of a 3145728-byte slot on 8 MB. The flash checker verified both bootloader and app headers, Kconfig size, generated partition bounds and app fit. Negative checks rejected a deliberately wrong 8 MB image header, an oversized app and an out-of-bounds partition. An existing IRAM attribute warning in unchanged bridge.cpp remains. No device test has been run.

The C5/W5500 regression build also succeeded; its image is 1149776 bytes (58.5% of a 1920 KB slot), and its 4 MB headers/config/partition check passed. These are build checks, not runtime validation on C5 hardware.
