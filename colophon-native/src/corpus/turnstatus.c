#include "turnstatus.h"
#include "parse/turns.h"
#include "util/sort.h"
#include <math.h>
#include <stdalign.h>
int corpus_number_compare(PyNum a, PyNum b) { return pynum_compare(a, b); }
bool corpus_quiet(int64_t snapshot, int64_t mtime) {
  return (__int128)snapshot - (__int128)mtime > 7200000;
}
static int ordering(const void *left, const void *right, void *context) {
  (void)context;
  const TurnModel *a = left, *b = right;
  MaybeNum x = a->start_ms.present ? a->start_ms : a->end_ms;
  MaybeNum y = b->start_ms.present ? b->start_ms : b->end_ms;
  if (x.present != y.present)
    return x.present ? -1 : 1;
  return x.present ? corpus_number_compare(x.value, y.value) : 0;
}
Err turn_models(Arena *arena, TurnFact *const *facts, size_t count,
                bool collapsed, int64_t mtime, int64_t snapshot,
                TurnModel **out) {
  *out = NULL;
  if (!count)
    return ERR_SUCCESS;
  Err e = arena_alloc(arena, count * sizeof **out, alignof(TurnModel),
                      (void **)out);
  if (e.code)
    return e;
  bool quiet = corpus_quiet(snapshot, mtime);
  for (size_t i = 0; i < count; i++) {
    const TurnFact *fact = facts[i];
    TurnTiming timing = turn_timing(fact, collapsed);
    TurnModel *t = &(*out)[i];
    *t = (TurnModel){.id = fact->key,
                     .status = fact->end_kind,
                     .start_ms = timing.start_ms,
                     .duration_ms = timing.duration_ms,
                     .ttft_ms = fact->ttft_ms};
    if (fact->end_ms.present)
      t->end_ms = (MaybeNum){true, {.i = fact->end_ms.value}};
    for (size_t k = 0; k < timing.flag_count; k++) {
      Str f = timing.flags[k];
      t->flags |= str_equal(f, STR_LIT("collapsed"))           ? F_COLLAPSED
                  : str_equal(f, STR_LIT("reported_duration")) ? F_REPORTED
                  : str_equal(f, STR_LIT("start_from_completion"))
                      ? F_START_COMPLETION
                      : F_UNKNOWN;
    }
    if (str_equal(fact->end_kind, STR_LIT("open"))) {
      t->status = quiet ? STR_LIT("abandoned") : STR_LIT("running");
      if (!quiet) {
        t->flags |= F_LIVE;
        t->end_ms = (MaybeNum){true, {.i = snapshot}};
        if (t->start_ms.present &&
            corpus_number_compare(t->end_ms.value, t->start_ms.value) >= 0)
          t->duration_ms.present =
              pynum_sub(t->end_ms.value, t->start_ms.value, "turn.duration",
                        &t->duration_ms.value);
        else
          t->flags |= F_UNKNOWN;
      }
    }
  }
  e = stable_sort(*out, count, sizeof **out, ordering, NULL);
  if (e.code)
    return e;
  for (size_t i = 0; i < count; i++)
    (*out)[i].n = i + 1;
  return ERR_SUCCESS;
}
typedef struct {
  PyNum start, end;
} Interval;
static int interval_order(const void *a, const void *b, void *ctx) {
  (void)ctx;
  const Interval *x = a, *y = b;
  int c = corpus_number_compare(x->start, y->start);
  return c ? c : corpus_number_compare(x->end, y->end);
}
Err active_interval_union(Arena *arena, const TurnModel *turns, size_t count,
                          MaybeNum *out) {
  *out = (MaybeNum){.present = true, .value = {.i = 0}};
  if (!count)
    return ERR_SUCCESS;
  Interval *v;
  Err e = arena_alloc(arena, count * sizeof *v, alignof(Interval), (void **)&v);
  if (e.code)
    return e;
  size_t n = 0;
  for (size_t i = 0; i < count; i++) {
    const TurnModel *t = &turns[i];
    if (!str_equal(t->status, STR_LIT("abandoned")) && t->duration_ms.present &&
        t->start_ms.present && t->end_ms.present &&
        corpus_number_compare(t->end_ms.value, t->start_ms.value) >= 0)
      v[n++] = (Interval){t->start_ms.value, t->end_ms.value};
  }
  e = stable_sort(v, n, sizeof *v, interval_order, NULL);
  if (e.code || !n)
    return e;
  out->present = false;
  PyNum start = v[0].start, end = v[0].end, delta, total = {.i = 0};
  for (size_t i = 1; i < n; i++) {
    if (corpus_number_compare(v[i].start, end) <= 0) {
      if (corpus_number_compare(v[i].end, end) > 0)
        end = v[i].end;
    } else {
      if (!pynum_sub(end, start, "session.active", &delta) ||
          !pynum_add(total, delta, "session.active", &total))
        return ERR_SUCCESS;
      start = v[i].start;
      end = v[i].end;
    }
  }
  if (pynum_sub(end, start, "session.active", &delta) &&
      pynum_add(total, delta, "session.active", &total))
    *out = (MaybeNum){.present = true, .value = total};
  return ERR_SUCCESS;
}
