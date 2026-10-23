#include "workspaces.h"
#include "out/jsonw.h"
#include "titles.h"
#include "util/fileio.h"
#include "util/json_number.h"
#include "util/sort.h"
#include <arpa/inet.h>
#include <errno.h>
#include <pwd.h>
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
static Str text(yyjson_val *v) {
  return yyjson_is_str(v)
             ? (Str){yyjson_get_str(v), (uint32_t)yyjson_get_len(v)}
             : (Str){0};
}
static yyjson_val *get(yyjson_val *v, const char *key) {
  return obj_get_last(v, (Str){key, (uint32_t)strlen(key)});
}
static Err join(Arena *arena, Str a, Str b, Str *out) {
  char *p;
  TRY(arena_alloc(arena, (size_t)a.n + b.n + 1, 1, (void **)&p));
  memcpy(p, a.p, a.n);
  if (b.n)
    memcpy(p + a.n, b.p, b.n);
  p[a.n + b.n] = 0;
  *out = (Str){p, a.n + b.n};
  return ERR_SUCCESS;
}
static bool has_space(Str s) {
  size_t at = 0;
  uint32_t cp;
  while (str_decode_next(s, &at, &cp))
    if (str_space_codepoint(cp))
      return true;
  return false;
}
static bool nfkc_invalid(Str s) {
  /* ASCII delimiters have no canonical compositions. NFKC can gain one
   * only through a scalar's compatibility expansion; the generated Unicode
   * 16 table proves that expansion without depending on host OS Unicode. */
  size_t at = 0;
  uint32_t cp;
  while (str_decode_next(s, &at, &cp))
    if (str_url_delimiter_codepoint(cp))
      return true;
  return false;
}
Err workspace_origin(Arena *arena, Str raw, Str *out) {
  *out = (Str){0};
  if (!metadata_text(raw))
    return ERR_SUCCESS;
  Str s = str_trim(raw, true);
  for (size_t i = 0; i < s.n; i++)
    if ((unsigned char)s.p[i] < 32 || s.p[i] == 127)
      return ERR_SUCCESS;
  size_t scheme = SIZE_MAX;
  for (size_t i = 0; i + 2 < s.n; i++)
    if (s.p[i] == ':' && s.p[i + 1] == '/' && s.p[i + 2] == '/') {
      scheme = i;
      break;
    }
  if (scheme == SIZE_MAX) {
    size_t at = SIZE_MAX, colon = SIZE_MAX;
    for (size_t i = 0; i < s.n; i++) {
      if (s.p[i] == '@' && at == SIZE_MAX)
        at = i;
      else if (s.p[i] == ':' && at != SIZE_MAX) {
        colon = i;
        break;
      }
    }
    if (at == SIZE_MAX || at == 0 || colon == SIZE_MAX || colon == at + 1 ||
        colon + 1 == s.n)
      return ERR_SUCCESS;
    Str user = {s.p, (uint32_t)at},
        host = {s.p + at + 1, (uint32_t)(colon - at - 1)};
    if (memchr(user.p, '/', user.n) || memchr(user.p, '@', user.n) ||
        memchr(host.p, '/', host.n) || has_space(user) || has_space(host))
      return ERR_SUCCESS;
    Str combined;
    TRY(join(arena, STR_LIT("ssh://"), host, &combined));
    TRY(join(arena, combined, STR_LIT("/"), &combined));
    TRY(join(arena, combined, (Str){s.p + colon + 1, s.n - colon - 1}, &s));
    scheme = 3;
  }
  Str lower;
  TRY(str_lower(arena, (Str){s.p, (uint32_t)scheme}, &lower));
  if (!str_equal(lower, STR_LIT("http")) &&
      !str_equal(lower, STR_LIT("https")) &&
      !str_equal(lower, STR_LIT("ssh")) && !str_equal(lower, STR_LIT("git")))
    return ERR_SUCCESS;
  size_t end = scheme + 3;
  while (end < s.n && s.p[end] != '/' && s.p[end] != '?' && s.p[end] != '#')
    end++;
  Str net = {s.p + scheme + 3, (uint32_t)(end - scheme - 3)};
  if (!net.n || nfkc_invalid(net))
    return ERR_SUCCESS;
  size_t begin = 0;
  for (size_t i = 0; i < net.n; i++)
    if (net.p[i] == '@')
      begin = i + 1;
  Str host = {0}, port = {0};
  bool ipv6 = false;
  if (begin < net.n && net.p[begin] == '[') {
    size_t close = begin + 1;
    while (close < net.n && net.p[close] != ']')
      close++;
    if (close == net.n)
      return ERR_SUCCESS;
    host = (Str){net.p + begin + 1, (uint32_t)(close - begin - 1)};
    char *tmp;
    TRY(arena_alloc(arena, host.n + 1, 1, (void **)&tmp));
    memcpy(tmp, host.p, host.n);
    tmp[host.n] = 0;
    unsigned char address[16];
    bool future = host.n >= 4 && (host.p[0] == 'v' || host.p[0] == 'V');
    if (future) {
      size_t i = 1;
      while (i < host.n && ((host.p[i] >= '0' && host.p[i] <= '9') ||
                            (host.p[i] >= 'a' && host.p[i] <= 'f') ||
                            (host.p[i] >= 'A' && host.p[i] <= 'F')))
        i++;
      future = i > 1 && i + 1 < host.n && host.p[i] == '.';
    }
    if (!future) {
      /* Python IPv6Address splits scope before validating the address: one
       * percent separator with a nonempty scope, whose other bytes are opaque.
       * Darwin inet_pton accepts an empty scope, so validate it independently. */
      char *scope = memchr(tmp, '%', host.n);
      if (scope) {
        size_t remaining = host.n - (size_t)(scope - tmp) - 1;
        if (!remaining || memchr(scope + 1, '%', remaining))
          return ERR_SUCCESS;
        *scope = 0;
      }
      if (inet_pton(AF_INET6, tmp, address) != 1)
        return ERR_SUCCESS;
    }
    if (close + 1 < net.n) {
      if (net.p[close + 1] != ':')
        return ERR_SUCCESS;
      port = (Str){net.p + close + 2, net.n - close - 2};
    }
    ipv6 = memchr(host.p, ':', host.n) != NULL;
  } else {
    if (memchr(net.p, '[', net.n) || memchr(net.p, ']', net.n))
      return ERR_SUCCESS;
    size_t colon = begin;
    while (colon < net.n && net.p[colon] != ':')
      colon++;
    host = (Str){net.p + begin, (uint32_t)(colon - begin)};
    if (colon < net.n)
      port = (Str){net.p + colon + 1, net.n - colon - 1};
  }
  unsigned number = 0;
  for (size_t i = 0; i < port.n; i++) {
    if (port.p[i] < '0' || port.p[i] > '9')
      return ERR_SUCCESS;
    number = number * 10 + (unsigned)(port.p[i] - '0');
    if (number > 65535)
      return ERR_SUCCESS;
  }
  if (!host.n || has_space(host))
    return ERR_SUCCESS;
  size_t stop = end;
  while (stop < s.n && s.p[stop] != '?' && s.p[stop] != '#')
    stop++;
  Str path = {s.p + end, (uint32_t)(stop - end)};
  while (path.n && path.p[path.n - 1] == '/')
    path.n--;
  if (path.n >= 4 && !memcmp(path.p + path.n - 4, ".git", 4))
    path.n -= 4;
  if (!path.n || (path.n == 1 && path.p[0] == '/'))
    return ERR_SUCCESS;
  while (path.n && path.p[0] == '/') {
    path.p++;
    path.n--;
  }
  TRY(str_lower(arena, host, &lower));
  Str result = STR_LIT("https://");
  if (ipv6)
    TRY(join(arena, result, STR_LIT("["), &result));
  TRY(join(arena, result, lower, &result));
  if (ipv6)
    TRY(join(arena, result, STR_LIT("]"), &result));
  TRY(join(arena, result, STR_LIT("/"), &result));
  return join(arena, result, path, out);
}
Err workspace_path(Arena *arena, Str raw, Str *out) {
  *out = (Str){0};
  if (!metadata_text(raw) || raw.p[0] != '/' || memchr(raw.p, 0, raw.n))
    return ERR_SUCCESS;
  Str normalized;
  TRY(file_lexical_path(raw, false, &normalized));
  size_t begin = 0;
  bool bad = false;
  for (size_t i = 0; i <= normalized.n; i++)
    if (i == normalized.n || normalized.p[i] == '/') {
      if (i - begin == 2 && !memcmp(normalized.p + begin, "..", 2))
        bad = true;
      begin = i + 1;
    }
  Err e = bad ? ERR_SUCCESS : str_copy(arena, normalized, out);
  free((void *)normalized.p);
  return e;
}
static Str parent(Str p) {
  size_t anchor = p.n >= 2 && p.p[0] == '/' && p.p[1] == '/' ? 2 : 1;
  if (p.n <= anchor)
    return (Str){0};
  size_t end = p.n;
  while (end > anchor && p.p[end - 1] != '/')
    end--;
  if (end > anchor)
    end--;
  return (Str){p.p, (uint32_t)end};
}
Err workspace_git_root(Arena *arena, Str cwd, Str *out) {
  *out = (Str){0};
  if (!cwd.p)
    return ERR_SUCCESS;
  struct stat st;
  Str p;
  TRY(str_copy(arena, cwd, &p));
  if (stat(p.p, &st)) {
    /* A removed folder, such as a deleted worktree, still belongs to the
     * repository around it: search from its nearest existing ancestor. */
    if (errno != ENOENT && errno != ENOTDIR)
      return ERR_SUCCESS;
    do {
      p = parent(p);
      if (!p.p)
        return ERR_SUCCESS;
      TRY(str_copy(arena, p, &p));
    } while (stat(p.p, &st));
  }
  if (!S_ISDIR(st.st_mode))
    return ERR_SUCCESS;
  while (p.p) {
    Str marker;
    TRY(join(arena, p, STR_LIT("/.git"), &marker));
    if (!stat(marker.p, &st) && (S_ISREG(st.st_mode) || S_ISDIR(st.st_mode))) {
      *out = p;
      return ERR_SUCCESS;
    }
    p = parent(p);
    if (p.p)
      TRY(str_copy(arena, p, &p));
  }
  return ERR_SUCCESS;
}
/* Unreadable or oversized files read as absent; only allocation fails. */
static Err read_text(Arena *arena, Str path, Str *out) {
  *out = (Str){0};
  char *bytes = NULL;
  size_t n = 0;
  Err e = file_read_all(path.p, &bytes, &n);
  if (e.code)
    return e.code == ERR_NOMEM ? e : ERR_SUCCESS;
  if (n <= UINT32_MAX)
    e = str_copy(arena, (Str){bytes, (uint32_t)n}, out);
  free(bytes);
  return e;
}
static Str first_line(Str s) {
  const char *end = s.p ? memchr(s.p, '\n', s.n) : NULL;
  if (end)
    s.n = (uint32_t)(end - s.p);
  return str_trim(s, true);
}
static Err beside(Arena *arena, Str base, Str path, Str *out) {
  if (path.p[0] == '/')
    return str_copy(arena, path, out);
  TRY(join(arena, base, STR_LIT("/"), out));
  return join(arena, *out, path, out);
}
/* The directory holding a repository's config. A linked worktree's .git file
 * names its private gitdir, whose commondir names the shared directory. */
static Err git_common_dir(Arena *arena, Str root, Str *out) {
  *out = (Str){0};
  Str dotgit, text, line, dir, file;
  struct stat st;
  TRY(join(arena, root, STR_LIT("/.git"), &dotgit));
  if (stat(dotgit.p, &st))
    return ERR_SUCCESS;
  if (S_ISDIR(st.st_mode)) {
    *out = dotgit;
    return ERR_SUCCESS;
  }
  TRY(read_text(arena, dotgit, &text));
  line = first_line(text);
  if (line.n < 8 || memcmp(line.p, "gitdir:", 7))
    return ERR_SUCCESS;
  line = str_trim((Str){line.p + 7, line.n - 7}, true);
  if (!line.n)
    return ERR_SUCCESS;
  TRY(beside(arena, root, line, &dir));
  TRY(join(arena, dir, STR_LIT("/commondir"), &file));
  TRY(read_text(arena, file, &text));
  line = first_line(text);
  if (!line.n) {
    *out = dir;
    return ERR_SUCCESS;
  }
  return beside(arena, dir, line, out);
}
static bool ascii_iequal(Str a, Str b) {
  if (a.n != b.n)
    return false;
  for (uint32_t i = 0; i < a.n; i++) {
    char x = a.p[i], y = b.p[i];
    if (x >= 'A' && x <= 'Z')
      x = (char)(x - 'A' + 'a');
    if (y >= 'A' && y <= 'Z')
      y = (char)(y - 'A' + 'a');
    if (x != y)
      return false;
  }
  return true;
}
static bool blank(char c) { return c == ' ' || c == '\t'; }
/* Git config section header: [remote "origin"] (name case-insensitive,
 * subsection exact with \-escapes) or the legacy [remote.origin]. */
static bool origin_section(Str line) {
  size_t i = 1;
  while (i < line.n && line.p[i] != ']' && !blank(line.p[i]) &&
         line.p[i] != '"')
    i++;
  Str name = {line.p + 1, (uint32_t)(i - 1)};
  if (i < line.n && line.p[i] == ']')
    return ascii_iequal(name, STR_LIT("remote.origin"));
  if (!ascii_iequal(name, STR_LIT("remote")))
    return false;
  while (i < line.n && blank(line.p[i]))
    i++;
  if (i == line.n || line.p[i++] != '"')
    return false;
  const char *want = "origin";
  size_t k = 0;
  for (; i < line.n && line.p[i] != '"'; i++) {
    char c = line.p[i];
    if (c == '\\' && i + 1 < line.n)
      c = line.p[++i];
    if (k == 6 || c != want[k++])
      return false;
  }
  return k == 6 && i + 1 < line.n && line.p[i + 1] == ']';
}
/* First url of [remote "origin"]: quotes, \-escapes and comments as git. */
static Err config_origin_url(Arena *arena, Str text, Str *out) {
  *out = (Str){0};
  bool inside = false;
  size_t at = 0;
  while (text.p && at < text.n) {
    const char *end = memchr(text.p + at, '\n', text.n - at);
    size_t stop = end ? (size_t)(end - text.p) : text.n;
    Str line = {text.p + at, (uint32_t)(stop - at)};
    at = stop + 1;
    while (line.n && blank(line.p[0])) {
      line.p++;
      line.n--;
    }
    if (line.n && line.p[line.n - 1] == '\r')
      line.n--;
    if (!line.n || line.p[0] == '#' || line.p[0] == ';')
      continue;
    if (line.p[0] == '[') {
      inside = origin_section(line);
      continue;
    }
    size_t i = 0;
    while (i < line.n && ((line.p[i] >= 'a' && line.p[i] <= 'z') ||
                          (line.p[i] >= 'A' && line.p[i] <= 'Z') ||
                          (line.p[i] >= '0' && line.p[i] <= '9') ||
                          line.p[i] == '-'))
      i++;
    if (!inside || !ascii_iequal((Str){line.p, (uint32_t)i}, STR_LIT("url")))
      continue;
    while (i < line.n && blank(line.p[i]))
      i++;
    if (i == line.n || line.p[i++] != '=')
      continue;
    while (i < line.n && blank(line.p[i]))
      i++;
    char *value;
    TRY(arena_alloc(arena, line.n - i + 1, 1, (void **)&value));
    size_t used = 0, keep = 0;
    bool quoted = false;
    for (; i < line.n; i++) {
      char c = line.p[i];
      if (c == '"') {
        quoted = !quoted;
        continue;
      }
      if (!quoted && (c == '#' || c == ';'))
        break;
      if (c == '\\' && i + 1 < line.n) {
        c = line.p[++i];
        c = c == 'n' ? '\n' : c == 't' ? '\t' : c == 'b' ? '\b' : c;
        value[used++] = c;
        keep = used;
        continue;
      }
      value[used++] = c;
      if (quoted || !blank(c))
        keep = used;
    }
    value[keep] = 0;
    *out = (Str){value, (uint32_t)keep};
    return ERR_SUCCESS;
  }
  return ERR_SUCCESS;
}
Err workspace_git_origin(Arena *arena, Str root, Str *out) {
  *out = (Str){0};
  if (!root.p)
    return ERR_SUCCESS;
  Str common, config, text, url;
  TRY(git_common_dir(arena, root, &common));
  if (!common.p)
    return ERR_SUCCESS;
  TRY(join(arena, common, STR_LIT("/config"), &config));
  TRY(read_text(arena, config, &text));
  TRY(config_origin_url(arena, text, &url));
  return url.p ? workspace_origin(arena, url, out) : ERR_SUCCESS;
}
static Err alias_error(WorkspaceAliases *out, const char *path,
                       const char *problem) {
  JsonWriter w = {0};
  jsonw_raw(&w, "colophon: ");
  jsonw_raw(&w, path);
  jsonw_raw(&w, ": ");
  jsonw_raw(&w, problem);
  jsonw_raw(&w, "; workspace aliases ignored");
  Err e = w.error;
  Str message = {0};
  if (!e.code)
    e = str_copy(&out->arena, (Str){w.data, (uint32_t)w.length}, &message);
  if (!e.code)
    e = corpus_strings_add(&out->arena, &out->errors, message);
  if (!e.code)
    fprintf(stderr, "%s\n", message.p);
  out->count = 0;
  jsonw_free(&w);
  return e;
}
Err workspace_aliases_decode(yyjson_val *root, bool file_schema,
                             const char *path, WorkspaceAliases *out) {
  char problem[180];
  yyjson_val *rows = root;
  if (file_schema) {
    PyNum schema;
    yyjson_val *v = get(root, "schema");
    if (!yyjson_is_obj(root) || !json_number(v, "workspaces.schema", &schema) ||
        schema.is_float || schema.i != 1)
      return alias_error(out, path, "field schema must be integer 1");
    rows = get(root, "aliases");
  }
  if (!yyjson_is_arr(rows))
    return alias_error(out, path, "field aliases must be an array");
  size_t count = yyjson_arr_size(rows);
  TRY(arena_alloc(&out->arena, (count ? count : 1) * sizeof *out->items,
                  _Alignof(WorkspaceAlias), (void **)&out->items));
  memset(out->items, 0, count * sizeof *out->items);
  for (size_t i = 0; i < count; i++) {
    yyjson_val *row = yyjson_arr_get(rows, i);
    WorkspaceAlias *alias = &out->items[i];
    if (!yyjson_is_obj(row)) {
      snprintf(problem, sizeof problem,
               "alias index %zu: alias must be an object", i);
      return alias_error(out, path, problem);
    }
    Str name = text(get(row, "name"));
    if (!metadata_text(name)) {
      snprintf(problem, sizeof problem,
               "alias index %zu, field name must be a nonblank string", i);
      return alias_error(out, path, problem);
    }
    TRY(str_copy(&out->arena, name, &alias->name));
    const char *fields[] = {"origins", "paths"};
    for (size_t j = 0; j < 2; j++) {
      yyjson_val *values = get(row, fields[j]);
      bool valid = yyjson_is_arr(values);
      size_t n = valid ? yyjson_arr_size(values) : 0;
      for (size_t k = 0; k < n; k++) {
        Str raw = text(yyjson_arr_get(values, k)), normalized = {0};
        if (j)
          TRY(workspace_path(&out->arena, raw, &normalized));
        else
          TRY(workspace_origin(&out->arena, raw, &normalized));
        if (!normalized.p) {
          valid = false;
          break;
        }
        Str copy;
        TRY(str_copy(&out->arena, raw, &copy));
        TRY(corpus_strings_add(
            &out->arena, j ? &alias->raw_paths : &alias->raw_origins, copy));
        CorpusStrings *list = j ? &alias->paths : &alias->origins;
        bool seen = false;
        for (size_t x = 0; x < list->count; x++)
          if (str_equal(list->items[x], normalized))
            seen = true;
        if (!seen)
          TRY(corpus_strings_add(&out->arena, list, normalized));
      }
      if (!valid) {
        snprintf(
            problem, sizeof problem,
            "alias index %zu, field %s must be an array of valid %s strings", i,
            fields[j], fields[j]);
        return alias_error(out, path, problem);
      }
    }
  }
  out->count = count;
  return ERR_SUCCESS;
}
Err workspace_aliases_load(const char *path, WorkspaceAliases *out) {
  char *bytes = NULL;
  size_t n = 0;
  Err e = file_read_all(path, &bytes, &n);
  if (e.code) {
    if (e.code == ERR_NOMEM)
      return e;
    if (errno == ENOENT)
      return ERR_SUCCESS;
    char message[200];
    snprintf(message, sizeof message, "%s", e.message);
    return alias_error(out, path, message);
  }
  /* Python text I/O universal newline conversion precedes parsing. */
  size_t used = 0;
  for (size_t i = 0; i < n; i++) {
    if (bytes[i] == '\r') {
      bytes[used++] = '\n';
      if (i + 1 < n && bytes[i + 1] == '\n')
        i++;
    } else
      bytes[used++] = bytes[i];
  }
  JsonRead read = json_read((Str){bytes, (uint32_t)used}, STRICT,
                            JSON_CONSTANTS_ALLOW, "workspaces.json");
  if (read.status == JSON_NOMEM) {
    free(bytes);
    json_read_free(&read);
    return err_make(ERR_NOMEM, "workspace JSON allocation failed");
  }
  if (read.status != JSON_OK) {
    JsonStats validation = {0};
    JsonStatus encoding =
        wtf8_validate((Str){bytes, (uint32_t)used}, STRICT, &validation);
    if (validation.bom)
      e = alias_error(out, path,
                      "line 1: Unexpected UTF-8 BOM (decode using utf-8-sig)");
    else if (encoding != JSON_OK)
      e = alias_error(out, path, "invalid UTF-8 text");
    else {
      yyjson_read_err err = {0};
      yyjson_doc *probe = yyjson_read_opts(
          bytes, used, YYJSON_READ_ALLOW_INF_AND_NAN, NULL, &err);
      yyjson_doc_free(probe);
      size_t line = 1;
      for (size_t i = 0; i < err.pos && i < used; i++)
        if (bytes[i] == '\n')
          line++;
      char problem[200];
      snprintf(problem, sizeof problem, "line %zu: %s", line,
               err.msg ? err.msg : "invalid JSON");
      e = alias_error(out, path, problem);
    }
  } else
    e = workspace_aliases_decode(yyjson_doc_get_root(read.doc), true, path,
                                 out);
  json_read_free(&read);
  free(bytes);
  return e;
}
void workspace_aliases_destroy(WorkspaceAliases *a) {
  arena_destroy(&a->arena);
  *a = (WorkspaceAliases){0};
}
static Str relative(Str cwd, Str root) {
  if (!cwd.p || !root.p || str_equal(cwd, root))
    return (Str){0};
  size_t n = root.n;
  bool cwd_double = cwd.n >= 2 && cwd.p[1] == '/';
  bool root_double = root.n >= 2 && root.p[1] == '/';
  if (cwd_double != root_double)
    return (Str){0};
  if (str_equal(root, STR_LIT("/")) || str_equal(root, STR_LIT("//"))) {
    if (cwd.n > n && !memcmp(cwd.p, root.p, n))
      return (Str){cwd.p + n, cwd.n - n};
    return (Str){0};
  }
  if (cwd.n > n && cwd.p[n] == '/' && !memcmp(cwd.p, root.p, n))
    return (Str){cwd.p + n + 1, cwd.n - n - 1};
  return (Str){0};
}
static Str rawtext(JScalar v) {
  return v.kind == JS_STRING ? v.value.s : (Str){0};
}
static Str dbtext(SessionModel *s, MetadataColumn c) {
  return s->db_info && s->db_info->values[c].kind == META_TEXT
             ? s->db_info->values[c].value.bytes
             : (Str){0};
}
static int string_order(const void *a, const void *b, void *ctx) {
  (void)ctx;
  return str_compare(*(const Str *)a, *(const Str *)b);
}
void corpus_workspaces_destroy(Corpus *c) { omap_destroy(&c->workspaces); }
Err corpus_resolve_workspaces(Corpus *c, const WorkspaceAliases *aliases) {
  corpus_workspaces_destroy(c);
  Omap memo = {0}, origins = {0};
  Err e = ERR_SUCCESS;
  const char *env = getenv("HOME");
  if (!env) {
    struct passwd *pw = getpwuid(getuid());
    env = pw ? pw->pw_dir : "/";
  }
  Str home = {0};
  e = workspace_path(&c->arena, (Str){env, (uint32_t)strlen(env)}, &home);
  if (e.code)
    goto done;
  for (OmapEntry *q = c->sessions.first; q; q = q->next) {
    SessionModel *s = q->value;
    Str origin = {0}, cwd = {0}, root = {0};
    e = workspace_origin(&c->arena, rawtext(s->meta.origin_url),
                         &origin);
    if (e.code)
      goto done;
    if (!origin.p) {
      e = workspace_origin(&c->arena, dbtext(s, META_GIT_ORIGIN_URL), &origin);
      if (e.code)
        goto done;
    }
    e = workspace_path(&c->arena, rawtext(s->meta.cwd), &cwd);
    if (e.code)
      goto done;
    if (!cwd.p) {
      e = workspace_path(&c->arena, dbtext(s, META_CWD), &cwd);
      if (e.code)
        goto done;
    }
    if (s->provider == PROVIDER_ANTIGRAVITY) {
      e = workspace_path(&c->arena, s->antigravity_git_root, &root);
      if (e.code)
        goto done;
    }
    if (cwd.p && !root.p) {
      Str *saved = omap_get(&memo, cwd);
      if (saved)
        root = *saved;
      else {
        e = workspace_git_root(&c->arena, cwd, &root);
        if (e.code)
          goto done;
        e = arena_alloc(&c->arena, sizeof *saved, _Alignof(Str),
                        (void **)&saved);
        if (e.code)
          goto done;
        *saved = root;
        e = omap_put(&memo, cwd, saved);
        if (e.code)
          goto done;
      }
    }
    if (!origin.p && root.p) {
      /* Claude and OpenCode record no remote; read the one Codex would. */
      Str *saved = omap_get(&origins, root);
      if (saved)
        origin = *saved;
      else {
        e = workspace_git_origin(&c->arena, root, &origin);
        if (e.code)
          goto done;
        e = arena_alloc(&c->arena, sizeof *saved, _Alignof(Str),
                        (void **)&saved);
        if (e.code)
          goto done;
        *saved = origin;
        e = omap_put(&origins, root, saved);
        if (e.code)
          goto done;
      }
    }
    s->subfolder = relative(cwd, root);
    const WorkspaceAlias *matched = NULL;
    for (size_t i = 0; i < aliases->count; i++) {
      const WorkspaceAlias *a = &aliases->items[i];
      bool match = false;
      size_t roots = 0;
      Str matchroot = {0};
      for (size_t j = 0; j < a->origins.count; j++)
        if (origin.p && str_equal(origin, a->origins.items[j]))
          match = true;
      for (size_t j = 0; j < a->paths.count; j++)
        if (cwd.p && (str_equal(cwd, a->paths.items[j]) ||
                      relative(cwd, a->paths.items[j]).p)) {
          roots++;
          matchroot = a->paths.items[j];
        }
      if (match || roots) {
        matched = a;
        if (roots)
          s->subfolder = roots == 1 ? relative(cwd, matchroot) : (Str){0};
        break;
      }
    }
    Str prefix, name, kind, alias = {0}, identity;
    if (matched) {
      prefix = STR_LIT("alias:");
      e = str_copy(&c->arena, matched->name, &name);
      if (e.code)
        goto done;
      identity = alias = name;
      kind = STR_LIT("alias");
    } else if (origin.p) {
      prefix = STR_LIT("origin:");
      identity = origin;
      name = title_path_name(origin, false);
      kind = STR_LIT("origin");
    } else if (root.p) {
      prefix = STR_LIT("git:");
      identity = root;
      name =
          str_equal(root, home) ? STR_LIT("~") : title_path_name(root, false);
      if (!name.n)
        name = root;
      kind = STR_LIT("git_root");
    } else {
      prefix = STR_LIT("cwd:");
      identity = cwd.p ? cwd : STR_LIT("");
      kind = STR_LIT("cwd");
      if (!cwd.p)
        name = STR_LIT("(unknown)");
      else if (str_equal(cwd, home))
        name = STR_LIT("~ (home)");
      else {
        Str rel = relative(cwd, home), display = cwd;
        if (rel.p) {
          e = join(&c->arena, STR_LIT("~/"), rel, &display);
          if (e.code)
            goto done;
        }
        e = join(&c->arena, display, STR_LIT(" (no repo)"), &name);
        if (e.code)
          goto done;
      }
    }
    e = join(&c->arena, prefix, identity, &s->workspace);
    if (e.code)
      goto done;
    Workspace *w = omap_get(&c->workspaces, s->workspace);
    if (!w) {
      e = arena_alloc(&c->arena, sizeof *w, _Alignof(Workspace), (void **)&w);
      if (e.code)
        goto done;
      *w = (Workspace){.name = name, .kind = kind, .alias = alias};
      e = omap_put(&c->workspaces, s->workspace, w);
      if (e.code)
        goto done;
    }
    Str keys[] = {origin, root, cwd};
    for (size_t i = 0; i < 3; i++)
      if (keys[i].p) {
        bool seen = false;
        for (size_t j = 0; j < w->keys.count; j++)
          if (str_equal(keys[i], w->keys.items[j]))
            seen = true;
        if (!seen) {
          e = corpus_strings_add(&c->arena, &w->keys, keys[i]);
          if (e.code)
            goto done;
        }
      }
  }
  for (OmapEntry *q = c->workspaces.first; q; q = q->next) {
    Workspace *w = q->value;
    e = stable_sort(w->keys.items, w->keys.count, sizeof(Str), string_order,
                    NULL);
    if (e.code)
      goto done;
  }
done:
  omap_destroy(&memo);
  omap_destroy(&origins);
  return e;
}
