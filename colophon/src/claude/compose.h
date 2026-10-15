#ifndef CP_CLAUDE_COMPOSE_H
#define CP_CLAUDE_COMPOSE_H
#include "scan.h"
/* Original physical line only: no suffix recovery and a 512 KiB ceiling. */
Err claude_usage_line(ClaudeRecord *record, const ReaderRawLine *line,
                      Str turn);
/* Local cumulative replacement precedes cross-file winner selection. Authored
 * units and summaries belong to Corpus.usage_arena; records stay immutable. */
Err claude_compose(ClaudeScan *scan, Corpus *corpus);
#endif
