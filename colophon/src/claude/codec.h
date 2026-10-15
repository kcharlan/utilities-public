#ifndef CP_CLAUDE_CODEC_H
#define CP_CLAUDE_CODEC_H
#include "parse.h"
/* Independent versioned Claude format, wholly owned by the decoded record.
 * Does not depend on source availability or a run Intern. */
Err claude_codec_encode(const ClaudeRecord *record, unsigned char **bytes, size_t *length);
Err claude_codec_decode(const void *bytes, size_t length, ClaudeRecord *out);
#endif
