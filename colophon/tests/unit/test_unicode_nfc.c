#include "runner.h"
#include "util/unicode_nfc.h"
#include <stdlib.h>

TEST(unicode_nfc_rejects_invalid_input_and_clears_output) {
    uint32_t bad[] = {0x110000};
    uint32_t *output = bad;
    size_t length = 99;
    ASSERT_FALSE(cp_unicode_nfc(bad, 1, &output, &length));
    ASSERT_TRUE(output == NULL);
    ASSERT_EQ(0, length);
    ASSERT_FALSE(cp_unicode_nfc(NULL, 1, &output, &length));
    ASSERT_FALSE(cp_unicode_nfc(bad, SIZE_MAX, &output, &length));
    ASSERT_FALSE(cp_unicode_nfc(bad, 1, NULL, &length));
    ASSERT_FALSE(cp_unicode_nfc(bad, 1, &output, NULL));
}

TEST(unicode_nfc_empty_and_ascii_owned_output) {
    uint32_t *output = NULL;
    size_t length;
    ASSERT_TRUE(cp_unicode_nfc(NULL, 0, &output, &length));
    ASSERT_TRUE(output == NULL);
    ASSERT_EQ(0, length);
    uint32_t ascii[] = {'A', 0, 'Z'};
    ASSERT_TRUE(cp_unicode_nfc(ascii, 3, &output, &length));
    ASSERT_EQ(3, length);
    ASSERT_TRUE(output != ascii);
    ASSERT_EQ(0, memcmp(ascii, output, sizeof(ascii)));
    free(output);
}

TEST(unicode_nfc_combining_blocking_hangul_and_surrogates) {
    uint32_t input[] = {'A', 0x305, 0x301, 0x1100, 0x1161, 0x11a8, 0xd800, 0x301};
    uint32_t expected[] = {'A', 0x305, 0x301, 0xac01, 0xd800, 0x301};
    uint32_t *output;
    size_t length;
    ASSERT_TRUE(cp_unicode_nfc(input, 8, &output, &length));
    ASSERT_EQ(6, length);
    ASSERT_EQ(0, memcmp(expected, output, sizeof(expected)));
    free(output);
}
