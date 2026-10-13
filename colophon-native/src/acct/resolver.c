#include "resolver.h"
#include "parse/record.h"
#include "tracker.h"
#include "util/time.h"
#include <stdint.h>
#include <string.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
static Err key(InheritedResolver *r, Str id, Str *out) {
  return str_nfc(&r->arena, id, "accounting.session_id", out);
}
static Err diagnostic(InheritedResolver *r, Str kind, Str id) {
  ResolverDiagnostic d = {kind, id};
  return record_append(&r->arena, (void **)&r->diagnostics,
                       &r->diagnostic_count, &r->diagnostic_capacity, sizeof d,
                       &d);
}
Err resolver_add(InheritedResolver *r, Str id, const TokenStream *s) {
  Str identity;
  TRY(key(r, id, &identity));
  return omap_put(&r->streams, identity, (void *)s);
}
Err resolver_snapshot(InheritedResolver *r, Str id, SnapshotResolution **out) {
  *out = NULL;
  Str identity;
  TRY(key(r, id, &identity));
  const TokenStream *stream = omap_get(&r->streams, identity);
  if (!stream) {
    TRY(diagnostic(r, STR_LIT("missing"), id));
    return ERR_SUCCESS;
  }
  SnapshotResolution *memo = omap_get(&r->memo, identity);
  if (!memo) {
    TRY(arena_alloc(&r->arena, sizeof *memo, _Alignof(SnapshotResolution),
                    (void **)&memo));
    *memo = (SnapshotResolution){0};
    Err e = accounting_parse(stream, r, &memo->result);
    if (e.code) {
      accounting_result_destroy(&memo->result);
      return e;
    }
    Str parsed;
    e = key(r, memo->result.session_id, &parsed);
    if (e.code) {
      accounting_result_destroy(&memo->result);
      return e;
    }
    if (!memo->result.session_id.p || !str_equal(identity, parsed)) {
      accounting_result_destroy(&memo->result);
      return err_make(ERR_INVALID,
                      "resolver stream key differs from parsed session id");
    }
    memo->stream = stream;
    memo->offered = true;
    if (memo->result.forked_from_id.p && memo->result.depends_on_parent) {
      Str parent;
      e = key(r, memo->result.forked_from_id, &parent);
      if (e.code) {
        accounting_result_destroy(&memo->result);
        return e;
      }
      memo->offered =
          (uintptr_t)omap_get(&r->dependencies, parent) == DEP_RESOLVED;
    }
    /* A direct snapshot call can recursively install this identity first.
     * Source overwrites that entry at the original position; release its
     * separately owned result only after replacement succeeds. */
    SnapshotResolution *replaced = omap_get(&r->memo, identity);
    e = omap_put(&r->memo, identity, memo);
    if (e.code) {
      accounting_result_destroy(&memo->result);
      return e;
    }
    if (replaced)
      accounting_result_destroy(&replaced->result);
  }
  *out = memo;
  return ERR_SUCCESS;
}
/* Both times parsed -> instant ordering; either invalid -> lexical ordering. */
static int compare_timestamp(Str a, Str b) {
  int64_t x, y;
  if (time_codex_timestamp(a, "accounting.snapshot.timestamp", &x) &&
      time_codex_timestamp(b, "accounting.snapshot.timestamp", &y))
    return (x > y) - (x < y);
  return str_compare(a, b);
}
static Err inherited(InheritedResolver *r, Str id, Str identity, Str cutoff,
                     ForkBaseline *out) {
  if (!cutoff.n) {
    TRY(diagnostic(r, STR_LIT("missing-cutoff"), id));
    return ERR_SUCCESS;
  }
  int64_t ms;
  if (!time_codex_timestamp(cutoff, "accounting.fork_ts", &ms))
    TRY(diagnostic(r, STR_LIT("lexical-cutoff"), id));
  SnapshotResolution *s;
  TRY(resolver_snapshot(r, id, &s));
  if (!s) {
    TRY(omap_put(&r->dependencies, identity, (void *)(uintptr_t)DEP_MISSING));
    return ERR_SUCCESS;
  }
  if (!s->offered) {
    TRY(omap_put(&r->dependencies, identity, (void *)(uintptr_t)DEP_NONE));
    return ERR_SUCCESS;
  }
  AccountingResult *p = &s->result;
  bool complete = !s->stream->unconsumed_tail && !p->buffered_retained &&
                  !p->buffered_count;
  if (!complete &&
      (!p->snapshot_count ||
       compare_timestamp(p->snapshots[p->snapshot_count - 1].timestamp,
                         cutoff) < 0))
    return ERR_SUCCESS;
  SnapshotAccumulator acc = {0};
  for (size_t i = 0; i < p->snapshot_count; i++) {
    TokenSnapshot snap = p->snapshots[i];
    Totals last = accounting_totals(snap.last),
           total = accounting_totals(snap.total);
    Totals counted = snapshot_apply(&acc, snap.last.present ? &last : NULL,
                                    snap.total.present ? &total : NULL);
    if (compare_timestamp(snap.timestamp, cutoff) <= 0) {
      out->totals = counted;
      out->present = true;
      totals_note_state(counted, "accounting.resolver.inherited_totals");
    }
  }
  if (!out->present && p->has_fork_state && p->has_inherited) {
    out->present = true;
    out->totals = p->inherited;
    totals_note_state(out->totals, "accounting.resolver.inherited_totals");
  }
  if (!out->present && p->forked_from_id.p && !p->has_fork_state)
    return ERR_SUCCESS;
  TRY(omap_put(&r->dependencies, identity, (void *)(uintptr_t)DEP_RESOLVED));
  out->resolved = true;
  return ERR_SUCCESS;
}
Err resolver_inherited(InheritedResolver *r, Str id, Str cutoff,
                       ForkBaseline *out) {
  *out = (ForkBaseline){0};
  Str identity;
  TRY(key(r, id, &identity));
  if (r->resolving.size >= 64 || omap_get(&r->resolving, identity))
    return ERR_SUCCESS;
  TRY(omap_put(&r->resolving, identity, (void *)1));
  Err e = inherited(r, id, identity, cutoff, out);
  omap_delete(&r->resolving, identity, NULL);
  return e;
}
void resolver_destroy(InheritedResolver *r) {
  for (OmapEntry *e = r->memo.first; e; e = e->next)
    accounting_result_destroy(&((SnapshotResolution *)e->value)->result);
  omap_destroy(&r->memo);
  omap_destroy(&r->streams);
  omap_destroy(&r->dependencies);
  omap_destroy(&r->resolving);
  arena_destroy(&r->arena);
  memset(r, 0, sizeof *r);
}
Err accounting_logs(LogRecord *const *records, size_t count,
                    InheritedResolver *resolver, AccountingResult *results) {
  Omap selected = {0};
  Err e = ERR_SUCCESS;
  /* Parent winners computed separately: never reorder accounting consumers. */
  for (size_t i = 0; i < count; i++) {
    LogRecord *rec = records[i];
    if (!rec->token_stream.has_prepass ||
        !rec->token_stream.prepass.session_id.p)
      continue;
    Str id;
    e = key(resolver, rec->token_stream.prepass.session_id, &id);
    if (e.code)
      break;
    LogRecord *old = omap_get(&selected, id);
    if (!old || rec->key.mtime_ns > old->key.mtime_ns ||
        (rec->key.mtime_ns == old->key.mtime_ns &&
         str_compare(rec->key.path, old->key.path) < 0)) {
      e = omap_put(&selected, id, rec);
      if (e.code)
        break;
    }
  }
  if (!e.code)
    for (OmapEntry *p = selected.first; p; p = p->next) {
      e = omap_put(&resolver->streams, p->key,
                   &((LogRecord *)p->value)->token_stream);
      if (e.code)
        break;
    }
  omap_destroy(&selected);
  if (e.code)
    return e;
  for (size_t i = 0; i < count; i++) {
    TRY(accounting_parse(&records[i]->token_stream, resolver, &results[i]));
    for (size_t j = 0; j < results[i].row_count; j++)
      results[i].rows[j].file = (int64_t)i;
  }
  return ERR_SUCCESS;
}
