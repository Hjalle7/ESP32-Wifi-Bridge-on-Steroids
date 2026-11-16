# Local recovery, isolated telemetry and setup authentication

This implementation extends the WT32-ETH01/4 MB deployment slice, the only supported target. Retained C5/W5500 and 8 MB environments are legacy and are not part of build or device validation. Hardware verification remains outstanding. It does not add a listening service in normal bridge mode.

## Local-only recovery

The optional watchdog remains off by default. When enabled, it evaluates twenty-second windows using local Wi-Fi state, reconnect count and forwarding results. No ICMP/gateway probes are sent by either watchdog or profile selection.

- An unplugged Ethernet cable or a quiet client does not trigger recovery.
- Disconnected Wi-Fi requests a connection attempt; frequent reassociation requests reconnects. These symptoms alone never reboot the board during an ordinary AP outage.
- At least 200 driver forwarding attempts are required before a 15% failure ratio is treated as evidence. A dedicated failed Wi-Fi transmit counter excludes intentional queue-cap/throttle and offline drops from both the fault count and attempt denominator; total drop telemetry is unchanged. Wi-Fi-direction failures can trigger reconnect escalation; Ethernet-direction transmit failures can trigger an Ethernet driver reset first.
- Consecutive bad windows use the configured threshold. A changed symptom resets escalation. Recovery actions are at least sixty seconds apart.
- Persistent forwarding errors may escalate to a coredump reboot, with at most two such reboots while the RTC budget is retained. Ten healthy minutes with both links up restore that budget. A real power loss can reset RTC state. Exhausting the budget leaves lighter recovery available; it does not freeze forwarding.

No end-to-end connectivity test is implied. A silent upstream failure with apparently healthy local drivers can remain undetected. Local queue-heartbeat/hung-task coverage beyond the existing platform mechanisms is not claimed.

## Explicit IP profile

Select **Telemetry IP profile** in setup. Values 1–3 select the saved static IP/netmask/gateway group independently of the SSID that connects. The setting defaults to profile 1 for old configuration blobs; an empty optional profile falls back to profile 1. Wi-Fi roaming/failover cannot silently select another IP profile by pinging gateways.

Devices moving between different IP networks must be configured explicitly before use there. This replaces automatic location detection; transparent client forwarding is unchanged. The new field is aligned beyond the legacy struct's trailing padding, preserving every old field offset and preventing old padding bytes from overriding the default.

## MQTT worker and bounded memory

Main-loop and watchdog producers copy messages to a four-entry FreeRTOS queue with zero wait. Offline/full/oversized messages are dropped; a `telemetry_drops` state field counts local saturation/size drops. Each message carries the connection generation so the worker rejects messages from a previous connection. A dedicated low-priority task owns all socket-facing publications and discovery. MQTT callbacks only update atomic connection state/generation.

The network timeout is one second, reconnect pacing five seconds, and QoS outbox limit 8192 bytes. Discovery failures retry at most once per five seconds and resume at the first unsent item, so slow acknowledgements cannot starve later sensors by repeatedly filling the outbox with the prefix. Availability/LWT and retained Home Assistant discovery remain; there are no command subscriptions. The worker has a 6 KB stack and the queue consumes about 3.3 KB plus queue overhead; outbox memory is allocated as needed up to its limit plus protocol overhead. Runtime free heap and stack high-water marks still require device/load testing, on the supported WT32/4 MB board.

If worker allocation fails, telemetry startup fails without taking down bridging. A watchdog reboot event is best effort and may be lost because recovery never waits for network transmission or ACKs. Local crash/reason records remain the recovery evidence.

## Provisioning authorization and lifetime

Configured devices enter setup only through a deliberate IO14 hold of at least three seconds at boot, or a runtime hold followed by release. Runtime entry uses a one-shot RTC request accepted only on its requested software reset. Failed association, missing client MAC, repeated failed boots, watchdog recovery and Ethernet initialization failure never authorize setup and never erase saved settings. An unconfigured device (`configured == false`) still starts initial setup automatically; an empty SSID on an otherwise configured device does not authorize it.

After the bounded initial Wi-Fi association attempts, the initialized station stays in normal mode. Normal-mode ticks request reconnects at most once per five seconds independently of the optional watchdog. Disconnect callbacks do not immediately reconnect. Existing bounded watchdog/failover recovery remains available. Initialization failures leave the device inactive with management disabled, without reboot cycling; the setup GPIO remains available. A missing, never-learned client MAC leaves the sniff callback running with 50 ms sleeps, GPIO polling and OTA validation until a client appears. Driver initialization failures require physical setup or a deliberate restart after repair.

Configured setup retains the existing inactivity timeout and adds a fixed 30-minute deadline from entry. Authenticated page/configuration/scan activity can reset inactivity, but cannot reset the absolute deadline; status polling still does not reset inactivity. HTTP dispatch rejects new requests at the absolute deadline. On either timeout the main task stops the Wi-Fi radio (disconnecting in-flight HTTP/OTA), clears any setup request and performs a planned reboot into normal operation. No saved configuration is erased. A continuously held boot setup pin cannot authorize another session across that reboot: it must be released and deliberately held again. First-time setup has no idle or absolute deadline. Pending OTA validation still requires local readiness and rolls back on its existing deadline without requiring provisioning.

## Setup authentication

Every registered HTTP route, including `/`, status/configuration, reboot/reset, scan, logs, crash diagnostics and OTA, passes the same authentication and origin gate before its handler executes. Unauthenticated requests receive HTTP 401 and a Basic challenge. Origin mismatch or cross-site browser requests receive HTTP 403. No wildcard CORS access is granted. Responses disable caching.

Browser login:

- Username: `admin`.
- Password: saved admin password, or the unique device-local setup/AP password if no admin password is saved.
- Obtain the AP password over local serial before installation. HTTP exists only while provisioning is active.

Credentials are snapshotted for one setup session. Changing the saved admin password takes effect on the next provisioning boot, so a configuration POST cannot change its own authentication halfway through handling. An empty saved admin password never permits anonymous HTTP. Existing browser fetch/XHR requests use same-origin browser authentication; local tools can send `X-Admin-Key` with the same session password. `scripts/ota_flash.sh` now requires the key argument explicitly.

Basic authentication is carried over HTTP inside the password-protected setup WLAN; it is not TLS. The unique AP secret and disabling setup outside commissioning remain necessary. Per-request authentication does not replace credential-storage protection or physical access controls.

## Verification and remaining acceptance

Host tests exercise quiet traffic/cable loss/Wi-Fi loss/thresholds/large counter windows, credential rejection and equality, actual HTTP dispatch with header/origin test doubles, queue saturation with a mandatory zero-wait assertion, resumable discovery after outbox backpressure, and old NVS overlays with deliberately nonzero padding. The embedded portal JavaScript is syntax-checked separately. Test doubles do not validate ESP-IDF socket behavior or timing.

Run `g++ -std=c++17 -Wall -Wextra -Isrc tests/test_runtime_policies.cpp -o /tmp/bridge-policies && /tmp/bridge-policies`, `python tests/test_boundaries.py`, `python tests/test_watchdog.py`, `python tests/test_config_layout.py`, `python tests/test_ota.py`, `python tests/test_scan.py`, and `python tests/test_provisioning.py`. The layout regression test reads the parent implementation commit from Git; use a checkout with that history.

Device acceptance still includes real browser authentication for all methods, cross-origin rejection, setup-password persistence, invalid/changed credentials, broker outage and backpressure, MQTT discovery reconnects, heap/stack limits, local recovery timing, power loss, OTA rollback, DHCP/ARP and Modbus, and a long soak. Independent DNS settings, stricter transactional configuration validation, TLS/trusted-time policy and a decision on an optional portal factory reset remain follow-up work (serial factory erase is already a separate intentional operation). Add client-IP collision checks and DHCP exclusion guidance; reject invalid masks/routes/ports and use transactional configuration updates. Review broker ACLs, credential storage, flash encryption and secure boot explicitly; none is claimed enabled.

The original implementation reported a WT32 4 MB build of 969232 bytes (49.3% of a 1920 KB slot), with matching bootloader/app headers, Kconfig size, partition bounds and OTA fit on the pinned platform/ESP-IDF 5.5.1. That prior evidence does not validate later firmware changes. Build only `pio run -e wt32-eth01-4mb` and run `python scripts/check_flash_layout.py wt32-eth01-4mb 4` after changes. The unchanged bridge helper has an existing IRAM declaration warning. Not hardware-tested.

The watchdog regression harness executes the actual forwarding drop/transmit branches and recovery state machine with simulated drivers/time. It covers sustained queue-cap/throttle-only loss, offline drops at reconnect, mixed policy/driver loss at 14.5%/15%, retry exhaustion, counter wrap and driver-error escalation to reboot, alongside quiet/cable/AP outages, cooldowns and reboot budgets. Policy drops cannot trigger recovery or dilute genuine failure ratios. Host tests do not prove driver timing, physical link health or QE4 reachability.

Correction validation: firmware commit `82cd587` built successfully for `wt32-eth01-4mb` on the pinned platform/ESP-IDF 5.5.1. The artifact checker verified 4 MB bootloader/app headers, effective Kconfig flash size, partition bounds and 969232 bytes in each 1966080-byte OTA slot (49.3%). No unsupported target was built. All four host suites passed, including the expanded watchdog cases; a negative control restoring the faulty total-drop input was rejected. Shell syntax and stacked diff checks passed. The pre-existing IRAM declaration warning remains. Not hardware-tested.

Provisioning regression tests execute the actual startup, GPIO, main loop, OTA validation and paced retry helper with simulated drivers and time. They cover startup association exhaustion, repeated failed boots, Ethernet/Wi-Fi initialization failure, watchdog recovery, stale RTC requests after a watchdog reset, OTA rollback, boot/runtime physical entry, one-shot authorization, held-pin expiry, inactivity extension, the absolute boundary and timer wrap. HTTP boundary tests execute the actual authenticated page handler: activity updates inactivity while the absolute deadline still denies requests. Unconfigured setup remains available past 30 minutes. These host checks do not replace device tests of radio shutdown during active HTTP/OTA, physical GPIO, brownout/watchdog resets or bootloader rollback.

Provisioning correction validation: all seven host suites passed (runtime policies, HTTP/MQTT boundaries, watchdog, NVS layout, OTA, scan and provisioning lifecycle). Negative controls restoring automatic setup after repeated failures and removing the absolute deadline were rejected. The supported `wt32-eth01-4mb` build passed with PlatformIO Core 6.1.18, pinned platform 55.3.34 and ESP-IDF 5.5.1. The artifact checker verified 4 MB bootloader/app headers, effective flash settings, partition bounds and 970480 / 1966080 bytes per OTA slot (49.4%). No unsupported target was built. The existing IRAM declaration warning remains. Not hardware-tested.
