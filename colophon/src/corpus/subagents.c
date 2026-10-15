#include "subagents.h"
#include "parse/record.h"
#include "util/events.h"
#include "util/sort.h"
#include <math.h>
#include <string.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
Err corpus_strings_add(Arena *arena, CorpusStrings *list, Str value) {
  return record_append(arena, (void **)&list->items, &list->count,
                       &list->capacity, sizeof value, &value);
}
static Str usable(JScalar s) {
  return s.kind == JS_STRING && metadata_text(s.value.s) ? s.value.s : (Str){0};
}
/* History identity tests Python whitespace, but keeps the raw spelling. */
static Str identity(const SessionModel *s) {
  JScalar id = s->meta_input.meta_id;
  return s->has_meta && id.kind == JS_STRING && str_trim(id.value.s, true).n
             ? id.value.s : (Str){0};
}
static Str dbtext(const SessionModel *s, MetadataColumn column) {
  if (!s->db_info || s->db_info->values[column].kind != META_TEXT)
    return (Str){0};
  Str v = s->db_info->values[column].value.bytes;
  return metadata_text(v) ? v : (Str){0};
}
MaybeNum corpus_finite(JScalar s, const char *site) {
  MaybeNum n = {0};
  if (s.kind == JS_INT)
    n = (MaybeNum){true, {.i = s.value.i}};
  else if (s.kind == JS_FLOAT && isfinite(s.value.f))
    n = (MaybeNum){true, {.is_float = true, .f = s.value.f}};
  if (n.present)
    n.present = pynum_timing(n.value, site, &n.value);
  return n;
}
static TurnModel *turn(SessionModel *s, Str id) {
  if (!metadata_text(id))
    return NULL;
  for (size_t i = 0; i < s->turn_count; i++)
    if (str_equal(s->turns[i].id, id))
      return &s->turns[i];
  return NULL;
}
static MaybeNum spawn_clock(const SessionModel *p, size_t i) {
  if (p->input->typed_clocks)
    return corpus_finite(p->input->spawn_clocks[i], "subagent.spawn.at_ms");
  MaybeMs m = p->record->spawns[i].at_ms;
  return (MaybeNum){m.present, {.i = m.value}};
}
static void spawn(SessionModel *s, SessionModel *p, int64_t snapshot) {
  const LogRecord *r = p->record;
  Str key = {0};
  bool conflict = false;
  for (size_t i = 0; i < r->activity_count; i++) {
    ActivityLink a = r->activities[i];
    if (str_equal(a.kind, STR_LIT("started")) && str_equal(a.child_id, s->id) &&
        turn(p, a.turn_key)) {
      if (key.p && !str_equal(key, a.turn_key))
        conflict = true;
      key = a.turn_key;
    }
  }
  if (key.p && !conflict) {
    s->spawn_turn = key;
    s->link_method = STR_LIT("activity");
    return;
  }
  if (s->agent_path.p && s->created_at_ms.present) {
    MaybeNum latest = {0};
    key = (Str){0};
    conflict = false;
    for (size_t i = 0; i < r->spawn_count; i++) {
      SpawnLink a = r->spawns[i];
      MaybeNum clock = spawn_clock(p, i);
      if (!str_equal(a.task_name, s->agent_path) || !clock.present ||
          pynum_compare(clock.value, s->created_at_ms.value) > 0)
        continue;
      int order = latest.present ? pynum_compare(clock.value, latest.value) : 1;
      if (order < 0)
        continue;
      if (order > 0) {
        latest = clock;
        key = a.turn_key;
        conflict = !turn(p, key);
      } else if (!turn(p, a.turn_key) || !str_equal(key, a.turn_key))
        conflict = true;
    }
    if (latest.present && !conflict) {
      s->spawn_turn = key;
      s->link_method = STR_LIT("spawn_call");
      return;
    }
  }
  if (s->has_depth && s->depth == 1) {
    for (size_t i = 0; i < s->record->usage_count; i++) {
      UsageRecord u = s->record->usage_records[i];
      Str root = usable(u.root_turn_id);
      if (!str_equal(usable(u.thread_id), s->id) || !root.p)
        continue;
      /* Dict semantics: last duplicate logged ID wins. */
      key = (Str){0};
      for (size_t j = 0; j < r->turn_count; j++)
        if (metadata_text(r->turns[j]->turn_id) &&
            str_equal(root, r->turns[j]->turn_id) && turn(p, r->turns[j]->key))
          key = r->turns[j]->key;
      if (key.p) {
        s->spawn_turn = key;
        s->link_method = STR_LIT("root_turn_id");
        return;
      }
    }
  }
  if (s->created_at_ms.present) {
    size_t matches = 0;
    for (size_t i = 0; i < p->turn_count; i++) {
      TurnModel *t = &p->turns[i];
      MaybeNum end = t->end_ms;
      if (str_equal(t->status, STR_LIT("running")))
        end = (MaybeNum){true, {.i = snapshot}};
      else if (str_equal(t->status, STR_LIT("abandoned"))) {
        end = (MaybeNum){0};
        for (size_t j = 0; j < r->turn_count; j++)
          if (str_equal(r->turns[j]->key, t->id))
            end = (MaybeNum){r->turns[j]->last_ms.present,
                             {.i = r->turns[j]->last_ms.value}};
      }
      if (t->start_ms.present && end.present &&
          pynum_compare(t->start_ms.value, s->created_at_ms.value) <= 0 &&
          pynum_compare(s->created_at_ms.value, end.value) <= 0) {
        key = t->id;
        matches++;
      }
    }
    if (matches == 1) {
      s->spawn_turn = key;
      s->link_method = STR_LIT("inferred");
    }
  }
}
static bool used(const SessionModel *s, const SessionModel *p, Str key) {
  const LogRecord *r = p->record;
  for (size_t i = 0; i < r->activity_count; i++)
    if (str_equal(r->activities[i].kind, STR_LIT("interacted")) &&
        str_equal(r->activities[i].child_id, s->id) &&
        str_equal(r->activities[i].turn_key, key))
      return true;
  for (size_t i = 0; i < r->receiver_count; i++)
    if (str_equal(r->receivers[i].child_id, s->id) &&
        str_equal(r->receivers[i].turn_key, key))
      return true;
  if (!s->agent_path.p)
    return false;
  size_t slash = SIZE_MAX;
  for (size_t i = 0; i < s->agent_path.n; i++)
    if (s->agent_path.p[i] == '/')
      slash = i;
  for (size_t i = 0; i < r->target_count; i++) {
    Str target = r->targets[i].target;
    if (!metadata_text(target) || !str_equal(r->targets[i].turn_key, key))
      continue;
    if (str_equal(target, s->agent_path))
      return true;
    if (target.p[0] != '/' && slash != SIZE_MAX &&
        slash + 1 + target.n == s->agent_path.n &&
        !memcmp(s->agent_path.p + slash + 1, target.p, target.n))
      return true;
  }
  return false;
}
static int child_order(const void *a, const void *b, void *ctx) {
  Omap *map = ctx;
  SessionModel *x = omap_get(map, *(const Str *)a),
               *y = omap_get(map, *(const Str *)b);
  if (x->start_ms.present != y->start_ms.present)
    return x->start_ms.present ? -1 : 1;
  return x->start_ms.present ? (x->start_ms.value > y->start_ms.value) -
                                   (x->start_ms.value < y->start_ms.value)
                             : 0;
}
Err corpus_children_order(SessionModel *s, Omap *by_id) {
  return stable_sort(s->children.items, s->children.count, sizeof(Str),
                     child_order, by_id);
}
Err corpus_graph_break_cycles(Arena *arena, Omap *identified) {
  SessionModel **chain;
  TRY(arena_alloc(arena, (identified->size + 1) * sizeof *chain,
                  _Alignof(SessionModel *), (void **)&chain));
  for (OmapEntry *q = identified->first; q; q = q->next) {
    SessionModel *s = q->value;
    s->graph_visit = s->graph_position = 0;
  }
  size_t visit = 0;
  for (OmapEntry *q = identified->first; q; q = q->next) {
    SessionModel *s = q->value;
    size_t count = 0;
    visit++;
    while (s && !s->graph_visit) {
      s->graph_visit = visit;
      s->graph_position = count;
      chain[count++] = s;
      s = omap_get(identified, s->parent_id);
    }
    if (s && s->graph_visit == visit)
      for (size_t i = s->graph_position; i < count; i++)
        chain[i]->parent_id = (Str){0};
  }
  return ERR_SUCCESS;
}
Err corpus_link_subagents(Corpus *c, const CodexMetadata *metadata,
                          int64_t snapshot) {
  c->linked = true;
  Omap identified = {0}, by_id = {0};
  Err e = ERR_SUCCESS;
  c->orphaned_subagents.count = c->inferred_links.count = 0;
  SessionModel **chain = NULL;
  e = arena_alloc(&c->arena, (c->sessions.size + 1) * sizeof *chain,
                  _Alignof(SessionModel *), (void **)&chain);
  if (e.code)
    goto done;
  for (OmapEntry *q = c->sessions.first; q; q = q->next) {
    SessionModel *s = q->value;
    const SessionMeta *m = &s->meta;
    s->children.count = s->interaction_turns.count = 0;
    s->flags &= ~(F_ORPHAN | F_FORKED);
    s->parent_id = s->spawn_turn = s->link_method = (Str){0};
    s->kind = s->is_subagent ? STR_LIT("subagent") : STR_LIT("session");
    s->has_link = s->is_subagent;
    s->has_depth = m->depth.kind == JS_INT && m->depth.value.i >= 0;
    s->depth = s->has_depth ? m->depth.value.i : 0;
    s->agent_path = usable(m->agent_path);
    if (!s->agent_path.p)
      s->agent_path = dbtext(s, META_AGENT_PATH);
    s->created_at_ms =
        s->meta_input.typed_clocks
            ? corpus_finite(s->meta_input.creation, "subagent.created_at_ms")
            : (MaybeNum){m->created_at_ms.present,
                         {.i = m->created_at_ms.value}};
    s->forked_from = !s->is_subagent && metadata_text(m->forked_from_id)
                         ? m->forked_from_id
                         : (Str){0};
    s->graph_visit = 0;
    s->graph_position = 0;
    for (size_t i = 0; i < s->turn_count; i++)
      s->turns[i].spawned.count = s->turns[i].used.count = 0;
    Str identifier = identity(s);
    if (identifier.p) {
      e = omap_put(&identified, identifier, s);
      if (e.code)
        goto done;
    }
    e = omap_put(&by_id, s->id, s);
    if (e.code)
      goto done;
    if (!s->is_subagent) {
      s->has_depth = true;
      continue;
    }
    Str *edge =
        identifier.p ? omap_get(&metadata->spawn_parents, identifier) : NULL;
    s->parent_id =
        edge && metadata_text(*edge) ? *edge : usable(m->parent_thread_id);
  }
  e = corpus_graph_break_cycles(&c->arena, &identified);
  if (e.code)
    goto done;
  for (OmapEntry *q = c->sessions.first; q; q = q->next) {
    SessionModel *s = q->value;
    if (!s->is_subagent)
      continue;
    SessionModel *p =
        identity(s).p ? omap_get(&identified, s->parent_id) : NULL;
    if (!p) {
      s->kind = STR_LIT("orphan");
      s->flags |= F_ORPHAN;
      e = corpus_strings_add(&c->arena, &c->orphaned_subagents, s->id);
    } else
      e = corpus_strings_add(&c->arena, &p->children, s->id);
    if (e.code)
      goto done;
    Str fork = s->meta.forked_from_id;
    if (metadata_text(fork) && str_equal(fork, s->parent_id))
      s->flags |= F_FORKED;
  }
  for (OmapEntry *q = c->sessions.first; q; q = q->next) {
    SessionModel *s = q->value;
    size_t count = 0;
    while (s && !s->has_depth) {
      chain[count++] = s;
      s = omap_get(&identified, s->parent_id);
    }
    if (s) {
      __int128 depth = s->depth;
      while (count) {
        SessionModel *child = chain[--count];
        child->depth = ++depth;
        child->has_depth = true;
        if (depth > INT64_MAX)
          event_note("int128_payload_sum", "session.depth", 1);
      }
    }
  }
  for (OmapEntry *q = c->sessions.first; q; q = q->next) {
    SessionModel *s = q->value;
    e = corpus_children_order(s, &by_id);
    if (e.code)
      goto done;
    if (!s->is_subagent || (s->flags & F_ORPHAN))
      continue;
    SessionModel *p = omap_get(&identified, s->parent_id);
    spawn(s, p, snapshot);
    if (str_equal(s->link_method, STR_LIT("inferred"))) {
      e = corpus_strings_add(&c->arena, &c->inferred_links, s->id);
      if (e.code)
        goto done;
    }
    for (size_t i = 0; i < p->turn_count; i++) {
      TurnModel *t = &p->turns[i];
      if (str_equal(t->id, s->spawn_turn))
        e = corpus_strings_add(&c->arena, &t->spawned, s->id);
      else if (metadata_text(t->id) && used(s, p, t->id)) {
        e = corpus_strings_add(&c->arena, &s->interaction_turns, t->id);
        if (!e.code)
          e = corpus_strings_add(&c->arena, &t->used, s->id);
      }
      if (e.code)
        goto done;
    }
  }
done:
  omap_destroy(&identified);
  omap_destroy(&by_id);
  return e;
}
