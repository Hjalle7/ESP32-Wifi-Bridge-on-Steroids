#pragma once
#include <stdint.h>

/* Classify local driver evidence only. Idle traffic and a disconnected cable
 * are not faults; no probe or broker is needed. Wi-Fi failures must count
 * failed driver transmits, excluding queue-cap, throttle and offline drops.
 * Values retain telemetry IDs. */
static inline uint8_t local_watchdog_reason(bool ethernet_up, bool wifi_up,
    uint32_t wifi_packets, uint32_t wifi_failures, uint32_t eth_packets,
    uint32_t eth_drops, uint32_t disconnects) {
  if (!ethernet_up) return 0;
  if (!wifi_up) return 3;
  if (disconnects >= 4) return 2;
  const uint64_t eth_total = (uint64_t)eth_packets + eth_drops;
  if (eth_total >= 200 && 1000ULL * eth_drops >= 150ULL * eth_total) return 4;
  const uint64_t wifi_total = (uint64_t)wifi_packets + wifi_failures;
  if (wifi_total >= 200 && 1000ULL * wifi_failures >= 150ULL * wifi_total) return 1;
  return 0;
}
