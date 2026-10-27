#ifndef CZSTD_H
#define CZSTD_H

// Shim for the vendored zstd decompression sources (see ../VERSION). SwiftPM exposes this
// directory as the module's public headers; the real headers live one level up.
#include "../zstd.h"
#include "../zstd_errors.h"

#endif
