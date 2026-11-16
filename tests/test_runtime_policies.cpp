#include "local_watchdog.h"
#include "provisioning_auth.h"
#include <assert.h>
#include <stdio.h>

/* Exercise quiet Modbus use, physical outages, threshold boundaries and
 * overflow-sized windows independently of ESP-IDF/hardware availability. */
int main() {
  assert(local_watchdog_reason(true, true, 0, 0, 0, 0, 0) == 0);
  assert(local_watchdog_reason(false, false, 0, 1000, 0, 1000, 10) == 0);
  assert(local_watchdog_reason(true, false, 0, 0, 0, 0, 0) == 3);
  assert(local_watchdog_reason(true, true, 0, 0, 0, 0, 4) == 2);
  assert(local_watchdog_reason(true, true, 169, 30, 0, 0, 0) == 0);
  assert(local_watchdog_reason(true, true, 170, 30, 0, 0, 0) == 1);
  assert(local_watchdog_reason(true, true, 171, 29, 0, 0, 0) == 0);
  assert(local_watchdog_reason(true, true, 0, 0, 170, 30, 0) == 4);
  assert(local_watchdog_reason(true, true, UINT32_MAX, UINT32_MAX, 0, 0, 0) == 1);
  assert(provisioning_secret_equal("test-secret", "test-secret"));
  assert(!provisioning_secret_equal("", ""));
  assert(!provisioning_secret_equal("test-secret", "test-secreT"));
  assert(!provisioning_secret_equal("test-secret", "test-secret-extra"));
  puts("Local health and credential policy checks passed");
}
