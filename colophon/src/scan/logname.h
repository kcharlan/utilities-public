#ifndef CP_LOGNAME_H
#define CP_LOGNAME_H
#include "util/str.h"
typedef enum { LOG_NAME_OTHER, LOG_NAME_PLAIN, LOG_NAME_ZSTD } LogNameFormat;
/* Classifies a path by its final component. NAME.jsonl is a plain log and
 * NAME.jsonl.zst a Zstandard-compressed one, both suffixes ASCII
 * case-insensitive. NAME must be nonempty: pathlib treats an initial dot as
 * part of the basename. Codex writes the .zst form when a session ends. */
LogNameFormat log_name_format(Str path);
#endif
