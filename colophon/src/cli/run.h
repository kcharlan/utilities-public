#ifndef CP_RUN_H
#define CP_RUN_H
#include "args.h"
#include <stddef.h>
#define COLOPHON_PAGE_SIZE_LIMIT (128u * 1024u * 1024u)
bool cli_page_over_limit(size_t size);
int cli_run(const Args *args);
/* URL hostname projection shared by the product and authored payload seam.
 * Returned string is malloc-owned, or NULL for an absent host. */
char *cli_source_host(const char *url);
#endif
