#include "reconcile.h"
#include "out/jsonw.h"
#include "parse/record.h"
#include <stdalign.h>
#include <stdio.h>
#include <string.h>
#define TRY(x) do { Err e_ = (x); if (e_.code) return e_; } while (0)
static Err zero(Arena *a, size_t n, size_t size, size_t alignment, void **out) {
  if (size && n > SIZE_MAX / size) return err_make(ERR_NOMEM, "Claude reader allocation overflow");
  TRY(arena_alloc(a, n * size, alignment, out));
  memset(*out, 0, n * size);
  return ERR_SUCCESS;
}
static bool same_prompt(const Request *a, const Request *b) {
  return a->at_ms.present == b->at_ms.present &&
      (!a->at_ms.present || a->at_ms.value == b->at_ms.value) &&
      str_equal(a->text, b->text) && str_equal(a->kind, b->kind) && a->images == b->images;
}
static bool later(MaybeMs a, MaybeMs b) {
  return a.present && (!b.present || a.value > b.value);
}
static Err max_map(Arena *a, Omap *to, const Omap *from) {
  for (OmapEntry *p = from->first; p; p = p->next) {
    __int128 *value = omap_get(to, p->key), n = *(__int128 *)p->value;
    if (!value) {
      TRY(zero(a, 1, sizeof *value, alignof(__int128), (void **)&value));
      TRY(omap_put(to, p->key, value));
    }
    if (n > *value) *value = n;
  }
  return ERR_SUCCESS;
}
static Err max_tools(Arena *a, CorpusTools *to, const CorpusTools *from) {
#define MAX(f) if (from->f > to->f) to->f = from->f
  MAX(shell); MAX(shell_failed); MAX(file_edits); MAX(web); MAX(image);
#undef MAX
  TRY(max_map(a, &to->mcp, &from->mcp));
  return max_map(a, &to->other, &from->other);
}
static Err grow(Arena *a, ClaudeRecord *v, size_t *capacity) {
  if (v->turn_count < *capacity) return ERR_SUCCESS;
  size_t n = *capacity ? *capacity * 2 : 8;
  void *next;
#define GROW(field, type) do { \
  TRY(zero(a, n, sizeof *v->field, alignof(type), &next)); \
  if (v->turn_count) memcpy(next, v->field, v->turn_count * sizeof *v->field); \
  v->field = next; \
} while (0)
  GROW(turns, TurnFact *); GROW(requests, Request); GROW(answers, Str);
  GROW(answer_ms, MaybeMs); GROW(tools, CorpusTools);
#undef GROW
  *capacity = n;
  return ERR_SUCCESS;
}
static Err merge_record(Arena *a, ClaudeRecord *v, size_t *capacity,
                        ClaudeRecord *r, size_t **occurrences) {
  for (size_t i = 0; i < r->turn_count; i++) {
    TurnFact *source = r->turns[i];
    size_t occurrence = 0;
    for (size_t k = 0; k < i; k++)
      if (same_prompt(&r->requests[k], &r->requests[i])) occurrence++;
    size_t found = v->turn_count;
    for (size_t k = 0; k < v->turn_count; k++) {
      Str uuid = v->turns[k]->turn_id;
      /* Conflicting UUIDs never collapse merely because the visible prompt
       * matches. Legacy/UUID-less input uses the exact tuple + occurrence. */
      bool both = source->turn_id.n && uuid.n;
      if ((both && str_equal(source->turn_id, uuid)) ||
          (!both && (*occurrences)[k] == occurrence && same_prompt(&v->requests[k], &r->requests[i]))) {
        found = k; break;
      }
    }
    if (found == v->turn_count) {
      size_t old_capacity = *capacity;
      TRY(grow(a, v, capacity));
      if (*capacity != old_capacity) {
        size_t *next;
        TRY(zero(a, *capacity, sizeof *next, alignof(size_t), (void **)&next));
        if (v->turn_count) memcpy(next, *occurrences, v->turn_count * sizeof *next);
        *occurrences = next;
      }
      TurnFact *t;
      TRY(zero(a, 1, sizeof *t, alignof(TurnFact), (void **)&t));
      *t = *source;
      char key[64]; int n = snprintf(key, sizeof key, "claude-turn-%zu", found + 1);
      TRY(str_copy(a, (Str){key, (uint32_t)n}, &t->key));
      v->turns[found] = t;
      v->requests[found] = r->requests[i];
      (*occurrences)[found] = occurrence;
      v->turn_count++;
    } else {
      TurnFact *t = v->turns[found];
      Str key = t->key, uuid = t->turn_id.n ? t->turn_id : source->turn_id;
      bool same_last = source->last_ms.present == t->last_ms.present &&
          (!source->last_ms.present || source->last_ms.value == t->last_ms.value);
      if (later(source->last_ms, t->last_ms) ||
          (same_last && !t->end_ms.present && source->end_ms.present)) *t = *source;
      t->key = key; t->turn_id = uuid;
    }
    MaybeMs answer_at = r->reader_facts && r->answer_ms ? r->answer_ms[i] : source->last_ms;
    if (r->answers[i].n && (!v->answers[found].n || later(answer_at, v->answer_ms[found]))) {
      v->answers[found] = r->answers[i]; v->answer_ms[found] = answer_at;
    }
    Str *key;
    TRY(zero(a, 1, sizeof *key, alignof(Str), (void **)&key));
    *key = v->turns[found]->key;
    TRY(omap_put(&r->canonical_turns, source->key, key));
  }
  for (OmapEntry *p = r->tool_turns.first; p; p = p->next) {
    Str *key = omap_get(&r->canonical_turns, *(Str *)p->value);
    if (key) TRY(omap_put(&v->tool_turns, p->key, key));
  }
  return ERR_SUCCESS;
}
static Err tool_identity(Arena *a, const ClaudeToolFact *f, Str turn, Str *out) {
  JsonWriter w = {0};
  jsonw_raw(&w, "["); jsonw_string(&w, turn); jsonw_raw(&w, ",");
  jsonw_raw(&w, f->identified ? "true," : "false,");
  jsonw_string(&w, f->id); jsonw_raw(&w, "]");
  Err e = w.error;
  if (!e.code) e = str_copy(a, (Str){w.data, (uint32_t)w.length}, out);
  jsonw_free(&w); return e;
}
static Err merge_tools(Arena *a, ClaudeRecord *views, size_t n, ClaudeRecord *records, size_t count, Omap *groups) {
  Omap *indexes;
  TRY(zero(a, n, sizeof *indexes, alignof(Omap), (void **)&indexes));
  Err e = ERR_SUCCESS;
  for (size_t i = 0; i < count && !e.code; i++) {
      ClaudeRecord *r = &records[i];
      if (!r->reader_facts) continue;
      ClaudeRecord *v = omap_get(groups, r->id);
      if (v->reader_copies == 1) continue;
      Omap *tools = &indexes[v - views];
      for (size_t k = 0; k < r->tool_count && !e.code; k++) {
        ClaudeToolFact *f = &r->tool_facts[k];
        Str *turn = omap_get(&r->canonical_turns, f->turn), key;
        if (!turn) continue;
        e = tool_identity(a, f, *turn, &key);
        if (e.code) break;
        ClaudeToolFact *old = omap_get(tools, key);
        if (old) old->failed |= f->failed;
        else {
          e = zero(a, 1, sizeof *old, alignof(ClaudeToolFact), (void **)&old);
          if (!e.code) { *old = *f; old->turn = *turn; e = omap_put(tools, key, old); }
        }
      }
  }
  for (size_t j = 0; j < n; j++) {
    ClaudeRecord *v = &views[j];
    for (OmapEntry *p = indexes[j].first; p && !e.code; p = p->next) {
      ClaudeToolFact *f = p->value;
      for (size_t k = 0; k < v->turn_count; k++)
        if (str_equal(v->turns[k]->key, f->turn)) {
          e = claude_tool_count(a, &v->tools[k], f->name, f->failed); break;
        }
    }
    omap_destroy(&indexes[j]);
  }
  if (e.code) return e;
    /* CLCD1 cannot identify complementary tools. Preserve its known counts
     * conservatively, without adding mirrored aggregate snapshots twice. */
  for (size_t i = 0; i < count; i++) {
      ClaudeRecord *r = &records[i];
      if (r->reader_facts) continue;
      ClaudeRecord *v = omap_get(groups, r->id);
      if (v->reader_copies == 1) continue;
      for (size_t k = 0; k < r->turn_count; k++) {
        Str *turn = omap_get(&r->canonical_turns, r->turns[k]->key);
        for (size_t m = 0; turn && m < v->turn_count; m++)
          if (str_equal(v->turns[m]->key, *turn)) TRY(max_tools(a, &v->tools[m], &r->tools[k]));
      }
  }
  return ERR_SUCCESS;
}
Err claude_reader_reconcile(ClaudeRecord *records, size_t count, Corpus *c,
                            ClaudeRecord **out, size_t *out_count) {
  *out = NULL; *out_count = 0;
  if (!count) return ERR_SUCCESS;
  TRY(zero(&c->arena, count, sizeof **out, alignof(ClaudeRecord), (void **)out));
  size_t *capacities, **occurrences;
  TRY(zero(&c->arena, count, sizeof *capacities, alignof(size_t), (void **)&capacities));
  TRY(zero(&c->arena, count, sizeof *occurrences, alignof(size_t *), (void **)&occurrences));
  Omap groups = {0}; Err e = ERR_SUCCESS;
  for (size_t i = 0; i < count && !e.code; i++) {
    ClaudeRecord *r = &records[i], *v = omap_get(&groups, r->id);
    if (!v) {
      v = &(*out)[(*out_count)++];
      *v = *r;
      v->reader_copies = 1;
      e = omap_put(&groups, r->id, v);
      if (e.code) break;
    } else {
      v->reader_copies++;
      bool newest = later(r->last_ms, v->last_ms);
      if (newest) {
        v->meta = r->meta;
        if (r->custom_title.n) v->custom_title = r->custom_title;
        if (r->ai_title.n) v->ai_title = r->ai_title;
      }
      if (r->first_ms.present && (!v->first_ms.present || r->first_ms.value < v->first_ms.value)) v->first_ms = r->first_ms;
      if (newest) v->last_ms = r->last_ms;
      if (r->key.mtime_ns > v->key.mtime_ns) v->key.mtime_ns = r->key.mtime_ns;
      if (v->retained && !r->retained) { v->key.path = r->key.path; v->config_dir = r->config_dir; }
      else if (r->retained == v->retained && r->config_dir.p &&
               (!v->config_dir.p || str_compare(r->config_dir, v->config_dir) < 0)) v->config_dir = r->config_dir;
      v->retained &= r->retained;
    }
  }
  for (size_t i = 0; i < *out_count; i++) {
    ClaudeRecord *v = &(*out)[i];
    if (v->reader_copies == 1) continue;
    v->turns = NULL; v->requests = NULL; v->answers = NULL; v->answer_ms = NULL; v->tools = NULL;
    v->turn_count = 0; v->tool_turns = (Omap){0}; v->canonical_turns = (Omap){0};
  }
  for (size_t i = 0; i < count && !e.code; i++) {
    ClaudeRecord *r = &records[i], *v = omap_get(&groups, r->id);
    omap_destroy(&r->canonical_turns);
    if (v->reader_copies == 1) continue;
    size_t group = (size_t)(v - *out);
    e = merge_record(&c->arena, v, &capacities[group], r, &occurrences[group]);
  }
  if (!e.code) e = merge_tools(&c->arena, *out, *out_count, records, count, &groups);
  omap_destroy(&groups);
  return e;
}
void claude_reader_views_destroy(ClaudeRecord *views, size_t count) {
  for (size_t i = 0; i < count; i++) {
    if (views[i].reader_copies == 1) continue;
    omap_destroy(&views[i].tool_turns);
    for (size_t j = 0; j < views[i].turn_count; j++) {
      omap_destroy(&views[i].tools[j].mcp); omap_destroy(&views[i].tools[j].other);
    }
  }
}
