#ifndef CP_RUN_H
#define CP_RUN_H
#include "args.h"
int cli_run(const Args *args);
/* URL hostname projection shared by the product and authored payload seam.
 * Returned string is malloc-owned, or NULL for an absent host. */
char *cli_source_host(const char *url);
#endif
