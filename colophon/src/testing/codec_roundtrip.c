#include "codec_roundtrip.h"
#include "cache/codec.h"
#include "parse/record.h"
#include <stdlib.h>
Err test_codec_roundtrip(LogRecord *r) {
    unsigned char *bytes = NULL;
    size_t length = 0;
    LogRecord decoded = {0};
    Err e = codec_encode(r, &bytes, &length);
    if (!e.code)
        e = codec_decode(bytes, length, &r->key, r->reader.tail_sha256, r->identifiers, &decoded);
    free(bytes);
    if (e.code) {
        record_destroy(&decoded);
        return e;
    }
    record_destroy(r);
    *r = decoded;
    r->token_stream.arena = &r->arena;
    return ERR_SUCCESS;
}
