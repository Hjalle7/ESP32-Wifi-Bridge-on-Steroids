# WT32-ETH01 / 4 MB: first hardware test

**Status: NOT HARDWARE-TESTED.** The board has been ordered, not received.
This is a bench acceptance procedure, not production deployment approval.
Source baseline: `12ddd23fd491252ee9c9edc97e1897d511ca664a` on `main`.
The earlier build/host evidence is recorded in
[security-review.md](security-review.md#verification-and-build-status); it does
not establish physical behavior. Record the exact firmware SHA actually tested.

Read [wt32-deployment.md](wt32-deployment.md) and
[local-recovery-and-access.md](local-recovery-and-access.md) for the security and
recovery policy. Only `wt32-eth01-4mb` is supported. Do not flash legacy 8 MB/C5
images, use CMake-generated flashing instructions, bypass TLS verification,
or connect the Qvantum QE4 during these initial tests.

## 1. Bench hardware and electrical checks

Required: WT32-ETH01, Mac, USB data cable, macOS-compatible **3.3 V logic**
USB-to-UART adapter, short jumpers, momentary ground jumpers/buttons for IO0,
EN and IO14, multimeter, regulated isolated bench supply, Ethernet cable,
2.4 GHz test AP/router with DHCP/DNS, and a disposable Ethernet client.
Use one client directly on the bridge, not a downstream multi-client switch.
For network tests use a second host on the AP LAN; a Mac with USB Ethernet
can be the bridged client. Advanced tests also need a test MQTT broker/Home
Assistant and a disposable Modbus TCP server/client pair.

Documentary board specifications are not measurements of the purchased unit:

| Item | Documentary evidence / bench decision |
| --- | --- |
| Power inputs | [Wireless-Tag board documentation](https://wiki.wireless-tag.com/docs/en/WT32-ETH01/board_features.html) specifies **5 V OR 3.3 V**, choose one input. Confirm revision, labels and polarity before power. |
| Supply capacity | The [WT32-ETH01 datasheet](https://www.tme.eu/Document/1503f6f34f86647f395694ec5f8ce17b/WT32-ETH01_datasheet_V1.3-en.pdf) specifies at least **500 mA** supply capability. Use regulated **5 V, at least 1 A capacity** at the confirmed 5 V input as bench headroom, not a measured consumption claim. Verify voltage during Wi-Fi bursts; average-current figures do not size a supply. |
| Serial/programming | ESP32 UART0 is TX=GPIO1, RX=GPIO3. Board revisions may label these TX0/RX0 or programming TXD/RXD. Other TXD/RXD pins can be UART2 GPIO17/GPIO5: do not confuse them. Confirm against the revision's pinout. |
| Ethernet | Source `src/bridge.cpp` selects LAN8720, PHY address 1, MDC=23, MDIO=18, PHY power/clock-enable=16, external RMII clock input GPIO0. These are firmware assumptions requiring board confirmation. |
| Flash / console | Required physical capacity: 4 MB; identify it below. Console expected from ESP-IDF defaults: UART0, 115200 baud, 8N1; PlatformIO monitor is explicitly 115200. Confirm effective generated Kconfig before connecting. |

Wire with all power disconnected:

| Adapter / control | Board signal |
| --- | --- |
| Adapter TX, 3.3 V logic | RX0 / GPIO3 |
| Adapter RX | TX0 / GPIO1 |
| Adapter GND and supply negative | GND (common reference) |
| Adapter VCC | **Leave disconnected**; use the separate supply |
| Regulated supply +5 V | Confirmed 5 V input only |
| Temporary BOOT jumper | IO0 to GND during reset into ROM downloader only |
| Temporary reset contact | EN to GND briefly, then release; EN is active high |
| Provisioning contact | IO14 to GND; firmware enables its internal pull-up |

Do not assume adapter VCC rating or a voltage selector establishes its TX logic
level. Never apply 5 V logic or RS-232 levels to GPIO, feed 5 V into 3V3, power
both supply inputs, or back-power an unpowered board through UART. Connect the
common ground before signals; keep loose contacts insulated and the antenna clear.
Do not assume RJ45 provides PoE or the QE4 supplies usable power/isolation.

Classic ESP32 strapping pins are GPIO0, 2, 5, 12 and 15; external loads can change
boot behavior. In particular, GPIO12 high at reset can select an incompatible
flash voltage. Leave unused straps alone; GPIO2 must be low/floating for UART
download. GPIO6–11 belong to flash. GPIO0 also carries the board's Ethernet
clock: **remove the BOOT ground before running firmware**. Never ground an
actively driven clock; enter download with EN held low first and confirm the
revision's GPIO16-controlled clock circuit. If it differs, stop and obtain its
schematic. IO14 is the setup input, not a boot strap or factory-reset pin.
Do not use the vendor AT firmware's CFG/reset instructions for this application.

## 2. macOS tools and identification

Commands below are instructions for the eventual operator; none has been run
against hardware. Install Apple's command-line tools if absent (`xcode-select
--install`), and Python 3.12 from python.org (or `brew install python@3.12` if
Homebrew is already used). No separate ESP-IDF, Arduino or global esptool install
is needed. With Python 3.12 available as `python3.12`:

```sh
git clone https://github.com/Hjalle7/ESP32-Wifi-Bridge-on-Steroids.git
cd ESP32-Wifi-Bridge-on-Steroids
git switch main
git pull --ff-only
git rev-parse HEAD
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install 'platformio==6.1.18' 'esptool==5.1.0'
pio --version
python -m esptool version
pio device list
ls /dev/cu.*
```

The two Python tools are isolated operator tooling, not repository dependencies;
do not commit `.venv` or logs. Compare ports before/after plugging in the adapter.
Install a vendor driver only if the adapter actually requires one. Set the real
port, not this example, in each terminal:

```sh
export PORT=/dev/cu.usbserial-REPLACE_ME
```

Close all serial monitors before esptool. Hold EN low, connect IO0 to ground,
then release EN. With manual wiring an esptool automatic reset may not work;
repeat the EN sequence when it prints `Connecting...`.

```sh
python -m esptool --chip esp32 --port "$PORT" --baud 115200 chip-id
python -m esptool --chip esp32 --port "$PORT" --baud 115200 flash-id
```

Record chip model/revision, MAC, JEDEC manufacturer/device ID and detected size.
**Stop unless it is a classic ESP32 and reports 4 MB**; an ESP32 chip identity
alone does not prove the PCB is WT32-ETH01. Photograph board/module markings
and match the revision's pinout. An unexpected capacity needs investigation,
not a changed image header. Re-enter download mode after automatic reset attempts.

Before replacing shipped firmware, make a private whole-flash backup:

```sh
mkdir -p work/hardware-test
python -m esptool --chip esp32 --port "$PORT" --baud 115200 read-flash 0 0x400000 work/hardware-test/before.bin
shasum -a 256 work/hardware-test/before.bin
```

Backups/logs may contain secrets. Store them privately, never attach them raw to
a public PR. A backup of encrypted/protected flash may not be restorable; stop
if security/protection errors appear rather than changing eFuses or forcing writes.

## 3. Build, verify, then first serial flash

Use the platform URL pinned in `platformio.ini` (55.03.34, ESP-IDF 5.5.1).
Do not substitute the legacy environments or update dependencies to fix setup.
If HTTPS fails, repair the local CA/proxy trust chain; never use `curl -k`,
`verify=False`, or disable PlatformIO TLS checks.

```sh
pio run -e wt32-eth01-4mb
python scripts/check_flash_layout.py wt32-eth01-4mb 4
export BUILD=.pio/build/wt32-eth01-4mb
python -m esptool --chip esp32 image-info "$BUILD/bootloader.bin"
python -m esptool --chip esp32 image-info "$BUILD/firmware.bin"
rg 'CONFIG_(IDF_TARGET=|ESPTOOLPY_FLASH|BOOTLOADER_APP_ROLLBACK_ENABLE|PARTITION_TABLE_OFFSET|ESP_CONSOLE_)' sdkconfig.wt32-eth01-4mb
shasum -a 256 "$BUILD/bootloader.bin" "$BUILD/partitions.bin" "$BUILD/firmware.bin"
```

If `rg` is unavailable use macOS `grep -E` for that read-only check.
Require ESP32 images, valid image checksums/hashes, **4 MB, DIO, 80 MHz** in both
headers, rollback enabled, partition table at `0x8000`, UART0/115200 console.
Inspect effective settings, including defaults omitted from `sdkconfig.defaults`.
The checker verifies size/fit/bounds, not every chip/mode/clock/console property.
Build size varies: use the current artifact, not the historical 977,296-byte size.

Verify the generated binary table against [partitions_4mb_ota.csv](../../partitions_4mb_ota.csv).
This standalone decoder uses no CMake flashing metadata:

```sh
python - <<'PY'
from pathlib import Path
import struct
p = Path('.pio/build/wt32-eth01-4mb/partitions.bin').read_bytes()
actual = []
for i in range(0, len(p), 32):
    if p[i:i+2] != b'\xaa\x50':
        break
    _, typ, sub, off, size, label, flags = struct.unpack('<HBBII16sI', p[i:i+32])
    label = label.split(b'\0')[0].decode()
    actual.append((label, typ, sub, off, size))
    print(label, hex(off), hex(size))
assert actual == [
    ('nvs', 1, 2, 0x9000, 0x6000),
    ('otadata', 1, 0, 0xf000, 0x2000),
    ('app0', 0, 0x10, 0x20000, 0x1e0000),
    ('app1', 0, 0x11, 0x200000, 0x1e0000),
    ('coredump', 1, 3, 0x3e0000, 0x10000)]
PY
```

Each app slot is 1,966,080 bytes. Flash ends at `0x400000`; final 64 KB is
unallocated. The first-install map is bootloader `0x1000`, partition table
`0x8000`, app0 `0x20000`. **Do not use `0x10000` for this application.**

For a new board, check that the future OTA metadata region in `before.bin` is
erased, so stale vendor metadata cannot select an old app1:

```sh
python - <<'PY'
from pathlib import Path
b = Path('work/hardware-test/before.bin').read_bytes()
assert len(b) == 0x400000
assert b[0xf000:0x11000] == b'\xff' * 0x2000, 'STOP: nonblank OTA metadata; plan migration first'
PY
```

If nonblank, stop and plan a backed-up first-install migration. An intentional
`erase-region 0xf000 0x2000` clears boot selection only, but must never be used
as a routine recovery/update step on an existing dual-slot installation. The
commands below deliberately do not initialize OTA metadata, erase NVS, or write
app1. They are for a first installation with the erased metadata check passed;
erased metadata makes the bootloader select OTA slot 0. An existing installation
requires an update/recovery plan that respects its active slot.

Close the monitor, enter ROM download again, then flash only checked artifacts:

```sh
python -m esptool --chip esp32 --port "$PORT" --baud 115200 write-flash \
  --flash-mode dio --flash-freq 80m --flash-size 4MB \
  0x1000 "$BUILD/bootloader.bin" \
  0x8000 "$BUILD/partitions.bin" \
  0x20000 "$BUILD/firmware.bin"
python -m esptool --chip esp32 --port "$PORT" --baud 115200 verify-flash \
  0x1000 "$BUILD/bootloader.bin" \
  0x8000 "$BUILD/partitions.bin" \
  0x20000 "$BUILD/firmware.bin"
```

Do not use `idf.py flash`, `flash_args`, `flasher_args.json`, CMake flash targets
or an unreviewed upload command. Generated CMake metadata is known to conflict
on clock and single-app settings. Preserve the matching ELF and artifact hashes.
Hold EN low, disconnect the IO0 ground, start the monitor, then release EN:

```sh
pio device monitor --environment wt32-eth01-4mb --port "$PORT" --baud 115200
```

Exit with Ctrl-C. Capture a private serial transcript including reset reason,
partition selection, firmware revision and setup messages. The AP password is
printed directly to serial as `[PORT] Local setup password: ...`; redact it.
If vendor NVS content prevents initial setup, use the recovery section, not an
automatic erase. No first-flash or runtime success is claimed by this guide.

## 4. Test setup and recording rules

Use a disposable isolated LAN. Agree its subnet, mask, gateway/DNS server,
DHCP pool and a unique excluded static ESP32 telemetry IP before provisioning.
The bridged client gets its **own DHCP IP**, distinct from the telemetry IP,
but both use the client's cloned MAC upstream. No NAT, WDS or second subnet.
Keep the test client's other interfaces off to avoid bypassing the bridge.
Keep the observing host on the AP LAN. On a Mac use `networksetup -listallhardwareports`
and `ifconfig` to identify interfaces; substitute actual interface/IP values below.

Current firmware has **no independent telemetry DNS setting**: `bridge.cpp`
sets DNS to the selected profile's gateway. Choose a test gateway that really
answers DNS; use a broker IP for the first MQTT check, then test a hostname.
DHCP DNS for the Ethernet client is a separate forwarded function.
The portal does not fully validate masks/routes/collisions or save transactionally;
do not test malformed settings on the basic path.

In every test: record start/end time, PASS/FAIL/NOT TESTED and observations in
the results sheet. PASS means all stated criteria were observed; any contrary
result is FAIL. Missing equipment/evidence is NOT TESTED. Basic tests precede
advanced tests; retain serial recovery and a known-good image throughout.

### Basic tests

1. **T01 — Cold boot.** Preconditions: verified serial image, stable supply,
   IO0/IO14 released. Procedure: remove power, restore it, capture serial for
   at least two minutes. Expected/PASS: sensible ESP32/4 MB boot and revision,
   no brownout/panic/reset loop; initial setup if genuinely unconfigured,
   otherwise normal startup (T04). Record voltage/reset reason. Observations: ___

2. **T02 — Automatic initial provisioning and authentication.** Preconditions:
   genuinely unconfigured NVS, no IO14 hold. Procedure: read the serial secret,
   join the advertised `<name>-setup-XXXX` AP on Mac, stay connected despite
   its lack of Internet, open `http://192.168.4.1`. Login is `admin` with saved
   admin password, or the unique 32-character AP secret if none is saved.
   Try unauthenticated `curl -i http://192.168.4.1/api/status` and a wrong
   password in a private browser window before correct login. Expected/PASS:
   automatic AP, HTTP 401 for absent/wrong credentials, authenticated access,
   no shared fallback password. Every registered route has the same gate;
   check root, config, scan and diagnostics, and an **unauthenticated** POST
   to `/api/config` with empty body (401, no change). An authenticated request
   with a different Origin must return 403. Setup HTTP is not TLS. Initial
   setup has no idle/absolute deadline; do not infer configured-session behavior.
   Observations (no secrets): ___

3. **T03 — Wi-Fi, static IP and persistence.** Preconditions: T02 and planned
   valid LAN settings. Procedure: scan/select or manually enter a 2.4 GHz SSID,
   password, telemetry IP/mask/gateway and profile 1; leave tuning at defaults.
   Set a private admin password and optional test broker settings. Use **Save
   & reboot** (hold/release control). Plain Save only persists; the API does
   not automatically reboot. Connect the Ethernet test client and force a
   DHCP renewal/frame during startup. Expected/PASS: Wi-Fi association with
   learned client MAC, telemetry IP from the plan, no address collision;
   after power cycle, association/settings still work. Verify saved non-secret
   values and blank password fields later via physical setup. Empty password
   fields mean unchanged, not cleared. Observations: ___

4. **T04 — Normal reboot / idle client.** Preconditions: configured board and
   learned client MAC. Procedure: reboot bridge only, first with active client,
   then quiet client. Expected/PASS: sniff learns/persists a changed MAC or
   reuses stored MAC after up to 30 s; no setup AP/portal. With no stored MAC,
   initial sniff is 60 s then it keeps waiting with GPIO polling—silence is
   not a reason to open setup. Repeat with client sending DHCP after waiting.
   Allow configured association retries (default 20 s × 3 per SSID) before
   classifying delayed startup. Observations: ___

5. **T05 — No normal-mode HTTP/OTA.** Preconditions: T04, observer on AP LAN,
   actual telemetry IP in `TELEMETRY_IP`. Procedure: run
   `curl --connect-timeout 3 --max-time 5 -i "http://$TELEMETRY_IP/"` and the
   same GET to `/api/status`, `/api/config`, `/api/update`. Expected/PASS:
   connection fails/times out, no HTTP response or login challenge; no setup
   AP. A 401 still proves an unwanted HTTP listener. Optional full TCP scan
   with an already installed scanner extends evidence; these checks prove
   only the tested addresses/ports, not an outbound-only firewall. Do not
   scan the client IP by mistake. Observations: ___

6. **T06 — Physical authorization.** Preconditions: configured normal mode.
   Procedure: IO14-to-GND under 3 s then release; repeat for at least 3 s
   and release. Then test a deliberate boot-time hold of at least 3 s.
   Expected/PASS: short press ignored; runtime hold/release causes planned
   setup reboot; boot hold enters setup. Saved configuration remains, AP
   secret is unchanged, next-session admin password works. Bridging is not
   attempted in provisioning. Release IO14 after entry. Observations: ___

7. **T07 — Non-destructive changes.** Preconditions: T06, private record of
   settings/credentials. Procedure: change only telemetry interval with plain
   Save, keep password fields blank; reboot via portal. Re-enter setup and
   compare settings, then reboot normally. Expected/PASS: changed interval
   persists; Wi-Fi/MQTT/admin credentials, static IP and learned MAC retained;
   no reset of configuration. Do not interpret password omission in GET
   `/api/config` as data loss. Restore interval. Observations: ___

8. **T08 — Inactivity expiry.** Preconditions: configured setup on an already
   validated image. Procedure: leave default idle timeout 0 (=900 s), reboot
   into a fresh authorized session; stop page reloads/config reads/scans/saves.
   Leave status polling only, or close browser. Expected/PASS: about 15 min
   after last real activity, admission closes, AP stops and board reboots
   normally without losing settings. Status polls do not extend inactivity.
   Record times; cleanup can delay final shutdown. Observations: ___

9. **T09 — Absolute configured-session deadline.** Preconditions: configured,
   validated image, fresh physical session, IO14 released. Procedure: record
   entry time; reload authenticated `/` every five minutes so inactivity
   cannot expire first. Continue beyond 30 min. Repeat with IO14 held across
   expiry, then release and deliberately hold again. Expected/PASS: entry's
   fixed 30-minute deadline denies new requests despite activity, cancels
   uploads if present, then reboots after cleanup. A continuously held pin
   cannot authorize another session; a fresh gesture can. No erase. Do not
   expect this deadline on first-ever unconfigured setup. Observations: ___

10. **T10 — Ethernet ↔ Wi-Fi forwarding.** Preconditions: T04, one wired client
    and observer on AP LAN. Procedure: ping each host from the other and copy
    a test file in both directions: on each host, put a disposable file in a
    dedicated empty directory and run `python3 -m http.server 8000 --bind 0.0.0.0`
    there. From the opposite host run `curl --fail --max-time 30
    http://PEER_IP:8000/test.bin -o received.bin`; compare `shasum -a 256` with
    the sender's file. Stop both servers with Ctrl-C. Expected/PASS: bidirectional delivery,
    matching hashes, client remains in existing subnet, no NAT. Use modest
    load first; throughput requirements are not established. Observations: ___

11. **T11 — MAC cloning / ARP / replacement.** Preconditions: T10 and access
    to AP association/DHCP tables. Procedure: record client MAC, compare AP
    station MAC and serial learned MAC. On observing Mac, ping both client
    and telemetry IP, inspect `arp -an`; capture ARP while alternating client
    traffic with MQTT. Reboot with same client idle; then replace with another
    disposable client, reboot and generate frames within sniff window.
    Expected/PASS: two distinct IPs resolve to the same current client MAC;
    telemetry replies and client frames reach their respective stacks; new
    MAC is persisted/reassociated, both paths recover. No duplicate addresses
    or stale association. This is shared-MAC acceptance, not an assumption
    that two successful pings suffice. Observations: ___

12. **T12 — DHCP, DNS and broadcast.** Preconditions: DHCP/DNS test LAN,
    actual wired interface in `CLIENT_IF`, observer interface in `LAN_IF`.
    Procedure: renew client DHCP (Mac: `sudo ipconfig set "$CLIENT_IF" DHCP`),
    inspect `ipconfig getpacket "$CLIENT_IF"`; resolve a known test DNS name
    through its supplied server (`dig @SERVER NAME`). On observer capture
    `sudo tcpdump -ni "$LAN_IF" 'arp or (udp and (port 67 or port 68 or port 53))'`.
    Capture UDP port 50001 on the opposite endpoint. Send a test broadcast
    with the command below, substituting the actual subnet broadcast, then
    repeat from the other host (Python 3 required on each sender):

    ```sh
    python3 - <<'PY'
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(b'WT32 bench broadcast', ('REPLACE_WITH_SUBNET_BROADCAST', 50001))
    s.close()
    PY
    ```

    Expected/PASS: DHCP exchange through
    bridge with correct lease/subnet/DNS; DNS query/reply and broadcasts cross
    both directions. Compare a direct-cable baseline if AP broadcast policy
    interferes; do not classify network filtering as proof of bridge success.
    Observations: ___

13. **T13 — Bidirectional Modbus TCP.** Preconditions: disposable Modbus TCP
    simulator on wired client, observer with known working Modbus client;
    record tool versions, unit ID, port and seeded holding-register address/value.
    Procedure: first prove direct-LAN operation, then read that register through
    bridge 100 times including an idle interval. On this simulator only, write
    a known harmless value and read it back. Swap server/client roles and repeat.
    Expected/PASS: requests and responses work in both placements, correct data,
    no unexplained timeout/reset compared with baseline. TCP port 502 handshake
    alone is insufficient. No QE4 or real control registers. Observations: ___

14. **T14 — MQTT / Home Assistant.** Preconditions: isolated broker, dedicated
    least-privilege test credentials and HA MQTT integration. Procedure: configure
    broker IP/port/credentials via GPIO setup; save/reboot. Observe broker logs
    and HA discovery. Node ID is last three bytes of cloned MAC in lowercase
    hex: `bridge/<node>/state`, `/availability`, `/watchdog`; discovery under
    `homeassistant/`. Expected/PASS: availability online, periodic JSON RSSI,
    uptime/link/reconnect/recovery fields and HA entities; only outbound telemetry,
    no command subscription. Repeat with resolvable broker hostname to exercise
    telemetry DNS via gateway. Plain `mqtt://` is current behavior; TLS/secure
    boot/flash encryption are not claimed. Observations: ___

15. **T15 — Broker outage / recovery.** Preconditions: T14 plus continuous
    client transfer/Modbus probes. Procedure: stop only test broker for five
    minutes, restore it. Expected/PASS: bridging continues without reset/setup;
    reconnect/discovery and state resume, bounded drops allowed, no command
    service appears. LWT/HA offline timing follows broker keepalive rather than
    immediate power-cut notification. Record probe gaps/counters. Observations: ___

16. **T16 — Wi-Fi loss / recovery.** Preconditions: configured board with serial
    capture. Procedure: disable test AP for five minutes, restore same SSID.
    Expected/PASS: interrupted traffic while disconnected, paced association
    retries (normal-mode retry at most once per 5 s), eventual recovery after
    AP returns; outage alone causes no recovery reboot, setup AP or erase.
    Repeat a boot with wrong test credentials, then repair via IO14; no automatic
    provisioning authorization. Observations: ___

17. **T17 — Cable loss / recovery.** Preconditions: T10 and serial/MQTT capture.
    Procedure: unplug Ethernet five minutes, reconnect and renew client traffic.
    Expected/PASS: Ethernet link state changes, no watchdog reboot/setup for
    cable loss or idle traffic, forwarding returns with settings intact. Broker
    outage and unplugged client are independent conditions. Observations: ___

### Advanced / fault-injection tests

Use a spare bench board, known-good backup/image and stable power. Do not change
firmware or enable diagnostic builds as part of this documentation task. Abort
on unexpected heating, voltage sag or repeated resets; preserve logs before repair.

18. **T18 — Optional local watchdog.** Preconditions: T10–17 pass; watchdog is
    off by default. Procedure: enable it via setup, record action mask and bad
    windows (0 defaults to all actions / 3 windows), save/reboot; repeat idle,
    cable and broker/AP outages for at least five minutes each under captures.
    Expected/PASS for these negative controls: no fault-driven reboot/setup.
    Positive escalation requires a controlled real driver-failure fixture,
    not arbitrary traffic loss or gateway ping blocking; if unavailable record
    that portion NOT TESTED. Expected with qualifying driver errors: 20 s
    windows, at least 200 attempts and >=15% failures, consecutive bad windows,
    actions >=60 s apart; Ethernet TX can reset Ethernet first, Wi-Fi TX causes
    reconnect, persistent errors can escalate to reboot. At most two recovery
    reboots per retained RTC budget, restored after ten healthy minutes; power
    loss can reset budget. Intentional cap/throttle/offline drops are excluded.
    No claim of detecting every silent upstream/hung-task fault. Restore setting.
    Observations, including untested escalation: ___

19. **T19 — Provisioning-only OTA.** Preconditions: validated known-good slot,
    current 4 MB table, backup and serial recovery. Build/check the candidate
    exactly as section 3, archive ELF/hashes/SHA, enter GPIO setup and join AP.
    Procedure: upload **firmware.bin only**, never table/bootloader. With browser
    authentication, use the portal Firmware update upload; alternatively curl
    prompts for the current HTTP password (keeps it out of shell history):

    ```sh
    curl --fail-with-body --max-time 180 --user admin \
      --data-binary @.pio/build/wt32-eth01-4mb/firmware.bin \
      http://192.168.4.1/api/update
    ```

    Release IO14 before automatic reboot; reconnect the client/AP. Expected/PASS:
    inactive slot targeted, upload accepted, normal reboot with correct revision,
    then `[OTA ] New firmware confirmed, no rollback` after 30 continuous
    seconds of active bridge + Wi-Fi association + Ethernet link. MQTT/client
    traffic are not confirmation requirements. Three-minute validation window
    starts after blocking startup, not upload or reset time. Configured setup
    cannot confirm; unconfigured initial setup can. Prove end-to-end forwarding
    independently afterward and repeat cold boot. Identical image upload can
    test slot handling, but cannot distinguish revisions: record slot/boot logs.
    Observations: ___

20. **T20 — Interrupted OTA / rollback / expiry.** Preconditions: T19 has left
    a validated fallback; preserve its hashes and serial boot-slot evidence.
    Procedure: (a) rate-limit a new upload with curl `--limit-rate 4k`, Ctrl-C
    well before completion, then reboot normally; (b) complete an upload,
    disconnect Ethernet before candidate boot, keep link absent past the
    three-minute window after startup, then restore it after rollback;
    (c) start a slow upload shortly before configured setup's absolute deadline,
    maintaining authenticated page activity beforehand to avoid idle expiry.
    Expected/PASS: (a) incomplete image is not selected; old image remains usable;
    (b) unconfirmed image rolls back to previous validated slot, settings retained;
    (c) admission ends, receiver wakes/cancels and flash cleanup completes before
    reboot, no expired upload selects a new boot slot. Capture boot slots and
    validation logs, not just identical version strings. Optional power cut during
    upload is a separate repeat with serial recovery ready; metadata/flash power
    failure behavior is unverified. If no valid fallback exists, do not promise
    rollback—recover serially. Observations: ___

21. **T21 — Power interruption / persistence.** Preconditions: T03–20, private
    record of saved settings and secret, no active write. Procedure: save a valid
    interval change, wait for success, reboot, cut/restore supply five times;
    re-enter setup and compare settings and secret. Expected/PASS: normal boot,
    Wi-Fi/static IP/MQTT/admin settings and AP secret persist, no spontaneous setup.
    Advanced separate run: interrupt a disposable configuration save; record last
    or new valid state, storage errors and recovery. Transactional application
    updates are not guaranteed; any corruption is FAIL, not a promised atomic
    outcome. Missing commissioned config must fail closed while marker survives;
    NVS init failure must not automatically erase/open setup. Total NVS loss can
    resemble a new board (accepted limitation). Do not intentionally corrupt NVS
    on the only board or count an unperformed fault as PASS. Observations: ___

## 5. Recovery ladder

Preserve serial logs, reset reason, SHA and available authenticated diagnostics
before changing anything. Never use factory erase as the first recovery step.

| Symptom | Non-destructive action first | Limit / escalation |
| --- | --- | --- |
| Flash connection/write failure | Close monitor; check crossed UART0 wires, common ground, 3.3 V logic, independent supply, IO0/EN sequence and 115200 baud. Retry verified artifacts. | Do not raise voltage, force chip/security overrides or substitute legacy layouts. Interrupted first install needs completed serial flash; it has no guaranteed fallback. |
| Boot loop | Remove IO0 ground with EN low, verify power/straps, capture boot log; restore known-good matching app using appropriate slot/update plan. | First-install command writes app0 only and is not a universal recovery for app1 selected by OTA metadata. Preserve table/NVS and inspect selected slot first. |
| Wrong SSID/password or inaccessible telemetry IP | Boot with IO14 low >=3 s, release, join setup AP using serial AP secret, authenticate and correct valid settings, Save & reboot. | Faults never authorize setup automatically. Boot hold avoids waiting through sniff/association. |
| Lost setup access | Release/re-hold IO14 for fresh authorization, reset into deliberate boot hold, reread serial AP secret; retry HTTP with the saved admin password if set. | AP secret does not override a separately saved admin password. Recover a forgotten admin credential from private records/backup; no universal bypass is implemented. |
| Failed OTA | Keep power stable, collect logs, allow pending-image deadline/rollback with valid fallback; then physically provision and retry verified image. | If no bootable fallback, use ROM serial recovery with known layout/active slot. Do not erase NVS to repair an app image. |
| Invalid/missing configuration | Try physically authorized setup if NVS remains readable, re-enter known-good settings. Back up flash before any repair. | NVS initialization failure leaves management disabled and requires local serial repair. Missing commissioned config is fail-closed; there is no automatic erase. Save failure can leave RAM changed; reboot/recheck persisted data. |

**Last resort: intentional factory erase**, only after diagnosis, private backup
and acceptance that all settings, learned MAC, AP secret, commissioning marker,
OTA images/metadata and crash records will be lost. ROM download must be working.
This is separate from GPIO14 provisioning. There is no factory-reset HTTP route.

```sh
# DESTRUCTIVE: entire chip. Do not use for ordinary credential/link recovery.
python -m esptool --chip esp32 --port "$PORT" --baud 115200 erase-flash
```

Then repeat identification, verified first-install flashing and provisioning.
Capture the newly generated serial AP secret; the previous password is invalid.
If a protected/unreadable chip prevents this, stop and investigate; do not burn
eFuses or disable protection. Partial/manual NVS editing is not a supported
credential-recovery procedure in this guide.

## 6. Results sheet

Copy per board/firmware run. Shared fields below apply to every row; use a new
sheet if firmware, board or flash identity changes. Attach only redacted evidence.

| Firmware commit SHA | Board identification / revision / chip MAC | Detected flash size + JEDEC ID | Test date (with timezone) |
| --- | --- | --- | --- |
| ___ | ___ | ___ | ___ |

Supply/adapter: ___; LAN/AP and client/tool versions: ___; artifact hashes: ___

| ID | Description | PASS / FAIL / NOT TESTED | Notes / evidence |
| --- | --- | --- | --- |
| T01 | Cold boot | NOT TESTED | |
| T02 | Initial setup/authentication | NOT TESTED | |
| T03 | Wi-Fi/static IP/persistence | NOT TESTED | |
| T04 | Normal reboot/idle | NOT TESTED | |
| T05 | No normal HTTP/OTA | NOT TESTED | |
| T06 | GPIO14 authorization | NOT TESTED | |
| T07 | Non-destructive changes | NOT TESTED | |
| T08 | Inactivity expiry | NOT TESTED | |
| T09 | Absolute 30-minute deadline | NOT TESTED | |
| T10 | Forwarding | NOT TESTED | |
| T11 | MAC/ARP/replacement | NOT TESTED | |
| T12 | DHCP/DNS/broadcast | NOT TESTED | |
| T13 | Bidirectional Modbus | NOT TESTED | |
| T14 | MQTT/HA | NOT TESTED | |
| T15 | Broker outage/recovery | NOT TESTED | |
| T16 | Wi-Fi loss/recovery | NOT TESTED | |
| T17 | Cable loss/recovery | NOT TESTED | |
| T18 | Watchdog controls/escalation | NOT TESTED | Record each subcase |
| T19 | OTA confirmation | NOT TESTED | |
| T20 | Interrupted OTA/rollback/expiry | NOT TESTED | Record each subcase |
| T21 | Power/settings persistence | NOT TESTED | Record each subcase |

## 7. Source/documentation caveats

- `AGENTS.md` still has historical unresolved/checklist items. Current source and
  the security review show 4 MB/provisioning/watchdog/OTA work merged; those notes
  are not proof of missing implementation or hardware acceptance.
- The `main.cpp` operating-mode summary says saving triggers reboot; the actual configuration
  handler saves only, and the browser's **Save & reboot** separately calls reboot.
- `config.h` describes an empty admin password as unprotected, and a `web.cpp`
  configuration-handler comment says unauthenticated. Actual route dispatch
  authenticates every registered route, falling back to the unique AP secret.
  Some embedded UI text still suggests automatic portal fallback or ping-based
  profile selection; configured faults remain normal/inactive and IP profile
  selection is explicit. Follow the tested source behavior above.
- Independent telemetry DNS is outstanding, despite requirements listing DNS
  provisioning. Gateway-as-DNS is implemented; test that limitation explicitly.
- `scripts/ota_flash.sh` hardcodes `$HOME/.pio-py313/bin/pio` and does not run the
  layout checker. The portable, separately verified upload above avoids relying
  on that workstation path. Do not change the helper in this documentation task.
- Existing layout checks do not validate every flashing parameter; CMake metadata
  conflicts remain as recorded in the security review. The explicit first-flash
  map above and artifact inspection are essential. Historical build sizes in
  older documents differ; they are not current acceptance measurements.

Still requiring physical confirmation: purchased PCB/pinout and flash identity,
power/regulation/isolation/current transients, GPIO0 clock/strap and IO14/reset
behavior, RF/antenna/enclosure performance, real HTTP/socket expiry and OTA
rollback, shared-MAC networking, load/heap/stack margins and sustained stability.
Bench passes should precede a separately planned QE4 integration/soak; they do
not establish production readiness.
