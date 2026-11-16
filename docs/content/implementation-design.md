# Heat-pump bridge implementation design

Status: target design with an initial implementation slice; see [wt32-deployment.md](wt32-deployment.md) for implemented behavior and remaining work. Hardware validation has not been performed.

This fork targets a transparent bridge for the Qvantum QE4 heat pump, with a static IPv4 telemetry endpoint and administration available only through explicit provisioning. Extend the existing ESP-IDF/PlatformIO firmware. [AGENTS.md](../../AGENTS.md) is the source of current requirements.

## Supported hardware and first qualification gate

Only WT32-ETH01 with classic ESP32, LAN8720 Ethernet and 2.4 GHz Wi-Fi using a 4 MB flash configuration is supported. Olimex, ESP32-C5/W5500 and 8 MB variants are outside this project's implementation and validation scope. Retained legacy configurations/code are not supported product targets; delete them only after checking WT32/shared-code dependencies.

WT32 wiring in the existing implementation: PHY address 1, MDC GPIO23, MDIO GPIO18, PHY power GPIO16 and external RMII clock input GPIO0. GPIO14 is the proposed provisioning input; qualify the actual board wiring before use. Do not change the shared forwarding path to add another board.

Before flashing, read the purchased unit with `esptool flash-id`. Do not infer its capacity from an upstream reference board. The retained `wt32-eth01` environment assumes 8 MB and must not be used for this deployment. This slice adds `wt32-eth01-4mb`; use only that environment and verify matching PlatformIO flash settings, effective sdkconfig, application/bootloader headers and the 4 MB partition/OTA budget. Initial installation and partition changes require a cable; app-only OTA cannot migrate the partition table.

Power is unresolved: verify board input specifications, regulation and isolation before connecting a supply. Do not assume the QE4 provides regulated 5 V or PoE. Antenna/enclosure modifications require physical RF and link-stability validation.

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

1. Establish and validate the WT32 4 MB build, partition layout and OTA/rollback budget before flashing. Verify the actual board flash ID, antenna, power, simultaneous Ethernet/Wi-Fi and DHCP/ARP. Do not build or test unsupported targets.
2. Explicit runtime states and button-driven provisioning without reset. Verify saved settings survive entry, timeout and reboot. Validate unique AP secret and separate factory reset.
3. Remove normal-mode HTTP, NetBIOS and SNTP startup. Verify no listening management ports and capture only required telemetry-stack traffic. Verify DHCP/ARP and client Modbus reads/writes continue.
4. Local watchdog and explicit profile selection. Inject Wi-Fi outage, cable removal, local queue failure and prolonged quiet traffic. Confirm bounded recovery and no broker-dependent resets.
5. DNS/IP persistence and isolated MQTT worker. Test old NVS blobs, rejected settings, interrupted saves, broker outage/backpressure, discovery ACLs and recovery.
6. Provisioning OTA/rollback and soak. Test client replacement/MAC relearning after link-up, cold boots, double-direction traffic, reconnection, update failure and representative long-term Modbus use.

Build success does not demonstrate hardware compatibility or transparent forwarding. No throughput tuning is proposed; use load only to qualify clock, power and reliability. Keep WT32-ETH01/4 MB usable throughout; no all-environments build is required.

## Status and outstanding requirements

PR #2 provides the design. This PR #3 slice adds the 4 MB target, non-destructive provisioning entry, unique AP credentials and provisioning-only management/OTA. PR #4 builds on it for local recovery, isolated MQTT and setup authentication, including separation of intentional drops from driver-failure health evidence. These changes are present at this stacked head, not main. See the deployment guide for implementation limits; design sections above describe the target, not completion.

Before deployment, complete independent DNS provisioning, transactional configuration validation (netmask/routing, usable addresses, MQTT port and string limits), known-client collision checks and DHCP exclusion guidance. Decide maximum setup-session duration, update/rollback acceptance and credential-storage/TLS/broker-ACL tradeoffs explicitly. Secure boot and flash encryption are not claimed enabled. Qualify QE4-relevant profiles/tuning and local driver/queue/task fault detection without treating intentional rate limiting or idle traffic as faults.

Hardware acceptance must cover cold boot, MAC cloning, shared-MAC IPv4/ARP reply demultiplexing, DHCP/DNS/broadcast forwarding, bidirectional Modbus TCP, idle client, broker outage/reconnect, Wi-Fi/cable recovery, provisioning without reset, old NVS blobs, OTA/rollback, power/antenna stability and soak. Builds alone do not establish readiness. Not hardware-tested.

## Source of truth

Requirements: [AGENTS.md](../../AGENTS.md). Implementation: `platformio.ini`, sdkconfig and partition files, `src/bridge.cpp`, `src/main.cpp`, `src/config.*`, `src/web.cpp` and `src/telemetry.cpp`. Historical upstream hardware notes do not expand the supported target scope.
