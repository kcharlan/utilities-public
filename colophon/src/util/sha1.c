#include "sha1.h"
#include <CommonCrypto/CommonDigest.h>
void sha1_digest(Str text, unsigned char digest[20]) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    CC_SHA1(text.p, text.n, digest);
#pragma clang diagnostic pop
}
