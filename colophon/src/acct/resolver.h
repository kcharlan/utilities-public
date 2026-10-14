#ifndef CP_ACCOUNTING_RESOLVER_H
#define CP_ACCOUNTING_RESOLVER_H
#include "parser.h"
#include "util/omap.h"
typedef enum { DEP_NONE, DEP_MISSING, DEP_RESOLVED } DependencyStatus;
typedef struct {
  const TokenStream *stream;
  AccountingResult result;
  bool offered;
} SnapshotResolution;
typedef struct {
  Str kind, session_id;
} ResolverDiagnostic;
struct InheritedResolver {
  Arena arena;
  Omap streams, memo, dependencies, resolving;
  ResolverDiagnostic *diagnostics;
  size_t diagnostic_count, diagnostic_capacity;
};
typedef struct {
  bool resolved, present;
  Totals totals;
} ForkBaseline;
Err resolver_add(InheritedResolver *resolver, Str session_id,
                 const TokenStream *stream);
Err resolver_snapshot(InheritedResolver *resolver, Str session_id,
                      SnapshotResolution **out);
Err resolver_inherited(InheritedResolver *resolver, Str session_id, Str cutoff,
                       ForkBaseline *out);
void resolver_destroy(InheritedResolver *resolver);
/* Inputs are borrowed in caller order. Parent selection does not reorder them.
 * Results and resolver borrow records until destroyed. */
Err accounting_logs(LogRecord *const *records, size_t count,
                    InheritedResolver *resolver, AccountingResult *results);
#endif
