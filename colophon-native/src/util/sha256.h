#ifndef CP_SHA256_H
#define CP_SHA256_H
#include <stddef.h>
#include <stdint.h>
typedef struct {
    uint32_t state[8];
    uint64_t bytes;
    unsigned char block[64];
    size_t used;
} Sha256;
void sha256_init(Sha256 *hash);
void sha256_update(Sha256 *hash, const void *data, size_t length);
void sha256_final(Sha256 *hash, unsigned char output[32]);
void sha256_hex(const void *data, size_t length, char output[65]);
#endif
