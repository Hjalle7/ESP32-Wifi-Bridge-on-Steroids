# Heat-pump bridge implementation design

Status: target design with an initial implementation slice; see [wt32-deployment.md](wt32-deployment.md) for implemented behavior and remaining work. Hardware validation has not been performed.

This fork targets a transparent bridge for an Ethernet heat pump, with a static IPv4 telemetry endpoint and administration available only through an explicit provisioning mode. Extend the existing firmware. WT32-ETH01 is the first-choice deployment hardware. Olimex ESP32-POE-ISO-EA-16MB remains a secondary candidate, conditional on the clock qualification below; it does not block WT32 development.

## Hardware mapping and first qualification gate

| Property | Olimex ESP32-POE-ISO-EA-16MB | Existing WT32-ETH01 target |
| --- | --- | --- |
| SoC/module family | Original ESP32, WROOM variant, external antenna | Original ESP32 with LAN8720A |
| Flash | Manufacturer specifies 16 MB; verify actual board | 8 MB on upstream reference board; verify purchased unit |
| Ethernet interface | Internal EMAC, RMII | Internal EMAC, RMII |
| PHY | LAN8710A shown in Rev.N schematic; LAN87xx driver candidate | Existing LAN87xx driver |
| PHY address | 0 in Olimex examples | 1 in current code |
| MDC / MDIO | GPIO23 / GPIO18 | GPIO23 / GPIO18 |
| PHY power enable | GPIO12, high in manufacturer example | GPIO16, high in current code |
| RMII reference clock | ESP32 output on GPIO17, inverted 50 MHz | External input on GPIO0 |
| Provisioning input candidate | BUT1 on GPIO34, active low | Dedicated input on GPIO14, currently factory reset |

Olimex's sample configuration calls the PHY LAN8720, while its Rev.N schematic identifies LAN8710A. Use the LAN87xx driver only after confirming the actual PHY identity and address on the purchased revision. The WROOM 16 MB variant must not be confused with WROVER/PSRAM variants, which have different pin constraints. GPIO34 is input-only and has no internal pull-up: confirm the board's external bias from the actual schematic and idle voltage; do not copy the current pull-up-based reset helper unchanged.

**Qualification gate for Olimex only: simultaneous Wi-Fi and Ethernet clocking.** Espressif's ESP-IDF v5.5 Ethernet guide explicitly advises against sourcing REF_CLK from ESP32 when Wi-Fi is active, due to clock instability. Olimex's normal WROOM wiring uses that clock source on GPIO17. Manufacturer Ethernet examples alone do not prove reliable simultaneous STA bridging. Before accepting this board, test the exact board revision and pinned toolchain with Ethernet and Wi-Fi active, including cold boots, reconnects, sustained bidirectional traffic and an unattended soak. A passing limited test is evidence, not a guarantee against the documented limitation. If unreliable, prefer WT32 with its external clock, or evaluate an external-clock hardware modification against the schematic; no GPIO-only software setting can create an unwired clock source.

Power: the Olimex board supports isolated IEEE 802.3af PoE input and other supply options. The Ethernet port connects to the heat pump, so do not assume PoE is available from the pump. Select USB or another manufacturer-supported supply unless the actual topology provides a PoE PSE. The board is not a PoE power source for the pump. Validate power stability and temperature in the intended enclosure. The product's commercial temperature rating is 0–70 C; verify the enclosure conditions.

## Board support design

Use the existing `wt32-eth01` PlatformIO environment on the pinned platform as the primary implementation and validation target. Verify the actual board revision, flash capacity and antenna arrangement before deployment; the upstream reference board has 8 MB, which must not be assumed for every WT32 unit. Retain C5 support without making it the deployment candidate. Defer a dedicated `olimex-esp32-poe-iso-ea-16mb` environment until that secondary candidate is revisited.

When adding Olimex support, move board-specific PHY address, power GPIO, RMII clock mode/pin and provisioning input into explicit compile-time board profiles. Keep the shared raw-frame forwarding code unchanged in the first hardware patch. The Olimex profile needs ESP-IDF internal RMII clock output with inverted GPIO17 output, rather than the hard-coded external GPIO0 input in `bridge_eth_init()`. Verify the exact API enum against the pinned SDK at implementation time. Do not merely change PHY power and address.

For the optional Olimex target only, set both `board_build.flash_size` and `board_upload.flash_size` to 16MB, and validate generated image headers plus the physical flash ID. Start with a separately named 16 MB partition table preserving the existing offsets and two 3 MB OTA slots, 24 KB NVS and 64 KB coredump, leaving the remaining capacity unallocated. Extra flash does not require larger application slots. Check NVS capacity for the expanded configuration. First deployment uses a cable because partition tables cannot be changed through ordinary app OTA. Do not carry a 16 MB image header onto a smaller WT32.

## Runtime states

| State | Forwarding | STA IPv4 / MQTT | AP and HTTP |
| --- | --- | --- | --- |
| Boot | Off until client MAC learned | Not started | Off |
| Bridge | Active | Static IPv4, outgoing telemetry | Off |
| Provisioning | Off | MQTT off; no upstream STA | Password-protected AP and portal |
| Recovery | Local staged recovery | Telemetry best effort | Off unless recovery policy selects provisioning |

Use exclusive provisioning rather than AP+STA bridging in the first implementation. A clean reboot separates driver lifecycles and avoids partial Wi-Fi reinitialization. Entering provisioning must not clear stored configuration.

Proposed physical control, subject to real GPIO qualification: holding the designated input for 3 seconds during normal operation requests provisioning after release, sets a one-shot RTC marker and performs a planned reboot. Consume the marker once on boot. A hold at boot also enters provisioning without erasing data. GPIO0/BOOT is not used because it selects ROM download mode. Factory reset is a separately authenticated portal action with explicit confirmation, not a longer version of the same button gesture. Keep serial recovery available. Account for watchdog resets and the boot-loop guard so a deliberate mode transition is not counted as a failed boot.

Keep the existing 15-minute inactivity return to bridge mode when saved credentials exist, excluding background status polls from activity. Unconfigured boards remain in provisioning. Saving valid settings schedules a reboot; leaving without saving retains the previous configuration. Add a separate maximum session duration, proposed 30 minutes for configured devices, so a forgotten browser cannot keep the AP up indefinitely. These durations are initial design defaults, not existing guarantees.

Generate a per-device random AP secret using ESP hardware randomness, persist it, and expose it through local serial at first commissioning or a physical label. Do not derive it from MAC or reuse `bridgesetup`. Ensure the operator can obtain the secret before installing the board; never publish it through MQTT or ordinary logs. Enforce authentication on all provisioning APIs, apply request/body limits, and require an explicit confirmation for destructive actions. The AP password protects transport access, not HTTP authentication by itself. OTA and credential responses require authentication. Secret fields remain masked; an empty password field means unchanged.

## Bridge and telemetry IP path

Retain the static STA netif and current IP-based ARP/IPv4 demultiplexing initially. The client and ESP32 share the cloned MAC but have distinct IPs. Deliver ARP for the telemetry IP and IPv4 destined to that IP to lwIP; forward client traffic unchanged. Preserve callback buffer ownership and single delivery/free on every path. Test both Ethernet-originated and Wi-Fi-originated frames, malformed/short frames, broadcasts and client DHCP. No extra Ethernet netif, NAT or DHCP client is required.

No HTTP server is started in bridge mode. Disable NetBIOS responder startup there: `netbios_update_name()` currently starts an unnecessary listening UDP service. Disable the current SNTP startup as well: `crashlog_time_start()` contacts the gateway and public NTP, outside the MQTT-only traffic policy. Use uptime and Home Assistant receipt timestamps for telemetry/crash correlation. DNS is allowed only when needed to resolve a configured broker hostname; a numeric broker address avoids that dependency. ARP and TCP responses remain necessary. Do not claim that removal of HTTP alone creates an outbound-only firewall: audit actual sockets, scan the telemetry IP, and capture ESP32-originated traffic.

The bridged client's IPv4, broadcasts and any other required Ethernet traffic must not inherit restrictions intended for ESP32's telemetry stack. IPv6 is disabled on the ESP32 stack for this deployment; that is separate from a policy on forwarded frames.

MQTT runs in its own task with bounded buffers, backoff and non-blocking producer queues. Audit `esp_mqtt_client_publish()` calls from main-loop/watchdog paths: the current API may block despite a comment claiming immediate return. Prefer bounded non-blocking enqueueing or a dedicated worker; drop/coalesce telemetry when offline. MQTT never determines watchdog health or OTA acceptance. No subscriptions, remote commands or broker-triggered restarts. Preserve availability/LWT and Home Assistant discovery; ACLs must allow both the device topics and its specific discovery topics. Evaluate TLS with certificate validation and a defined trusted-time strategy; do not add insecure certificate bypasses to avoid the SNTP decision.

## Local watchdog and profile selection

Monitor Wi-Fi driver state/disconnect events, Ethernet link, forwarding attempt/completion/error counters, queue age and task heartbeats. A quiet Modbus client is healthy: lack of frames alone must never trigger a reset. Local indicators cannot prove remote end-to-end reachability; report this limit rather than reintroducing ping.

Use separate symptoms and cooldowns: reconnect Wi-Fi for persistent Wi-Fi failure, restart Ethernet for evidenced local Ethernet/queue failure, and restart the board only after bounded lighter recovery attempts. A disconnected Ethernet cable is not a reason for an endless reboot loop. Bound recovery frequency and preserve crash evidence. Broker outage produces MQTT retry only.

Remove `gateway_reachable()` calls from watchdog and automatic location detection. First production version uses an explicitly selected saved network/IP profile, configurable in provisioning. It does not guess location from identical SSIDs. BSSID-based matching is an optional later design, with roaming implications; SSID alone is insufficient. Ensure roaming cannot silently reapply a profile by ping.

## Configuration and updates

Append new DNS, provisioning and profile-selection fields to BridgeConfig; do not move or resize existing fields. Load older short blobs onto defaults and validate before use. Validate contiguous netmask, usable unicast address, subnet/gateway consistency where applicable, DNS/broker syntax, MQTT port and string limits. Reject an address equal to a known client address; document DHCP reservation/exclusion because static validation cannot prove absence of network conflicts.

Retain a last-known-good configuration or explicitly versioned pending configuration so malformed/new settings cannot destroy the only recovery route. Verify atomic NVS save and migration failure paths. Failed Wi-Fi startup retains saved credentials and can enter the protected portal under the existing bounded recovery policy.

Proposed update policy: authenticated OTA in provisioning only, with USB recovery. Keep rollback enabled. Confirmation must match the intended boot mode: a newly flashed configured device should prove successful bridge startup, stable Wi-Fi association and local datapath health for at least 30 seconds after startup, without requiring MQTT or client traffic. Time since boot alone is insufficient. A deliberately requested provisioning session must not accidentally validate an image that cannot bridge; make the update flow return to bridge mode to verify. Define separate initial commissioning acceptance for devices with no saved credentials. Exercise rollback on real hardware, including bad credentials, power interruption and failed bridge initialization.

## Small implementation patches and acceptance

1. Establish the WT32 baseline using its existing build environment. Verify the actual board revision, flash capacity and partition compatibility, antenna solution, power, simultaneous Ethernet/Wi-Fi and DHCP/ARP before changing runtime behavior. Olimex board profiles and its clock qualification are deferred and are not prerequisites for WT32 work.
2. Explicit runtime states and button-driven provisioning without reset. Verify saved settings survive entry, timeout and reboot. Validate unique AP secret and separate factory reset.
3. Remove normal-mode HTTP, NetBIOS and SNTP startup. Verify no listening management ports and capture only required telemetry-stack traffic. Verify DHCP/ARP and client Modbus reads/writes continue.
4. Local watchdog and explicit profile selection. Inject Wi-Fi outage, cable removal, local queue failure and prolonged quiet traffic. Confirm bounded recovery and no broker-dependent resets.
5. DNS/IP persistence and isolated MQTT worker. Test old NVS blobs, rejected settings, interrupted saves, broker outage/backpressure, discovery ACLs and recovery.
6. Provisioning OTA/rollback and soak. Test client replacement/MAC relearning after link-up, cold boots, double-direction traffic, reconnection, update failure and representative long-term Modbus use.

Build success does not demonstrate hardware compatibility or transparent forwarding. No throughput tuning is proposed; use load only to qualify clock, power and reliability. Keep WT32 usable throughout. C5 changes require its build check as well.

## Sources and evidence

Manufacturer sources consulted for this mapping (check the purchased PCB revision):

- [Olimex product and variant specifications](https://www.olimex.com/Products/IoT/ESP32/ESP32-POE-ISO/open-source-hardware)
- [Olimex Rev.N schematic](https://github.com/OLIMEX/ESP32-POE-ISO/blob/c19307ecd8a9d8c5703de7a1571cd89945e39c01/HARDWARE/ESP32-PoE-ISO-Rev.N/ESP32-PoE-ISO_Rev_N.pdf)
- [Olimex WROOM 16 MB ISO example and GPIO mapping](https://github.com/OLIMEX/ESP32-POE/blob/deb38a377d50eadb04ddc7118a17a5ae58b1ee53/SOFTWARE/ESPHOME/esp32-poe-iso-16mb.yaml) (mapping reference, not a firmware dependency or simultaneous bridge test)
- [ESP-IDF v5.5 Ethernet guide: RMII clock and Wi-Fi restriction](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/network/esp_eth.html)

Repository code inspected: `src/bridge.cpp`, `src/main.cpp`, `src/config.h`, `src/config.cpp`, `src/web.cpp`, `src/telemetry.cpp`, `src/crashlog.cpp`, `platformio.ini`, and `sdkconfig.defaults`. Requirements come from the user's Second Brain 2 project overview and project summary; this document makes the plan available in the repository without relying on Dropbox access.
