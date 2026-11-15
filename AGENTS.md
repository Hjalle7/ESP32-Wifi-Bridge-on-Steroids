# AGENTS.md — Qvantum QE4 Wi-Fi bridge fork

Instructions for coding agents and reviewers. **This fork's requirements take precedence over inherited upstream documentation, build targets, examples and assumptions.** Read this file and the actual source/configuration before making claims. Do not treat intended functionality as implemented.

## Project scope and hardware

- **Only supported product target: WT32-ETH01, classic ESP32 with LAN8720 Ethernet PHY and 2.4 GHz Wi-Fi, using a 4 MB flash configuration.** The actual flash chip on the purchased board must be checked with `esptool flash-id` before flashing. Do not assume the original author's measured 8 MB chip applies to this board.
- Do not develop or test unrelated hardware targets, including ESP32-C5/W5500 and 8 MB variants. They are not product requirements. Only inspect legacy code when needed to remove it safely or to assess shared-code regressions.
- The existing `platformio.ini` still defines an 8 MB WT32 build and a C5/W5500 build. **These are legacy configurations, not evidence that either is a supported target.** Before hardware flashing, implement and validate a 4 MB-compatible partition table, OTA slots, image header, sdkconfig and PlatformIO settings. Do not flash an 8 MB image to a 4 MB chip.
- Preserve ESP-IDF via PlatformIO (no Arduino) unless a specific change is approved. Keep existing bridge implementation; avoid a wholesale rewrite.

## Purpose and network invariants

The device provides an Ethernet-to-Wi-Fi bridge for a **Qvantum QE4 heat pump**, allowing Home Assistant and Modbus TCP communication over the existing network.

- Preserve the existing transparent, MAC-cloning layer-2 bridge design: the heat pump remains in the existing IPv4 IoT VLAN/subnet and obtains its own address from the existing DHCP server. **No NAT, double NAT, additional routed subnet, WDS requirement or IPv6 dependency.**
- Keep a **separate, configurable static IPv4 address for the ESP32's own outbound MQTT telemetry** (not a permanent management service). It must not collide with the heat pump address or DHCP allocations. Configure IP, netmask, gateway and DNS in provisioning. Validate uniqueness and routing assumptions; sharing the cloned MAC across two IP addresses requires careful ARP and receive-path handling.
- Normal operation must expose **no HTTP portal, admin API, OTA endpoint or other listening management service**. Do not accidentally remove the local IPv4 stack needed for outbound MQTT and its replies.
- MQTT is **outbound telemetry only** for Home Assistant, including useful link status (RSSI, connection state, uptime, reconnects, watchdog/recovery counters). No inbound MQTT commands, control or remote configuration. MQTT outages must not block Ethernet/Wi-Fi forwarding.
- Preserve bidirectional Modbus TCP, ARP, DHCP, DNS and relevant broadcast traffic for the bridged client. Avoid assumptions that traffic is continuous; an idle heat pump is not a failed bridge.

## Provisioning, security and recovery

- Provide an explicit **non-destructive** provisioning entry mechanism that retains saved settings. Factory reset must be a separate intentional operation. Define the physical trigger, boot behavior, timeout and exit path before implementing.
- Run setup AP and web administration **only while provisioning**. Do not use a shared/default AP password such as `bridgesetup`; use a unique strong credential or another defensible first-use enrollment method.
- Provision Wi-Fi settings, static ESP32 IPv4/netmask/gateway/DNS, MQTT broker/port/credentials, and any necessary recovery settings. Validate input and preserve backward compatibility of existing NVS `BridgeConfig` blobs: **append fields, never reorder existing fields** without an explicit migration.
- Management functions, firmware updates and diagnostics must be provisioning-only. Choose USB flashing and/or provisioning-only OTA deliberately; if OTA is retained, verify the 4 MB dual-slot partition budget and meaningful rollback/confirmation. Never assume the original 8 MB layout fits.
- Use a **local watchdog**, not gateway ping, DNS, MQTT, internet access or Modbus response as the sole health criterion. Detect genuine link/driver faults, distinguish low traffic, and escalate conservatively (link recovery, Wi-Fi reconnect, reboot). Avoid recovery loops and preserve crash diagnostics where feasible.
- Avoid unauthenticated configuration writes and unprotected OTA in provisioning. Review secret handling, broker ACLs, optional TLS, flash encryption and secure boot as explicit tradeoffs; do not claim these are enabled without evidence.
- No hard-coded personal IP addresses, SSIDs, passwords, names, network topology or other private deployment details in committed code or documentation.

## Implementation and code review

- **Scope every review to the supported WT32-ETH01 4 MB target and the QE4 use case.** Ignore inherited C5/W5500 and 8 MB issues unless they directly break shared code or the 4 MB migration.
- Review the actual diff/PR and surrounding affected code, not unrelated upstream features. Prioritize functional correctness, memory safety, frame/buffer ownership, concurrency, deadlocks, Wi-Fi/ETH callbacks, NVS migration, flash/OTA safety, watchdog loops and security.
- Explicitly distinguish **existing behavior**, **planned behavior**, **untested assumptions** and **verified on target hardware**. Do not infer completion from this document or from a passing build.
- Check relevant open PRs (#2–#4) and their base/head branches before recommending changes or merging; do not assume their changes are already in `main`. Avoid duplicating or conflicting with in-flight work.
- Keep changes minimal and isolated. Use a separate branch and PR; do not merge without review. Do not modify unrelated targets merely to satisfy an all-environments build.
- Use English for source comments, identifiers, logs, UI and technical documentation. Explain non-obvious functions and ownership/task/IRAM constraints; avoid personal details and historical anecdotes in code comments.
- Respect hot-path timing and buffer ownership: receive callbacks must release/forward each buffer exactly once. MQTT, scans, provisioning and diagnostics must not block the forwarding path.
- Treat `sdkconfig.*` as potentially stale generated configuration. Verify effective settings, partition offsets, image headers and flash sizes instead of trusting comments or a successful compile.
- Build the supported 4 MB configuration once it exists. Hardware validation must cover: cold boot, MAC cloning, DHCP/ARP, bidirectional Modbus TCP, idle client, MQTT broker outage/reconnect, Wi-Fi loss/recovery, provisioning without reset, saved configuration migration, and firmware update/rollback if supported.
- If hardware is unavailable, report **not hardware-tested**; do not claim production readiness.

## Legacy implementation to change or remove

This is a **migration checklist**, not a list of features to preserve. Verify each item against the current branch and open PRs before changing it. Remove an item from this checklist once the code and configuration are updated and verified. Keep historical explanations in Git history or `docs/content/history.md`, not in this file.

| Existing or inherited behavior | Required disposition |
| --- | --- |
| WT32 build assumes 8 MB flash and uses `partitions_8mb_ota.csv` | Replace with a validated 4 MB configuration, including image header and viable OTA/rollback strategy. Confirm the actual chip first. |
| Additional ESP32-C5/W5500 build target | Remove from the supported build/review workflow; delete target-specific code/config only when safe for the WT32 build. |
| HTTP management server and API available in normal bridge mode | Disable/remove normal-mode listeners; keep administration and diagnostics in provisioning only. Preserve outbound MQTT connectivity. |
| Shared/default setup AP password | Replace with secure first-use provisioning credentials/enrollment. |
| Factory-reset GPIO also used to enter setup | Provide a separate non-destructive provisioning path; retain an intentional factory reset. |
| Gateway ping used by watchdog | Replace health detection with local link/driver signals, with idle-client protection and staged recovery. |
| Gateway ping used to identify network profile | Remove or redesign independently of watchdog; verify need for multiple profiles. |
| IP-camera-centric tuning, multi-site/5 GHz features and obsolete diagnostics | Keep only if justified for the QE4 and supported hardware. Avoid deleting shared behavior without checking dependencies and NVS compatibility. |
| HTTP OTA endpoint reachable in normal mode | Move to provisioning-only OTA or replace with USB flashing; revalidate 4 MB partition and rollback constraints. |

Do not assume any checklist item is still present after PR #2–#4. Review the actual code and mark it resolved only after evidence. This checklist describes **work to inspect**, not confirmed bugs in every branch.

## Repository navigation and source of truth

- `platformio.ini`, `sdkconfig.defaults`, `sdkconfig.wt32-eth01`, partition CSV files: inspect **actual** build settings; inherited 8 MB/C5 definitions need cleanup as separate implementation work.
- `src/bridge.cpp`: Ethernet/Wi-Fi forwarding, MAC cloning, network callbacks, watchdog.
- `src/config.cpp` / `src/config.h`: persisted configuration and NVS compatibility.
- `src/web.cpp`: existing portal/API; planned restriction to provisioning.
- `src/telemetry.cpp`: MQTT state and Home Assistant discovery.
- `src/main.cpp`: startup, provisioning lifecycle, recovery/OTA confirmation.
- `docs/content/handoff.md`, `docs/content/backlog.md`, `docs/content/history.md`: inherited implementation notes and history; they may describe the original camera/8 MB/C5 setup and **are not current requirements for this fork**. Update handoff/backlog when implementation status changes.

## Unresolved project decisions

1. Confirm actual flash size and establish a safe 4 MB partition/OTA plan.
2. Choose the non-destructive provisioning entry/exit mechanism and secure AP enrollment.
3. Choose provisioning-only OTA vs serial-only updates and define rollback behavior.
4. Verify ARP/frame demultiplexing for ESP32 telemetry IP alongside the cloned heat-pump MAC.
5. Retain only QE4-relevant roaming, network profiles and tuning; preserve configuration migration where needed.
6. Define the precise local watchdog signals and recovery thresholds.
7. Validate practical Wi-Fi coverage with the installed enclosure and any external antenna modification; RF hardware modifications require physical verification.
8. Power supply for the board is **not yet settled**. Do not assume the QE4 provides a suitable regulated 5 V output; confirm electrical specifications and isolation before connecting it.

**Priority:** a secure, stable, maintainable QE4 bridge on WT32-ETH01/4 MB, not feature parity with upstream.
