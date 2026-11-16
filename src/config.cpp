/*
 * config.cpp - Loading, saving and resetting the persistent configuration.
 *
 * The configuration lives in g_cfg and is persisted as a single NVS blob
 * (namespace CFG_NVS_NS, key CFG_NVS_KEY). See config.h for the layout rules.
 */
#include "config.h"

#include <string.h>
#include <stdio.h>

#include "nvs.h"
#include "nvs_flash.h"

BridgeConfig g_cfg;

/* Fill *c with factory defaults.
 *
 * Everything is zeroed first, then the few fields that need a non-zero
 * starting value are set. The management IP defaults are only a starting
 * point - they are meant to be corrected in the portal. */
void cfg_defaults(BridgeConfig *c) {
  memset(c, 0, sizeof(*c));
  c->magic = CFG_MAGIC;
  strcpy(c->name, "wifibridge");

  c->mgmt_ip[0] = 192; c->mgmt_ip[1] = 168; c->mgmt_ip[2] = 178; c->mgmt_ip[3] = 250;
  c->mgmt_mask[0] = 255; c->mgmt_mask[1] = 255; c->mgmt_mask[2] = 255; c->mgmt_mask[3] = 0;
  c->mgmt_gw[0] = 192; c->mgmt_gw[1] = 168; c->mgmt_gw[2] = 178; c->mgmt_gw[3] = 1;

  c->mqtt_port    = 1883;
  c->telemetry_s  = 10;
  c->configured   = false;

  /* The tuning fields deliberately stay at 0. That is not a forgotten
   * default but the convention from config.h: 0 means "use the sdkconfig
   * value or the PHY default". Putting real numbers here would create a
   * second source of truth next to sdkconfig.defaults. */
}

/* Load the configuration from NVS into g_cfg.
 *
 * Starts from defaults, then overlays whatever is stored. The stored blob may
 * be shorter than sizeof(BridgeConfig) (written by older firmware with fewer
 * fields) or longer (after a downgrade); in both cases the common prefix is
 * copied and the rest stays at its default. Without this, every firmware
 * update that adds a field would wipe the configuration and leave the board
 * stuck in the setup AP instead of doing its job. */
bool cfg_load(void) {
  cfg_defaults(&g_cfg);
  // Default to closed until absence or a valid blob has been established.
  g_cfg.configured = true;
  nvs_handle_t guard;
  esp_err_t ge = nvs_open("provisioning", NVS_READONLY, &guard);
  uint8_t commissioned = 0;
  if (ge == ESP_OK) {
    ge = nvs_get_u8(guard, "commissioned", &commissioned);
    nvs_close(guard);
  }
  if (ge != ESP_OK && ge != ESP_ERR_NVS_NOT_FOUND) return false;

  nvs_handle_t h;
  esp_err_t opened = nvs_open(CFG_NVS_NS, NVS_READONLY, &h);
  if (opened != ESP_OK) {
    if (opened == ESP_ERR_NVS_NOT_FOUND && !commissioned) {
      g_cfg.configured = false;
      return true;
    }
    return false;
  }

  /* Query the stored size first. */
  size_t sz = 0;
  esp_err_t err = nvs_get_blob(h, CFG_NVS_KEY, NULL, &sz);
  if (err != ESP_OK || sz < offsetof(BridgeConfig, configured) + sizeof(g_cfg.configured)) {
    nvs_close(h);
    printf("[CFG ] No stored configuration - using defaults\n");
    return false;
  }

  uint8_t *raw = (uint8_t *)malloc(sz);
  if (!raw) { nvs_close(h); return false; }

  err = nvs_get_blob(h, CFG_NVS_KEY, raw, &sz);
  nvs_close(h);

  if (err != ESP_OK) { free(raw); return false; }

  uint32_t magic;
  memcpy(&magic, raw, sizeof(magic));
  if (magic != CFG_MAGIC) {
    free(raw);
    printf("[CFG ] Magic mismatch - using defaults\n");
    return false;
  }

  if (raw[offsetof(BridgeConfig, configured)] > 1) { free(raw); return false; }
  BridgeConfig tmp;
  cfg_defaults(&tmp);
  memcpy(&tmp, raw, sz < sizeof(tmp) ? sz : sizeof(tmp));
  free(raw);

  if (!memchr(tmp.name, '\0', sizeof(tmp.name))) return false;
  if (!memchr(tmp.ssid1, '\0', sizeof(tmp.ssid1))) return false;
  if (!memchr(tmp.pass1, '\0', sizeof(tmp.pass1))) return false;
  if (!memchr(tmp.ssid2, '\0', sizeof(tmp.ssid2))) return false;
  if (!memchr(tmp.pass2, '\0', sizeof(tmp.pass2))) return false;
  if (!memchr(tmp.mqtt_host, '\0', sizeof(tmp.mqtt_host))) return false;
  if (!memchr(tmp.mqtt_user, '\0', sizeof(tmp.mqtt_user))) return false;
  if (!memchr(tmp.mqtt_pass, '\0', sizeof(tmp.mqtt_pass))) return false;
  if (!memchr(tmp.admin_pass, '\0', sizeof(tmp.admin_pass))) return false;
  if (!memchr(tmp.ssid3, '\0', sizeof(tmp.ssid3))) return false;
  if (!memchr(tmp.pass3, '\0', sizeof(tmp.pass3))) return false;
  if (commissioned && !tmp.configured) return false;
  g_cfg = tmp;
  // Legacy configured blobs acquire the independent loss-detection marker.
  if (g_cfg.configured && !commissioned) {
    if (nvs_open("provisioning", NVS_READWRITE, &guard) != ESP_OK) return false;
    esp_err_t marked = nvs_set_u8(guard, "commissioned", 1);
    if (marked == ESP_OK) marked = nvs_commit(guard);
    nvs_close(guard);
    if (marked != ESP_OK) return false;
  }
  printf("[CFG ] Loaded (%u of %u bytes): name='%s' ssid1='%s'\n",
                (unsigned)sz, (unsigned)sizeof(tmp), g_cfg.name, g_cfg.ssid1);
  return true;
}

/* Persist g_cfg to NVS (always the full current struct size). */
bool cfg_save(void) {
  // Claim commissioning before storing settings: interrupted saves fail closed.
  if (!g_cfg.configured) return false;
  nvs_handle_t guard;
  if (nvs_open("provisioning", NVS_READWRITE, &guard) != ESP_OK) return false;
  esp_err_t marked = nvs_set_u8(guard, "commissioned", 1);
  if (marked == ESP_OK) marked = nvs_commit(guard);
  nvs_close(guard);
  if (marked != ESP_OK) return false;
  g_cfg.magic = CFG_MAGIC;

  nvs_handle_t h;
  if (nvs_open(CFG_NVS_NS, NVS_READWRITE, &h) != ESP_OK) return false;

  esp_err_t err = nvs_set_blob(h, CFG_NVS_KEY, &g_cfg, sizeof(g_cfg));
  if (err == ESP_OK) err = nvs_commit(h);
  nvs_close(h);

  printf("[CFG ] Save: %s\n", err == ESP_OK ? "ok" : "FAILED");
  return err == ESP_OK;
}

/* Erase everything in the configuration namespace and reset g_cfg to
 * defaults. Only our own namespace is erased, not the whole NVS partition. */
bool cfg_factory_reset(void) {
  nvs_handle_t h;
  if (nvs_open(CFG_NVS_NS, NVS_READWRITE, &h) != ESP_OK) return false;
  nvs_erase_all(h);
  esp_err_t err = nvs_commit(h);
  nvs_close(h);
  cfg_defaults(&g_cfg);
  return err == ESP_OK;
}

/* --------------------------------------------------------------------------
 * IPv4 helpers
 * ------------------------------------------------------------------------ */

/* Parse "a.b.c.d" into out[0..3]. Rejects anything that is not four decimal
 * numbers in the range 0..255; `out` is only written on success. */
bool parse_ipv4(const char *s, uint8_t out[4]) {
  if (!s) return false;
  unsigned a, b, c, d;
  if (sscanf(s, "%u.%u.%u.%u", &a, &b, &c, &d) != 4) return false;
  if (a > 255 || b > 255 || c > 255 || d > 255) return false;
  out[0] = (uint8_t)a; out[1] = (uint8_t)b;
  out[2] = (uint8_t)c; out[3] = (uint8_t)d;
  return true;
}

/* Format ip[0..3] as "a.b.c.d" into out (needs at least 16 bytes). */
void format_ipv4(const uint8_t ip[4], char *out, size_t out_len) {
  snprintf(out, out_len, "%u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
}
