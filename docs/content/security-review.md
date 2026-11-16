# Security review

## Scope and outcome

**Final source security review result: APPROVE.** This records the completed
review/correction cycle for the Qvantum QE4 bridge on WT32-ETH01/4 MB only.
It is not deployment approval: **not hardware-tested; deployment readiness has
not been established.** Legacy 8 MB and C5/W5500 targets are outside scope.

The reviewed stack comprised [PR #2](https://github.com/Hjalle7/ESP32-Wifi-Bridge-on-Steroids/pull/2)
(design, head `ee12291`), [PR #3](https://github.com/Hjalle7/ESP32-Wifi-Bridge-on-Steroids/pull/3)
(4 MB/provisioning, head `bb23b45`) and [PR #4](https://github.com/Hjalle7/ESP32-Wifi-Bridge-on-Steroids/pull/4)
(recovery/access and security corrections, final reviewed commit
`217d294d51a6aa8e60604ebed281e8e50dcf540f`). All three are merged.
Final main commit `efe21a523aa96376638065a119df863bbe5f7f27` has exactly the same
Git tree as the reviewed commit (`71551b54e7546e861c4b36ae8a0b69c33461ef00`).

Evidence is the commit history, actual source/tests and the correction records in
[local-recovery-and-access.md](local-recovery-and-access.md),
[wt32-deployment.md](wt32-deployment.md) and [handoff.md](handoff.md).
[AGENTS.md](../../AGENTS.md) defines current requirements; inherited upstream
hardware claims are not QE4 acceptance evidence.

## Architecture and verified source/host guarantees

- Transparent MAC-cloning layer-2 forwarding is retained, with a separate static
  IPv4 telemetry address; no NAT or additional routed subnet is introduced.
  Normal mode does not start HTTP/OTA, NetBIOS or SNTP. This is source evidence,
  not an on-device port scan or an outbound-only firewall guarantee.
- Configured devices require deliberate IO14 authorization for non-destructive
  provisioning. Startup/link/watchdog failures cannot authorize management.
  A persisted random per-device AP secret replaces the shared password; failure
  to generate/persist it does not enable a shared fallback. All registered HTTP
  routes pass authentication and origin checks; credentials are session snapshots.
- Configured setup has inactivity expiry and an absolute 30-minute deadline.
  Expiry revokes admission, cancels active OTA and awaits handler cleanup before
  radio shutdown/reboot. New setup requires fresh physical authorization.
  Storage faults do not automatically erase NVS; a separately stored commissioning
  marker detects configuration loss while that evidence survives.
- MQTT is outbound telemetry without command subscriptions. Producers use a bounded
  zero-wait queue and a separate publishing worker. Local recovery excludes idle
  clients, broker outages and intentional/offline drops as driver-fault evidence.
- The 4 MB dual-slot OTA layout retains rollback. Pending images require 30
  continuous seconds of local readiness within three minutes after blocking startup
  completes. MQTT/client traffic is not required; local readiness does not prove
  end-to-end forwarding.

## Significant findings and corrections

| Finding identified during review | Implemented correction |
| --- | --- |
| Legacy flash assumptions, normal-mode management and shared setup credentials | `6554add`: supported 4 MB layout, provisioning-only services, unique AP secret and physical setup entry. `b4ceef1`: all-route authentication, isolated MQTT and local-only recovery. |
| Policy/offline drops could be mistaken for driver faults; pending OTA could remain unconfirmed indefinitely | `82cd587`, `2ed3492`: separate driver-failure evidence, exclude Ethernet offline drops and bound OTA validation/rollback. |
| Scan SSIDs could break JSON; failure handling and escape-buffer budgets were incomplete | `5de86a3`: bounded reads, complete control-byte escaping, buffer sizing and browser/manual-entry recovery. |
| Fault-driven setup bypassed physical authorization; authenticated activity could prolong setup indefinitely | `8c8c812`: physical authorization on configured devices, paced normal-mode retries, fixed setup deadline and held-pin/RTC safeguards. |
| Storage loss/errors could reopen commissioning or erase settings; Wi-Fi initialization could abort; expiry could race active OTA | `217d294`: fail-closed storage/marker handling, nonfatal partial-driver cleanup and serialized OTA admission/boot selection with acknowledged cancellation. |

## Verification and build status

All eight host suites passed again on post-merge main while preparing this document:
`test_runtime_policies.cpp`, `test_boundaries.py`, `test_watchdog.py`,
`test_config_layout.py`, `test_ota.py`, `test_scan.py`, `test_provisioning.py`
and `test_recovery_failures.py`. They exercise production code with simulated
drivers/time: authentication/origin gates, MQTT backpressure, NVS offsets/migration
and storage faults, GPIO/session policy, recovery thresholds and OTA lifecycle.
Scan checks include ASan/UBSan, JSON round trips and browser error recovery.
Recovery negative controls were rejected. These checks do not validate ESP-IDF
socket/driver timing or physical behavior.

**Clean post-merge build: PASS.** The supplied verification record covers reviewed
commit `efe21a523aa96376638065a119df863bbe5f7f27` and target
`wt32-eth01-4mb`, using Python 3.12.14, PlatformIO 6.1.18, pinned platform
55.3.34 and ESP-IDF 5.5.1. Firmware is 977,296 bytes of a 1,966,080-byte OTA
slot (49.7%), leaving 988,784 bytes per slot. This supersedes the earlier build
size and post-merge TLS blocker recorded here; no build was rerun for this
documentation update.

**Build-environment TLS issue: resolved.** The platform's virtual environment
used a certifi bundle missing the environment's HTTPS proxy CA. Adding the
existing proxy CA to the workspace-local certifi bundle resolved the failure.
TLS certificate verification remained enabled; the fix changed no tracked
repository files.

**Flash-layout verification: PASS.** The repository flash-layout checker and
partition-table verification passed. Artifacts verified the ESP32 target, 4 MB
flash and DIO/80 MHz settings; image checksums and hashes are valid. OTA 0 spans
`0x020000–0x200000` and OTA 1 spans `0x200000–0x3E0000`; end addresses are
exclusive.

**Remaining build warnings:** existing conflicting IRAM attributes on
`is_for_mgmt` remain. Generated CMake metadata contains conflicting 40 MHz and
single-app settings. **Use only the verified PlatformIO artifacts and flash
offsets for flashing; do not use the conflicting CMake flashing metadata.**

Hardware has not yet arrived and no hardware testing has been performed.
Physical flash capacity must be confirmed before flashing. A passing build and
artifact checks do not establish hardware validation or deployment readiness.

## Accepted limitations and outstanding improvements

- **Accepted limitation — complete NVS loss:** losing both configuration namespace
  and commissioning marker is indistinguishable from a new board, permitting
  automatic initial setup, which has no session deadline. Another NVS key cannot
  solve this; independent manufacturing/eFuse enrollment is not implemented.
  Legacy devices cannot recover evidence lost before migration.
- **Accepted limitation — provisioning HTTP without TLS:** Basic/header-key
  authentication operates inside the password-protected setup WLAN. Physical entry,
  a unique secret and bounded configured sessions reduce exposure but do not provide
  TLS transport protection. Serial/flash access remains a trust boundary.
- **Outstanding security improvements:** independent DNS provisioning, transactional
  input validation/failed-save recovery, valid masks/routes/ports, client-IP collision
  checks and DHCP exclusion guidance. MQTT currently uses `mqtt://`; TLS/trusted-time,
  broker ACLs and credential-storage policy need review. Secure boot and flash
  encryption are not claimed enabled.
- **Known reliability risks:** local watchdog signals cannot detect every silent
  upstream failure; additional queue/heartbeat/hung-task coverage is not established.
  RTC reboot budgets can reset on power loss. Telemetry/events may be dropped by
  design; memory/stack margins and shared-MAC address conflicts remain unqualified.

## Unverified hardware and remaining acceptance

On the purchased board, verify flash ID before flashing, power/regulation/isolation,
antenna/enclosure and GPIO14 electrical/hold/reset behavior. Exercise cold boot,
MAC cloning/relearning, shared-MAC IPv4/ARP demultiplexing, DHCP/DNS/broadcasts,
bidirectional Modbus TCP and idle operation. Scan normal-mode ports and capture
telemetry-stack traffic; test real browser authentication and secret persistence.

Inject broker/Wi-Fi/cable outages, driver faults and power loss; verify watchdog
cooldowns/reboot limits and settings-preserving recovery. Test OTA success,
interruption, expiry during active HTTP/upload, socket wakeup, flash cancellation/
commit, driver cleanup and bootloader rollback. Measure heap/stack under load and
complete a QE4 soak. These hardware-dependent guarantees remain unverified.
