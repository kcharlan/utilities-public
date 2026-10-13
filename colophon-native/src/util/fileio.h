#ifndef CP_FILEIO_H
#define CP_FILEIO_H
#include "err.h"
#include "str.h"
#include <stddef.h>
/* Returned strings/buffers are malloc-owned and NUL terminated. Byte count
 * excludes the terminator; embedded NUL bytes are preserved. */
Err file_read_all(const char *path, char **bytes, size_t *length);
Err runtime_home(char **path);
/* pathlib POSIX lexical normalization and expanduser, shared by CLI paths. */
Err file_expand_path(const char *raw, char **path);
/* Length-aware lexical path operations. Returned Str is malloc-owned and
 * NUL-terminated; embedded NUL remains an ordinary metadata component byte.
 * missing_user_unchanged selects os.path.expanduser instead of pathlib. */
Err file_lexical_path(Str raw, bool collapse_parent, Str *path);
Err file_expand_user(Str raw, bool missing_user_unchanged, Str *path);
/* Codex key: abspath with lexical '..', preserving links and '//' anchor;
 * strips /private only for /private/var/... as the pinned producer does. */
Err file_codex_path_key(const char *path, char **key);
Err file_abbreviate_home(const char *path, char **display);
/* Create missing directories with 0700; existing parents retain their modes. */
Err file_mkdir_parents(const char *directory);
/* Enforce runtime directory 0700, then best-effort stale regular-temp sweep. */
Err ensure_runtime_home(const char *path);
#endif
