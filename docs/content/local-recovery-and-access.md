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

Run `g++ -std=c++17 -Wall -Wextra -Isrc tests/test_runtime_policies.cpp -o /tmp/bridge-policies && /tmp/bridge-policies`, `python tests/test_boundaries.py`, `python tests/test_watchdog.py`, and `python tests/test_config_layout.py`. The layout regression test reads the parent implementation commit from Git; use a checkout with that history.

Device acceptance still includes real browser authentication for all methods, cross-origin rejection, setup-password persistence, invalid/changed credentials, broker outage and backpressure, MQTT discovery reconnects, heap/stack limits, local recovery timing, power loss, OTA rollback, DHCP/ARP and Modbus, and a long soak. Independent DNS settings, stricter transactional configuration validation, TLS/trusted-time policy, maximum setup-session duration and a decision on an optional portal factory reset remain follow-up work (serial factory erase is already a separate intentional operation). Add client-IP collision checks and DHCP exclusion guidance; reject invalid masks/routes/ports and use transactional configuration updates. Review broker ACLs, credential storage, flash encryption and secure boot explicitly; none is claimed enabled.

The original implementation reported a WT32 4 MB build of 969232 bytes (49.3% of a 1920 KB slot), with matching bootloader/app headers, Kconfig size, partition bounds and OTA fit on the pinned platform/ESP-IDF 5.5.1. That prior evidence does not validate later firmware changes. Build only `pio run -e wt32-eth01-4mb` and run `python scripts/check_flash_layout.py wt32-eth01-4mb 4` after changes. The unchanged bridge helper has an existing IRAM declaration warning. Not hardware-tested.

The watchdog regression harness executes the actual forwarding drop/transmit branches and recovery state machine with simulated drivers/time. It covers sustained queue-cap/throttle-only loss, offline drops at reconnect, mixed policy/driver loss at 14.5%/15%, retry exhaustion, counter wrap and driver-error escalation to reboot, alongside quiet/cable/AP outages, cooldowns and reboot budgets. Policy drops cannot trigger recovery or dilute genuine failure ratios. Host tests do not prove driver timing, physical link health or QE4 reachability.
