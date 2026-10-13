#ifndef CP_SHA1_H
#define CP_SHA1_H
#include "str.h"
/* SHA-1 is source-defined message-dedup evidence, not a security primitive. */
void sha1_digest(Str text, unsigned char digest[20]);
#endif
