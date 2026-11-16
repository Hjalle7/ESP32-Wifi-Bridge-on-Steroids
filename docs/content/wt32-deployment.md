# WT32 4 MB deployment: first implementation slice

## Build and flash capacity

WT32-ETH01/4 MB is the only supported target. Use `pio run -e wt32-eth01-4mb` (also the default environment). The retained `wt32-eth01` (8 MB) and `nicemcu-c5-w5500` environments are unsupported legacy configurations; do not build, test or flash them for this project. The actual purchased board has not been inspected: read its flash ID before initial installation. Do not flash an 8 MB header/partition layout onto a 4 MB device.

The 4 MB layout contains: 24 KB NVS at 0x9000, 8 KB OTA metadata at 0xF000, two 1920 KB app slots at 0x20000 and 0x200000, and 64 KB coredump at 0x3E0000. The final 64 KB is reserved. Both Kconfig defaults and application/bootloader image headers must say 4 MB. After building, run `python scripts/check_flash_layout.py wt32-eth01-4mb 4` to verify the headers, generated binary partition table and firmware fit. First installation or partition changes require a cable; ordinary OTA updates only replace an app slot. Existing devices migrating from 8 MB need a deliberate cable migration with configuration backup, not an app-only OTA.

## Setup access and recovery

Connect WT32 IO14 to GND for at least three seconds at boot to enter provisioning. During normal operation, hold it low for at least three seconds and release: the main loop requests a planned reboot into setup. A short press does nothing. Do not use IO0/BOOT. Input timing and the actual board wiring still need device verification.

This gesture never clears saved Wi-Fi, IP or MQTT settings. Factory erase is a separate serial-tool operation for now; there is no new factory-reset portal endpoint in this patch. A full flash erase also removes the device-local AP password and requires obtaining the new one locally.

The setup AP has a 32-character per-device random password, stored independently from BridgeConfig in NVS. Obtain it over local serial before installation. It is printed directly through the ROM console, bypassing the web-visible console ring and MQTT. If generation/persistence fails, the AP is not started with a shared fallback. In provisioning, APSTA mode enables scanning; the STA is not deliberately associated to an upstream network. HTTP is reachable on the setup AP at 192.168.4.1. The existing inactivity return to normal operation remains.

HTTP, including OTA and diagnostics, does not start in normal bridge mode. `web_start(false)` also refuses startup. NetBIOS and SNTP startup have been removed. The static STA IP and existing frame routing remain for outgoing MQTT and reply packets. OTA through `scripts/ota_flash.sh` now defaults to the 4 MB environment and requires entering provisioning first; capture the AP credential and ensure local recovery before updating an installed board.

OTA confirmation requires 30 continuous seconds with active bridge, Wi-Fi association and Ethernet link, independently of MQTT/client traffic. Configured devices stuck in provisioning do not confirm the new image; unconfigured provisioning remains a valid initial-commissioning state. PR #4 bounds validation to three minutes after blocking startup completes; readiness interruptions reset the 30-second stability interval but never extend that deadline. An unconfirmed pending image is rolled back at the deadline. If the rollback API returns, the firmware logs the error and restarts unconfirmed so the rollback-enabled bootloader can reject it. Already validated images are unaffected. These local checks cannot prove end-to-end connectivity or full datapath health.

## Hardware assumptions

Power and antenna choices remain unresolved. Verify board input specifications, regulation, current capacity and isolation before connecting a supply; do not assume the QE4 offers regulated 5 V or PoE. Any external antenna modification requires physical RF and link-stability checks. No supply or antenna has been physically verified.

## Remaining work

This is not the completed production architecture. PR #4 removes gateway probes, isolates outbound MQTT and authenticates all registered provisioning routes; see [local-recovery-and-access.md](local-recovery-and-access.md). Independent DNS, transactional configuration/address validation, security tradeoffs and maximum setup duration remain open. The serial factory-erase path remains separate from non-destructive provisioning; a portal reset action is optional. No outbound-only firewall or hardware-verified zero listening ports is claimed.

Before deployment, test DHCP/ARP and bidirectional Modbus, MAC replacement, physical setup without data loss, unique-secret persistence and serial-only visibility, broker outage, cable/Wi-Fi recovery, OTA rollback (including link loss), antenna/power stability and an unattended soak. See [implementation-design.md](implementation-design.md) for the remaining design and acceptance criteria.

## Build verification

The original implementation reported a WT32 4 MB build on the pinned PlatformIO platform/ESP-IDF 5.5.1: 968720 bytes (49.3% of a 1966080-byte slot). It reported matching bootloader/app headers, Kconfig size, generated partition bounds and app fit, plus rejection of wrong-size headers, oversized apps and out-of-bounds partitions. This is prior build evidence, not a new build or hardware verification. Rebuild/check only `wt32-eth01-4mb` after firmware changes. An existing IRAM declaration warning remains.

PR #4 final-review fixes were rebuilt for `wt32-eth01-4mb` using the pinned platform/ESP-IDF 5.5.1 and its PlatformIO Core 6.1.18. The artifact checker passed: 4 MB app/bootloader headers, effective flash configuration, generated partition bounds and 969488 / 1966080 bytes per OTA slot (49.3%); rollback is enabled in the generated configuration. All five host suites passed (`test_runtime_policies.cpp`, `test_boundaries.py`, `test_config_layout.py`, `test_watchdog.py`, `test_ota.py`). New cases cover OTA success/deadline/flapping/temporary outages/API errors/timer wrap, Ethernet offline/recovery within and across watchdog windows, driver retries and counter wrap. Negative controls disabling the deadline or restoring Ethernet total-drop classification failed as expected. The existing IRAM declaration warning remains. Not hardware-tested.

## Acceptance still required

Provision and validate DNS independently of the gateway; reject malformed/non-unicast addresses, invalid masks/routes/ports and known client-IP collisions; document DHCP exclusions and safe configuration migration/failed saves. Review broker ACLs, TLS/trusted-time and credential storage (secure boot/flash encryption are not claimed). Define whether an absolute setup-session timeout is needed alongside inactivity return. Serial factory erase is a separate intentional reset mechanism; a portal reset action is optional follow-up, not an implemented feature.

PR #4 implements local recovery, isolated MQTT and route authentication at this head. Intentional queue-cap/throttle and offline drops remain telemetry, not watchdog failure evidence. Verify shared-MAC IPv4/ARP receive paths, cold boot, DHCP/DNS/broadcasts, bidirectional Modbus, idle client, broker outage/reconnect, Wi-Fi loss/recovery, settings-preserving setup, NVS migration and OTA rollback on the actual WT32/4 MB board. Not hardware-tested.
