#ifndef CP_OPENCODE_SCAN_H
#define CP_OPENCODE_SCAN_H
#include "db.h"
#include "cli/args.h"
/* Discovery is read-only and precedes runtime creation. Disabled returns before
 * inspecting any source. Call read afterwards; store owns paths and diagnostics. */
Err opencode_discover(const Args *args, OpencodeStore *store);
const char *opencode_status(const OpencodeStore *store);
const char *opencode_database_status(OpencodeDatabaseStatus status);
#endif
