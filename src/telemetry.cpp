/*
 * telemetry.cpp - MQTT connection including Home Assistant autodiscovery
 *
 * Only runs once the management netif has an IP. The MQTT client uses the
 * same lwIP stack that the selective delivery in bridge.cpp feeds with
 * packets.
 *
 * Topics (<node> = last three bytes of the STA MAC, hex):
 *   bridge/<node>/state         periodic JSON state
 *   bridge/<node>/availability  "online" / "offline" (last will)
 *   bridge/<node>/watchdog      discrete watchdog events
 *   homeassistant/...           retained discovery entries
 */

#include "telemetry.h"
#include "config.h"
#include "bridge.h"

#include <string.h>
#include <atomic>
#include "freertos/queue.h"

#include "mqtt_client.h"
#include "esp_wifi.h"

static esp_mqtt_client_handle_t s_mqtt = NULL;
static std::atomic<bool> s_connected{false};
static std::atomic<uint32_t> s_generation{0};
/* Four pending messages plus a bounded MQTT outbox limit outage memory use.
 * Producers copy messages without waiting; only the worker touches sockets. */
struct TelemetryMessage {
  char topic[160];
  char payload[640];
  int qos;
  int retain;
  uint32_t generation;
};
static QueueHandle_t s_queue = nullptr;
static bool s_publish_ok = true;  /* worker-owned discovery batch result */
static std::atomic<uint32_t> s_queue_drops{0};
static char  s_node[16]   = "bridge";
static char  s_base[48];
static char  s_avail[64];
static char  s_state[64];

/* MQTT event handler: tracks the connection state, publishes "online" on
 * connect and schedules a fresh discovery announcement after a reconnect. */
static void mqtt_evt(void *arg, esp_event_base_t base, int32_t id, void *data) {
  (void)arg; (void)base;
  esp_mqtt_event_handle_t e = (esp_mqtt_event_handle_t)data;

  switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
      s_connected = true;
      printf("[MQTT] Connected\n");
      ++s_generation;
      break;
    case MQTT_EVENT_DISCONNECTED:
      s_connected = false;

      printf("[MQTT] Disconnected\n");
      break;
    default:
      (void)e;
      break;
  }
}

/* Nonblocking producer boundary. Offline/full queues lose telemetry rather
 * than delaying forwarding or watchdog recovery. Payloads must fit exactly. */
static void queue_publish(const char *topic, const char *payload, int qos, int retain) {
  if (!s_queue || !s_connected.load()) return;
  TelemetryMessage message = {};
  if (strlen(topic) >= sizeof(message.topic) || strlen(payload) >= sizeof(message.payload)) {
    ++s_queue_drops;
    return;
  }
  strcpy(message.topic, topic);
  strcpy(message.payload, payload);
  message.qos = qos; message.retain = retain;
  message.generation = s_generation.load();
  if (xQueueSend(s_queue, &message, 0) != pdTRUE) ++s_queue_drops;
}

/* Worker-only network operation. Outbox exhaustion is a telemetry failure,
 * never a request for bridge recovery; discovery retries are paced. */
static void worker_publish(const char *topic, const char *payload, int qos, int retain) {
  if (!s_connected.load() || esp_mqtt_client_publish(s_mqtt, topic, payload, 0, qos, retain) < 0)
    s_publish_ok = false;
}

static size_t s_discovery_cursor = 0, s_discovery_index = 0;

/* Resume a failed discovery batch at its first unsent item. Replaying the
 * prefix would starve later entries when broker ACKs slowly free outbox space. */
static void discovery_publish(const char *topic, const char *payload, int qos, int retain) {
  if (s_discovery_index++ != s_discovery_cursor) return;
  worker_publish(topic, payload, qos, retain);
  if (s_publish_ok) ++s_discovery_cursor;
}

/* Publish one Home Assistant sensor discovery entry (retained). `key` is the
 * field in the state JSON; unit/devclass/stateclass/icon are optional (NULL).
 * Kept short so everything fits into one buffer. */
static void announce_one(const char *key, const char *name, const char *unit,
                         const char *devclass, const char *stateclass,
                         const char *icon) {
  char topic[160];
  snprintf(topic, sizeof(topic),
           "homeassistant/sensor/bridge_%s/%s/config", s_node, key);

  char extra[160] = "";
  size_t o = 0;
  if (unit)       o += snprintf(extra + o, sizeof(extra) - o, ",\"unit_of_measurement\":\"%s\"", unit);
  if (devclass)   o += snprintf(extra + o, sizeof(extra) - o, ",\"device_class\":\"%s\"", devclass);
  if (stateclass) o += snprintf(extra + o, sizeof(extra) - o, ",\"state_class\":\"%s\"", stateclass);
  if (icon)       o += snprintf(extra + o, sizeof(extra) - o, ",\"icon\":\"%s\"", icon);

  char payload[640];
  snprintf(payload, sizeof(payload),
    "{\"name\":\"%s\",\"uniq_id\":\"bridge_%s_%s\","
    "\"stat_t\":\"%s\",\"avty_t\":\"%s\","
    "\"val_tpl\":\"{{ value_json.%s }}\"%s,"
    "\"dev\":{\"ids\":[\"bridge_%s\"],\"name\":\"%s\","
    "\"mf\":\"DIY\",\"mdl\":\"WT32-ETH01 L2 Bridge\"}}",
    name, s_node, key, s_state, s_avail, key, extra, s_node, g_cfg.name);

  discovery_publish(topic, payload, 1, 1);
}

/* Publish all discovery entries (sensors plus the Ethernet link binary
 * sensor). Called on the first telemetry tick after each (re)connect. */
static void announce_all(void) {
  announce_one("rssi",     "Signal strength",     "dBm", "signal_strength", "measurement", NULL);
  announce_one("ch",       "Wi-Fi channel",       NULL,  NULL, NULL, "mdi:wifi");
  announce_one("kbps_up",  "Throughput LAN to Wi-Fi", "kbit/s", "data_rate", "measurement", NULL);
  announce_one("kbps_down","Throughput Wi-Fi to LAN", "kbit/s", "data_rate", "measurement", NULL);
  announce_one("drop_up",  "Dropped LAN to Wi-Fi", "pkt", NULL, "total_increasing", "mdi:alert");
  announce_one("drop_down","Dropped Wi-Fi to LAN", "pkt", NULL, "total_increasing", "mdi:alert");
  announce_one("uptime",   "Uptime",              "s",   "duration", "total_increasing", NULL);
  announce_one("heap",     "Free heap",           "B",   NULL, "measurement", "mdi:memory");
  /* IP of the bridged device. For a camera without its own display this is
   * often the only way to find out under which address it is reachable - the
   * bridge sees it in the data path anyway. */
  announce_one("client_ip","Client IP",           NULL,  NULL, NULL, "mdi:ip-network");
  /* Increase with every watchdog escalation (Ethernet or Wi-Fi level) - the
   * trend is the signal, not the absolute value. The forced reboot (highest
   * level) is NOT visible here separately - telemetry_note_watchdog_event()
   * and the coredump cover that. */
  announce_one("wd_reconnects","Watchdog Wi-Fi reconnects",NULL, NULL, "total_increasing", "mdi:wifi-refresh");
  announce_one("wd_eth_resets","Watchdog Ethernet resets",NULL, NULL, "total_increasing", "mdi:lan-connect");
  announce_one("roam_count","Active AP switches",NULL, NULL, "total_increasing", "mdi:wifi-arrow-left-right");
  /* All Wi-Fi disconnects since boot and the reason of the last one - the
   * history with RSSI/AP/duration is available at /api/disconnects. */
  announce_one("wifi_disc","Wi-Fi disconnects total",NULL, NULL, "total_increasing", "mdi:wifi-off");
  /* Only real drops of an existing connection, without the failed attempts
   * that follow - this is the meaningful curve. */
  announce_one("wifi_kicks","Wi-Fi drops",NULL, NULL, "total_increasing", "mdi:wifi-alert");
  announce_one("disc_reason","Last drop reason",NULL, NULL, NULL, "mdi:wifi-alert");
  /* Uplink health: how long frames wait in the driver's TX queue (rises long
   * before frames get lost) and frames the MAC gave up on, on the air. */
  announce_one("txq_ms",   "TX queue delay",      "ms",  "duration", "measurement", NULL);
  announce_one("air_fail", "Frames lost on air",  NULL,  NULL, "total_increasing", "mdi:wifi-strength-alert-outline");

  char topic[160], payload[512];
  snprintf(topic, sizeof(topic),
           "homeassistant/binary_sensor/bridge_%s/eth/config", s_node);
  snprintf(payload, sizeof(payload),
    "{\"name\":\"Ethernet link\",\"uniq_id\":\"bridge_%s_eth\","
    "\"stat_t\":\"%s\",\"avty_t\":\"%s\","
    "\"val_tpl\":\"{{ 'ON' if value_json.eth == 1 else 'OFF' }}\","
    "\"dev_cla\":\"connectivity\","
    "\"dev\":{\"ids\":[\"bridge_%s\"],\"name\":\"%s\"}}",
    s_node, s_state, s_avail, s_node, g_cfg.name);
  discovery_publish(topic, payload, 1, 1);

  if (s_publish_ok) printf("[MQTT] Discovery sent\n");
}

/* Own all socket-facing publishing. Reconnect generation ensures a fresh
 * retained discovery/availability batch after each connection. Events queued
 * before an outage are discarded, and recovery never waits for their ACKs. */
static void telemetry_worker(void *) {
  uint32_t announced_generation = 0, cursor_generation = 0;
  bool availability_sent = false;
  uint32_t last_discovery = 0;
  bool attempted = false;
  TelemetryMessage message;
  for (;;) {
    const uint32_t generation = s_generation.load();
    if (s_connected.load() && generation != announced_generation &&
        (!attempted || millis() - last_discovery >= 5000u)) {
      attempted = true; last_discovery = millis(); s_publish_ok = true;
      if (cursor_generation != generation) {
        cursor_generation = generation;
        s_discovery_cursor = 0;
        availability_sent = false;
      }
      if (!availability_sent) {
        worker_publish(s_avail, "online", 1, 1);
        availability_sent = s_publish_ok;
      }
      if (s_publish_ok) { s_discovery_index = 0; announce_all(); }
      if (s_publish_ok) announced_generation = generation;
    }
    if (xQueueReceive(s_queue, &message, pdMS_TO_TICKS(200)) == pdTRUE && s_connected.load() &&
        message.generation == s_generation.load())
      worker_publish(message.topic, message.payload, message.qos, message.retain);
  }
}

/* See telemetry.h. Derives the node id and topics from the STA MAC (= the
 * cloned client MAC), configures the last will on the availability topic and
 * starts the client asynchronously. */
bool telemetry_start(void) {
  if (g_cfg.mqtt_host[0] == '\0') {
    printf("[MQTT] No broker configured - skipped\n");
    return false;
  }

  uint8_t mac[6];
  esp_wifi_get_mac(WIFI_IF_STA, mac);
  snprintf(s_node, sizeof(s_node), "%02x%02x%02x", mac[3], mac[4], mac[5]);
  snprintf(s_base,  sizeof(s_base),  "bridge/%s", s_node);
  snprintf(s_state, sizeof(s_state), "%s/state", s_base);
  snprintf(s_avail, sizeof(s_avail), "%s/availability", s_base);

  char uri[96];
  snprintf(uri, sizeof(uri), "mqtt://%s:%u", g_cfg.mqtt_host, g_cfg.mqtt_port);

  esp_mqtt_client_config_t cfg = {};
  cfg.broker.address.uri              = uri;
  cfg.credentials.client_id           = s_node;
  cfg.session.last_will.topic         = s_avail;
  cfg.session.last_will.msg           = "offline";
  cfg.session.last_will.qos           = 1;
  cfg.session.last_will.retain        = 1;
  cfg.session.keepalive               = 30;
  cfg.network.timeout_ms             = 1000;
  cfg.network.reconnect_timeout_ms   = 5000;
  cfg.outbox.limit                   = 8192;
  if (g_cfg.mqtt_user[0]) {
    cfg.credentials.username                 = g_cfg.mqtt_user;
    cfg.credentials.authentication.password  = g_cfg.mqtt_pass;
  }

  s_queue = xQueueCreate(4, sizeof(TelemetryMessage));
  if (!s_queue) return false;
  s_mqtt = esp_mqtt_client_init(&cfg);
  if (!s_mqtt) {
    vQueueDelete(s_queue); s_queue = nullptr;
    printf("[MQTT] Init failed\n"); return false;
  }

  esp_mqtt_client_register_event(s_mqtt, MQTT_EVENT_ANY, mqtt_evt, NULL);
  if (esp_mqtt_client_start(s_mqtt) != ESP_OK) {
    esp_mqtt_client_destroy(s_mqtt); s_mqtt = nullptr;
    vQueueDelete(s_queue); s_queue = nullptr;
    return false;
  }
  if (xTaskCreate(telemetry_worker, "telemetry", 6144, nullptr, 1, nullptr) != pdPASS) {
    esp_mqtt_client_stop(s_mqtt); esp_mqtt_client_destroy(s_mqtt);
    s_mqtt = nullptr; s_connected = false;
    vQueueDelete(s_queue); s_queue = nullptr;
    return false;
  }
  printf("[MQTT] Connecting to %s\n", uri);
  return true;
}

/* See telemetry.h. Format and queue state without any socket operations.
 * Discovery and network waits belong exclusively to the publishing worker. */
void telemetry_tick(void) {
  if (!s_mqtt || !s_connected) return;

  static uint32_t last = 0;
  const uint32_t interval = (uint32_t)g_cfg.telemetry_s * 1000UL;
  if (millis() - last < interval) return;
  last = millis();


  BridgeStats st;
  bridge_get_stats(&st);

  char payload[600];
  snprintf(payload, sizeof(payload),
    "{\"rssi\":%d,\"ch\":%u,\"kbps_up\":%lu,\"kbps_down\":%lu,"
    "\"pkt_up\":%lu,\"pkt_down\":%lu,\"drop_up\":%lu,\"drop_down\":%lu,"
    "\"wifi_disc\":%lu,\"wifi_kicks\":%lu,\"disc_reason\":\"%s\","
    "\"wd_reconnects\":%lu,\"wd_eth_resets\":%lu,\"roam_count\":%lu,"
    "\"telemetry_drops\":%lu,\"eth\":%d,\"uptime\":%lu,\"heap\":%lu,\"bssid\":\"%s\","
    "\"client_ip\":\"%s\",\"txq_ms\":%lu,\"air_fail\":%lu}",
    (int)st.rssi, (unsigned)st.channel,
    (unsigned long)st.kbps_eth2wifi, (unsigned long)st.kbps_wifi2eth,
    (unsigned long)st.pkt_eth2wifi,  (unsigned long)st.pkt_wifi2eth,
    (unsigned long)st.drop_eth2wifi, (unsigned long)st.drop_wifi2eth,
    (unsigned long)st.wifi_disc_count, (unsigned long)st.wifi_kicks,
    st.disc_last_reason ? bridge_wifi_reason_str(st.disc_last_reason) : "-",
    (unsigned long)st.wd_reconnects, (unsigned long)st.wd_eth_resets, (unsigned long)st.roam_count,
    (unsigned long)s_queue_drops.load(), st.eth_link ? 1 : 0, (unsigned long)(millis() / 1000),
    (unsigned long)esp_get_free_heap_size(), st.bssid, st.client_ip,
    (unsigned long)st.txq_delay_ms, (unsigned long)st.air_fail);

  queue_publish(s_state, payload, 0, 0);
}

/* See telemetry.h. */
void telemetry_note_watchdog_event(const char *action, const char *reason) {
  if (!s_mqtt || !s_connected) return;

  char topic[64];
  snprintf(topic, sizeof(topic), "%s/watchdog", s_base);

  char payload[128];
  snprintf(payload, sizeof(payload), "{\"action\":\"%s\",\"reason\":\"%s\",\"uptime\":%lu}",
           action, reason ? reason : "", (unsigned long)(millis() / 1000));

  /* Best-effort event: a reboot may discard it. Local recovery must never
   * delay for MQTT transmission or acknowledgement. */
  queue_publish(topic, payload, 1, 0);
}
