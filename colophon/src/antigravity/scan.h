#ifndef CP_ANTIGRAVITY_SCAN_H
#define CP_ANTIGRAVITY_SCAN_H
#include "db.h"
#include "cli/args.h"
/* Discovery precedes runtime creation. Disabled means no source inspection. */
Err antigravity_discover(const Args *args,AntigravityStore *store);
const char *antigravity_status(const AntigravityStore *store);
#endif
