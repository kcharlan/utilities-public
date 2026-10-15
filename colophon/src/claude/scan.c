#define _DARWIN_C_SOURCE
#include "scan.h"
#include "store.h"
#include "metadata.h"
#include "corpus/subagents.h"
#include "parse/record.h"
#include "testing/hooks.h"
#include "util/fileio.h"
#include "util/json_number.h"
#include "util/sort.h"
#include "util/time.h"
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
static Str str(const char *p) { return (Str){p, (uint32_t)strlen(p)}; }
static Err join(Arena *a, const char *parent, const char *name, Str *out) {
  size_t n = strlen(parent) + strlen(name) + 2;
  char *p;
  TRY(arena_alloc(a, n, 1, (void **)&p));
  snprintf(p, n, "%s/%s", parent, name);
  *out = str(p);
  return ERR_SUCCESS;
}
static bool readable(const char *p) {
  struct stat st;
  return !stat(p, &st) && S_ISDIR(st.st_mode) && !access(p, R_OK | X_OK);
}
static Err path(Arena *a, const char *raw, Str *out) {
  char *absolute = NULL;
  TRY(file_codex_path_key(raw, &absolute));
  char resolved[PATH_MAX];
  Err e =
      str_copy(a, str(realpath(absolute, resolved) ? resolved : absolute), out);
  free(absolute);
  return e;
}
static Err root(ClaudeScan *s, Str p, ClaudeRootKind kind, Str config) {
  Str normalized;
  TRY(path(&s->arena, p.p, &normalized));
  Str resume = {0};
  if (config.p)
    TRY(path(&s->arena, config.p, &resume));
  for (size_t i = 0; i < s->root_count; i++)
    if (str_equal(s->roots[i].path, normalized)) {
      if (resume.p && (!s->roots[i].resume_config_dir.p ||
                       str_compare(resume, s->roots[i].resume_config_dir) < 0))
        s->roots[i].resume_config_dir = resume;
      return ERR_SUCCESS;
    }
  ClaudeRoot *next;
  TRY(arena_alloc(&s->arena, (s->root_count + 1) * sizeof *next,
                  _Alignof(ClaudeRoot), (void **)&next));
  if (s->root_count)
    memcpy(next, s->roots, s->root_count * sizeof *next);
  s->roots = next;
  bool present = readable(normalized.p);
  next[s->root_count++] = (ClaudeRoot){.path = normalized,
                                       .resume_config_dir = resume,
                                       .kind = kind,
                                       .present = present,
                                       .complete = true};
  s->present |= present;
  return ERR_SUCCESS;
}
static yyjson_val *get(yyjson_val *v, const char *name) {
  return obj_get_last(v, str(name));
}
static bool nonempty(yyjson_val *v) {
  return yyjson_is_str(v) && yyjson_get_len(v) > 0;
}
static Err history_line(void *context, const ReaderRawLine *line,
                        const JsonRead *json) {
  ClaudeScan *s = context;
  if (!line->bytes.n)
    return ERR_SUCCESS;
  yyjson_val *v = json->doc ? yyjson_doc_get_root(json->doc) : NULL,
             *stamp = get(v, "timestamp");
  int64_t ms;
  PyNum n;
  bool number = json_number(stamp, "claude.history", &n);
  bool timestamp =
      number &&
      (!n.is_float
           ? time_ms_from_i64(n.i, true, "claude.history", &ms)
           : time_truncate_ms(n.f, "claude.history", &ms) && n.f == (double)ms);
  if (nonempty(get(v, "sessionId")) && yyjson_is_str(get(v, "display")) &&
      yyjson_is_str(get(v, "project")) && timestamp) {
    ClaudeHistory h={.at_ms=ms};
    Str *fields[]={&h.id,&h.display,&h.project};
    const char *names[]={"sessionId","display","project"};
    for(size_t i=0;i<3;i++) {
      yyjson_val *value=get(v,names[i]);
      TRY(str_copy(&s->arena,(Str){yyjson_get_str(value),(uint32_t)yyjson_get_len(value)},fields[i]));
    }
    TRY(record_append(&s->arena,(void **)&s->history,&s->history_usable,
                      &s->history_capacity,sizeof h,&h));
  } else
    s->history_malformed++;
  return ERR_SUCCESS;
}
static Err decoded(void *context, const ReaderRawLine *line,
                   const JsonRead *json) {
  return history_line(context, line, json);
}
Err claude_inspect(const Args *args, ClaudeScan *s) {
  s->disabled = args->no_claude;
  const char *home = getenv("HOME");
  if (!home || !*home)
    return err_make(ERR_INVALID,
                    "HOME is unavailable for Claude source selection");
  const char *selected =
      args->claude_home ? args->claude_home : getenv("CLAUDE_CONFIG_DIR");
  bool custom = selected && *selected;
  Str config;
  if (custom) {
    TRY(path(&s->arena, selected, &config));
  } else
    TRY(join(&s->arena, home, ".claude", &config));
  s->config_root = config;
  TRY(join(&s->arena, config.p, "history.jsonl", &s->history_path));
  if (args->claude_desktop_dir) {
    char *expanded = NULL;
    TRY(file_expand_path(args->claude_desktop_dir, &expanded));
    Err e = path(&s->arena, expanded, &s->desktop_dir);
    free(expanded);
    if (e.code)
      return e;
  } else
    TRY(join(&s->arena, home, "Library/Application Support/Claude",
             &s->desktop_dir));
  Str p;
  if (!custom) {
    Str xdg;
    TRY(join(&s->arena, home, ".config/claude", &xdg));
    TRY(join(&s->arena, xdg.p, "projects", &p));
    TRY(root(s, p, CLAUDE_PROJECTS, xdg));
  }
  TRY(join(&s->arena, config.p, "projects", &p));
  TRY(root(s, p, CLAUDE_PROJECTS, config));
  if (!custom) {
    const char *names[] = {"local-agent-mode-sessions", "claude-code-sessions"};
    for (size_t i = 0; i < 2; i++) {
      TRY(join(&s->arena, s->desktop_dir.p, names[i], &p));
      TRY(root(s, p, CLAUDE_DESKTOP, (Str){0}));
    }
  }
  TRY(join(&s->arena, home, ".claude-swap-backup/sessions", &p));
  TRY(root(s, p, CLAUDE_SWAP, (Str){0}));
  if (s->disabled) {
    s->present = false;
    return ERR_SUCCESS;
  }
  struct stat st;
  if (!stat(s->history_path.p, &st) && S_ISREG(st.st_mode) &&
      !access(s->history_path.p, R_OK)) {
    DiscoveredLog key = {.path = s->history_path, .size = st.st_size};
    ReaderResult result = {0};
    ReaderCallbacks cb = {.context = s, .decoded_line = decoded};
    Err e = reader_read_log(&key, &cb, &result);
    reader_result_destroy(&result);
    if (e.code == ERR_NOMEM)
      return e;
    if (!e.code && s->history_usable)
      s->present = true;
  }
  return ERR_SUCCESS;
}
static Err skipped(ClaudeScan *s, Str p) {
  SkippedFile value = {p, STR_LIT("unreadable")};
  return record_append(&s->arena, (void **)&s->skipped, &s->skipped_count,
                       &s->skipped_capacity, sizeof value, &value);
}
static Err traversal_error(ClaudeScan *s, ClaudeRoot *r, Str p) {
  r->complete = false;
  return skipped(s, p);
}
/* Missing/non-directory candidates and excluded symlinks are normal locator
 * outcomes. Other stat/access failures make the enclosing scan incomplete. */
static Err source_directory(ClaudeScan *s, ClaudeRoot *r, Str p, bool follow,
                            bool *present) {
  *present = false;
  struct stat st;
  int status = follow ? stat(p.p, &st) : lstat(p.p, &st);
  if (status) {
    if (errno == ENOENT || errno == ENOTDIR)
      return ERR_SUCCESS;
    return traversal_error(s, r, p);
  }
  if (!S_ISDIR(st.st_mode))
    return ERR_SUCCESS;
  if (access(p.p, R_OK | X_OK))
    return traversal_error(s, r, p);
  *present = true;
  return ERR_SUCCESS;
}
typedef struct {
  Str *items;
  size_t count, capacity;
} Children;
static int order(const void *a, const void *b, void *ctx) {
  (void)ctx;
  return str_compare(*(const Str *)a, *(const Str *)b);
}
static Err children(ClaudeScan *s, ClaudeRoot *r, Str parent, Children *out) {
  DIR *d = opendir(parent.p);
  if (!d) {
    r->complete = false;
    return skipped(s, parent);
  }
  Err e = ERR_SUCCESS;
  struct dirent *entry;
  for (;;) {
    errno = 0;
    entry = readdir(d);
    if (!entry) {
      if (errno) {
        r->complete = false;
        e = skipped(s, parent);
      }
      break;
    }
    if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
      continue;
    Str p;
    e = join(&s->arena, parent.p, entry->d_name, &p);
    if (e.code)
      break;
    if (discovery_hidden(p.p))
      continue;
    e = record_append(&s->arena, (void **)&out->items, &out->count,
                      &out->capacity, sizeof p, &p);
    if (e.code)
      break;
  }
  if (closedir(d) && !e.code) {
    r->complete = false;
    e = skipped(s, parent);
  }
  if (!e.code)
    e = stable_sort(out->items, out->count, sizeof *out->items, order, NULL);
  return e;
}
static bool jsonl(Str path) {
  return path.n > 6 && !strncasecmp(path.p + path.n - 6, ".jsonl", 6);
}
static Err walk_projects(ClaudeScan *s, ClaudeRoot *r, Str p,
                         volatile sig_atomic_t *flag, Omap *seen) {
  if (flag && *flag)
    return err_make(ERR_IO, "interrupted");
  Children list = {0};
  TRY(children(s, r, p, &list));
  for (size_t i = 0; i < list.count; i++) {
    Str child = list.items[i];
    struct stat st;
    if (lstat(child.p, &st)) {
      r->complete = false;
      TRY(skipped(s, child));
      continue;
    }
    if (S_ISDIR(st.st_mode)) {
      if (!discovery_package(child.p))
        TRY(walk_projects(s, r, child, flag, seen));
      continue;
    }
    if (!S_ISREG(st.st_mode) || !jsonl(child))
      continue;
    if (omap_get(seen, child))
      continue;
    TRY(omap_put(seen, child, (void *)1));
    if(st.st_size)s->logs++;
    if (s->count == s->capacity) {
      size_t n = s->capacity ? s->capacity * 2 : 16;
      ClaudeRecord *next = realloc(s->records, n * sizeof *next);
      if (!next)
        return err_make(ERR_NOMEM, "Claude records allocation failed");
      s->records = next;
      s->capacity = n;
    }
    ClaudeRecord *record = &s->records[s->count];
    DiscoveredLog key = {.path = child,
                         .size = st.st_size,
                         .mtime_ns =
                             (int64_t)st.st_mtimespec.tv_sec * 1000000000 +
                             st.st_mtimespec.tv_nsec,
                         .stat_ok = true,
                         .device = st.st_dev,
                         .inode = st.st_ino};
    bool hit=false;
    Err e=claude_store_get(s->store,&key,record,&hit);
    if(!e.code&&!hit)e=claude_parse(&key,r->path,r->resume_config_dir,record);
    else if(!e.code) {
      record->parent_agent=record->tool_use_id=record->description=record->agent_type=(Str){0};
      record->has_spawn_depth=false; record->spawn_depth=0;
      e=claude_sidecar_load(record);
    }
    if (e.code) {
      claude_record_destroy(record);
      if (e.code != ERR_IO)
        return e;
      r->complete = false;
      TRY(skipped(s, child));
    } else {
      s->count++;
      if(hit)s->cached++;else s->parsed++;
    }
  }
  return ERR_SUCCESS;
}
static bool desktop_skip(Str p) {
  const char *name = strrchr(p.p, '/') + 1;
  const char *names[] = {".build",       ".git",    "build", "DerivedData",
                         "node_modules", "outputs", "target"};
  for (size_t i = 0; i < sizeof names / sizeof *names; i++)
    if (!strcmp(name, names[i]))
      return true;
  return false;
}
static Err walk_desktop(ClaudeScan *s, ClaudeRoot *r, Str p, int depth,
                        volatile sig_atomic_t *flag, Omap *seen) {
  Str config, projects;
  TRY(join(&s->arena, p.p, ".claude", &config));
  TRY(join(&s->arena, config.p, "projects", &projects));
  /* Locator stores are descendants of the selected container, rather than
   * independently selected symlink roots. Preserve D8's lstat boundary. */
  bool has_config = false, has_projects = false;
  TRY(source_directory(s, r, config, false, &has_config));
  if (has_config) {
    TRY(source_directory(s, r, projects, false, &has_projects));
    if (has_projects)
      TRY(walk_projects(s, r, projects, flag, seen));
  }
  if (depth >= 4)
    return ERR_SUCCESS;
  Children list = {0};
  TRY(children(s, r, p, &list));
  for (size_t i = 0; i < list.count; i++) {
    struct stat st;
    Str child = list.items[i];
    if (desktop_skip(child))
      continue;
    if (cp_fault("claude_locator_lstat") || lstat(child.p, &st)) {
      TRY(traversal_error(s, r, child));
      continue;
    }
    if (S_ISDIR(st.st_mode) && !discovery_package(child.p))
      TRY(walk_desktop(s, r, child, depth + 1, flag, seen));
  }
  return ERR_SUCCESS;
}
Err claude_scan(ClaudeScan *s, volatile sig_atomic_t *flag) {
  if (s->disabled)
    return ERR_SUCCESS;
  Omap seen = {0};
  Err e = ERR_SUCCESS;
  for (size_t i = 0; i < s->root_count && !e.code; i++) {
    ClaudeRoot *r = &s->roots[i];
    if (!r->present) {
      if(!claude_path_deleted(r->path.p))TRY(traversal_error(s,r,r->path));
      continue;
    }
    if (r->kind == CLAUDE_PROJECTS)
      e = walk_projects(s, r, r->path, flag, &seen);
    else if (r->kind == CLAUDE_DESKTOP)
      e = walk_desktop(s, r, r->path, 0, flag, &seen);
    else {
      Children list = {0};
      e = children(s, r, r->path, &list);
      for (size_t j = 0; j < list.count && !e.code; j++) {
        const char *name = strrchr(list.items[j].p, '/') + 1;
        char *end;
        long n = strtol(name, &end, 10);
        if (n <= 0 || end == name || *end != '-')
          continue;
        Str projects, resolved;
        e = join(&s->arena, list.items[j].p, "projects", &projects);
        bool present = false;
        if (!e.code)
          e = source_directory(s, r, projects, true, &present);
        if (!e.code && present) {
          e = path(&s->arena, projects.p, &resolved);
          if (!e.code)
            e = walk_projects(s, r, resolved, flag, &seen);
        }
      }
    }
  }
  omap_destroy(&seen);
  if(!e.code)e=claude_scan_aliases(s);
  return e;
}
Err claude_scan_aliases(ClaudeScan *s) {
  Err e=ERR_SUCCESS;
    for (size_t i = 0; i < s->count; i++) {
      ClaudeRecord *record = &s->records[i];
      if(record->parent_session.p)continue;
      for (size_t j = 0; j < record->aliases.count; j++) {
        Str alias = record->aliases.items[j];
        CorpusStrings *owners = omap_get(&s->history_aliases, alias);
        if (!owners) {
          e = arena_alloc(&s->arena, sizeof *owners, _Alignof(CorpusStrings),
                          (void **)&owners);
          if (e.code)
            return e;
          *owners = (CorpusStrings){0};
          e = omap_put(&s->history_aliases, alias, owners);
          if (e.code)
            return e;
        }
        bool seen_owner = false;
        for (size_t k = 0; k < owners->count; k++)
          seen_owner |= str_equal(owners->items[k], record->id);
        if (!seen_owner) {
          e = corpus_strings_add(&s->arena, owners, record->id);
          if (e.code)
            return e;
        }
      }
    }
  return e;
}
void claude_scan_destroy(ClaudeScan *s) {
  for (size_t i = 0; i < s->count; i++)
    claude_record_destroy(&s->records[i]);
  free(s->records);
  omap_destroy(&s->history_aliases);
  omap_destroy(&s->history_conflicts);
  arena_destroy(&s->arena);
  *s = (ClaudeScan){0};
}
