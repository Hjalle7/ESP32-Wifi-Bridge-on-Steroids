#pragma once
#include <stdint.h>

/* Fixed from session entry, independent of authenticated HTTP activity.
 * First-time setup has no deadline; configured devices need fresh GPIO entry. */
#define PROVISIONING_MAX_SESSION_MS (30u * 60u * 1000u)

static inline bool provisioning_session_expired(bool configured_at_entry,
                                                uint32_t started_at,
                                                uint32_t now) {
  return configured_at_entry && now - started_at >= PROVISIONING_MAX_SESSION_MS;
}
