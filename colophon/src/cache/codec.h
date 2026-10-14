#ifndef CP_CODEC_H
#define CP_CODEC_H
#include "model/logrecord.h"
/* One portable format; output bytes are malloc-owned. Decode initializes and
 * owns a record, borrowing the supplied run Intern. Invalid data is ERR_INVALID,
 * allocation failure is ERR_NOMEM. Always destroy decoded output, even on error. */
Err codec_encode(const LogRecord *record, unsigned char **bytes, size_t *length);
Err codec_decode(const void *bytes, size_t length, const DiscoveredLog *key, const char tail[65],
                 Intern *identifiers, LogRecord *out);
#endif
