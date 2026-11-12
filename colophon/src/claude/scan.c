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
#include "util/events.h"
#include "util/jobpool.h"
#include "scan/scan.h"
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
/* Root locators may remain symlinks after their target is removed. Resolve
 * existing links/ancestors even then, without traversing any discovered child.
 * Permission errors and link loops deliberately retain the lexical identity. */
static Err missing_root(const char *raw, unsigned links, char **out) {
  char resolved[PATH_MAX];
  if (realpath(raw, resolved)) {
    *out = strdup(resolved);
    return *out ? ERR_SUCCESS : err_make(ERR_NOMEM, "Claude root allocation failed");
  }
  if (errno != ENOENT || links >= 40 || !strcmp(raw, "/"))
    return file_codex_path_key(raw, out);
  struct stat st;
  if (!lstat(raw, &st) && S_ISLNK(st.st_mode)) {
    char target[PATH_MAX];
    ssize_t n = readlink(raw, target, sizeof target - 1);
    if (n < 0 || (size_t)n >= sizeof target - 1)
      return file_codex_path_key(raw, out);
    target[n] = 0;
    char joined[PATH_MAX];
    const char *slash = strrchr(raw, '/');
    int used = target[0] == '/' ? snprintf(joined, sizeof joined, "%s", target)
        : snprintf(joined, sizeof joined, "%.*s/%s", (int)(slash - raw), raw, target);
    if (used < 0 || (size_t)used >= sizeof joined)
      return file_codex_path_key(raw, out);
    char *normalized = NULL;
    TRY(file_codex_path_key(joined, &normalized));
    Err e = missing_root(normalized, links + 1, out);
    free(normalized);
    return e;
  }
  char *parent = strdup(raw);
  if (!parent) return err_make(ERR_NOMEM, "Claude root allocation failed");
  char *slash = strrchr(parent, '/');
  char *name = slash + 1;
  char *base = NULL;
  if (slash == parent) base = strdup("/");
  else {
    *slash = 0;
    Err e = missing_root(parent, links, &base);
    if (e.code) { free(parent); return e; }
  }
  if (!base) { free(parent); return err_make(ERR_NOMEM, "Claude root allocation failed"); }
  size_t size = strlen(base) + strlen(name) + 2;
  char *joined = malloc(size);
  if (!joined) { free(base); free(parent); return err_make(ERR_NOMEM, "Claude root allocation failed"); }
  snprintf(joined, size, "%s/%s", base, name);
  Err e = file_codex_path_key(joined, out);
  free(joined); free(base); free(parent);
  return e;
}
static Err path(Arena *a, const char *raw, Str *out) {
  char *absolute = NULL;
  TRY(file_codex_path_key(raw, &absolute));
  char *resolved = NULL;
  Err e = missing_root(absolute, 0, &resolved);
  if (!e.code) e = str_copy(a, str(resolved), out);
  free(resolved);
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
typedef struct {
  DiscoveredLog key;
  ClaudeRoot *root;
  bool skip, hit;
  Err result;
  ClaudeRecord record;
  EventCapture before, events;
} ScanJob;
typedef struct {
  ScanJob *jobs;
  size_t count, capacity;
  ClaudeRoot *root;
  EventCapture pending;
} Walk;
static _Thread_local Walk *walking;
static Err queue(Walk *walk, ScanJob job) {
  event_capture_end();
  if (walk->count == walk->capacity) {
    size_t n = walk->capacity ? walk->capacity * 2 : 16;
    ScanJob *next = realloc(walk->jobs, n * sizeof *next);
    if (!next) { event_capture_begin(&walk->pending); return err_make(ERR_NOMEM, "Claude jobs allocation failed"); }
    walk->jobs = next; walk->capacity = n;
  }
  job.before = walk->pending; walk->pending = (EventCapture){0};
  walk->jobs[walk->count++] = job;
  event_capture_begin(&walk->pending);
  return ERR_SUCCESS;
}
static Err skipped(ClaudeScan *s, Str p) {
  if (walking) return queue(walking, (ScanJob){.key.path=p, .root=walking->root, .skip=true});
  SkippedFile value = {p, STR_LIT("unreadable")};
  return record_append(&s->arena, (void **)&s->skipped, &s->skipped_count,
                       &s->skipped_capacity, sizeof value, &value);
}
static Err traversal_error(ClaudeScan *s, ClaudeRoot *r, Str p) {
  if (!walking) r->complete = false;
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
  DIR *d = cp_fault("claude_directory_io") ? NULL : opendir(parent.p);
  if (!d) {
    if (!walking) r->complete = false;
    return skipped(s, parent);
  }
  Err e = ERR_SUCCESS;
  struct dirent *entry;
  for (;;) {
    errno = 0;
    entry = readdir(d);
    if (!entry) {
      if (errno) {
        if (!walking) r->complete = false;
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
    if (!walking) r->complete = false;
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
      if (!walking) r->complete = false;
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
    if (cp_fault("claude_discovery"))
      return err_make(ERR_NOMEM, "Claude discovery failure");
    TRY(omap_put(seen, child, (void *)1));
    DiscoveredLog key = {.path = child,
                         .size = st.st_size,
                         .mtime_ns =
                             (int64_t)st.st_mtimespec.tv_sec * 1000000000 +
                             st.st_mtimespec.tv_nsec,
                         .stat_ok = true,
                         .device = st.st_dev,
                         .inode = st.st_ino};
    TRY(queue(walking, (ScanJob){.key=key, .root=r}));
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
typedef struct { ClaudeScan *scan; Walk *walk; size_t collected; } ScanWork;
static Err scan_work(size_t i, void *context) {
  ScanWork *w = context; ScanJob *job = &w->walk->jobs[i];
  if (job->skip) return ERR_SUCCESS;
  event_capture_begin(&job->events);
  Err e = (i == 0 && cp_fault("claude_log_io_first")) ||
          (i == 2 && cp_fault("claude_log_io_third"))
      ? err_make(ERR_IO, "synthetic Claude read failure")
      : claude_store_get(w->scan->store,&job->key,&job->record,&job->hit);
  if (!e.code && !job->hit)
    e=claude_parse(&job->key,job->root->path,job->root->resume_config_dir,&job->record);
  else if (!e.code) {
    job->record.parent_agent=job->record.tool_use_id=job->record.description=job->record.agent_type=(Str){0};
    job->record.has_spawn_depth=false; job->record.spawn_depth=0;
    e=claude_sidecar_load(&job->record);
  }
  event_capture_end();
  return e;
}
static Err scan_collect(size_t i, Err e, void *context) {
  ScanWork *w = context; ScanJob *job = &w->walk->jobs[i];
  job->result=e; w->collected=i+1;
  return e.code && e.code != ERR_IO ? e : ERR_SUCCESS;
}
static Err scan_publish(ClaudeScan *s, ScanJob *job) {
  Err e=job->result;
  event_capture_replay(&job->before);
  if (job->skip) { job->root->complete=false; return skipped(s, job->key.path); }
  if (job->key.size) s->logs++;
  event_capture_replay(&job->events);
  if (e.code == ERR_IO) { job->root->complete=false; return skipped(s, job->key.path); }
  if (e.code) return e;
  if (s->count == s->capacity) {
    size_t n=s->capacity ? s->capacity*2 : 16;
    ClaudeRecord *next=realloc(s->records,n*sizeof *next);
    if (!next) return err_make(ERR_NOMEM,"Claude records allocation failed");
    s->records=next; s->capacity=n;
  }
  s->records[s->count++]=job->record; job->record=(ClaudeRecord){0};
  if (job->hit) s->cached++; else s->parsed++;
  return ERR_SUCCESS;
}
Err claude_scan(ClaudeScan *s, volatile sig_atomic_t *flag) {
  if (s->disabled)
    return ERR_SUCCESS;
  Omap seen = {0};
  Err e = ERR_SUCCESS;
  Walk walk = {0};
  walking=&walk; event_capture_begin(&walk.pending);
  for (size_t i = 0; i < s->root_count && !e.code; i++) {
    ClaudeRoot *r = &s->roots[i];
    walk.root = r;
    if (!r->present) {
      if(!claude_path_deleted(r->path.p))e=traversal_error(s,r,r->path);
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
  event_capture_end(); walking=NULL;
  omap_destroy(&seen);
  Err discovery_error=e;
  ScanWork work={.scan=s,.walk=&walk};
  Err run_error=jobpool_run(walk.count,scan_worker_count(),flag,scan_work,scan_collect,&work,NULL);
  e=ERR_SUCCESS;
  for (size_t i=0; i<work.collected && !e.code; i++) e=scan_publish(s,&walk.jobs[i]);
  if (!e.code) e=run_error;
  if (!e.code) { event_capture_replay(&walk.pending); e=discovery_error; }
  for (size_t i=0; i<walk.count; i++) {
    claude_record_destroy(&walk.jobs[i].record);
    event_capture_destroy(&walk.jobs[i].before); event_capture_destroy(&walk.jobs[i].events);
  }
  event_capture_destroy(&walk.pending); free(walk.jobs);
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
