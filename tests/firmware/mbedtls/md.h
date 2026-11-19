#pragma once

#include <cstddef>

enum mbedtls_md_type_t { MBEDTLS_MD_SHA1 };
struct mbedtls_md_info_t {};

inline const mbedtls_md_info_t *mbedtls_md_info_from_type(mbedtls_md_type_t) {
  static const mbedtls_md_info_t info;
  return &info;
}

inline int mbedtls_md_hmac(const mbedtls_md_info_t *, const unsigned char *,
                           size_t, const unsigned char *, size_t,
                           unsigned char *) {
  return -1;
}
