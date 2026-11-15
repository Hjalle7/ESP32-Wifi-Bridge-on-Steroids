#pragma once
#include <stddef.h>
#include <string.h>

/* Compare complete bounded credentials without a data-dependent byte exit.
 * Empty values never authenticate, including an uninitialized setup secret. */
static inline bool provisioning_secret_equal(const char *expected, const char *received) {
  const size_t size = strlen(expected);
  if (!size || strlen(received) != size) return false;
  unsigned char different = 0;
  for (size_t i = 0; i < size; ++i) different |= expected[i] ^ received[i];
  return different == 0;
}
