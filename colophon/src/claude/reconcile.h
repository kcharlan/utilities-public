#ifndef CP_CLAUDE_RECONCILE_H
#define CP_CLAUDE_RECONCILE_H
#include "parse.h"
/* Borrow record strings; own composed arrays in the corpus arena. The caller
 * destroys temporary map nodes after add/link, never the borrowed records. */
Err claude_reader_reconcile(ClaudeRecord *records, size_t count, Corpus *corpus,
                            ClaudeRecord **out, size_t *out_count);
void claude_reader_views_destroy(ClaudeRecord *views, size_t count);
#endif
