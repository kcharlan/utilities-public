#include "runner.h"
#include "zstd.h"

TEST(zstd_vendor_is_pinned_decoder_and_decodes_stored_frame) {
    ASSERT_EQ(10507u, ZSTD_versionNumber());
    /* Synthetic single-segment frame: 4-byte content size, one raw last block. */
    const unsigned char frame[] = {0x28,0xB5,0x2F,0xFD, 0xA0, 8,0,0,0, 0x41,0,0,
                                   '{','"','k','"',':','1','}','\n'};
    char out[16];
    size_t n = ZSTD_decompress(out, sizeof out, frame, sizeof frame);
    ASSERT_FALSE(ZSTD_isError(n));
    ASSERT_EQ(8u, n);
    ASSERT_TRUE(!memcmp(out, "{\"k\":1}\n", 8));
}
