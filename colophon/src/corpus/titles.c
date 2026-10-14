#include "titles.h"
#include <string.h>
Str title_candidate_text(TitleCandidate candidate) {
  return !candidate.is_bytes && candidate.json.kind == JS_STRING
             ? candidate.json.value.s
             : (Str){0};
}
Str title_path_name(Str path, bool stem) {
  Str result = {path.p, 0};
  size_t at = 0;
  while (at < path.n) {
    while (at < path.n && path.p[at] == '/')
      at++;
    size_t start = at;
    while (at < path.n && path.p[at] != '/')
      at++;
    size_t n = at - start;
    if (n && !(n == 1 && path.p[start] == '.'))
      result = (Str){path.p + start, (uint32_t)n};
  }
  if (stem)
    for (size_t i = result.n; i > 1; i--)
      if (result.p[i - 1] == '.') {
        result.n = (uint32_t)i - 1;
        break;
      }
  return result;
}
void title_select(const Str candidates[7], Str cwd, Str identity, Str path,
                  Str *full, Str *source) {
  const Str names[] = {STR_LIT("database_name"),
                       STR_LIT("session_index"),
                       STR_LIT("desktop_title"),
                       STR_LIT("rollout_title"),
                       STR_LIT("database_title"),
                       STR_LIT("first_user_message"),
                       STR_LIT("database_first_user_message")};
  for (size_t i = 0; i < 7; i++)
    if (metadata_text(candidates[i])) {
      *full = candidates[i];
      *source = names[i];
      return;
    }
  Str folder = title_path_name(cwd, false);
  if (metadata_text(cwd) && metadata_text(folder)) {
    *full = folder;
    *source = STR_LIT("folder");
  } else if (metadata_text(identity)) {
    *full = identity;
    *source = STR_LIT("session_id");
  } else {
    *full = title_path_name(path, true);
    *source = STR_LIT("filename");
  }
}
Err title_humanize(Arena *arena, Str path, Str *out) {
  if (!metadata_text(path)) {
    *out = STR_LIT("subagent");
    return ERR_SUCCESS;
  }
  size_t start = path.n;
  while (start && path.p[start - 1] != '/')
    start--;
  Str label = {path.p + start, path.n - (uint32_t)start};
  char *p;
  Err e = arena_alloc(arena, label.n + 1, 1, (void **)&p);
  if (e.code)
    return e;
  for (size_t i = 0; i < label.n; i++)
    p[i] = (label.p[i] == '_' || label.p[i] == '-') ? ' ' : label.p[i];
  p[label.n] = 0;
  *out = (Str){p, label.n};
  if (!metadata_text(*out))
    *out = STR_LIT("subagent");
  return ERR_SUCCESS;
}
Err title_subagent(Arena *arena, Str path, Str nickname, Str *out) {
  Err e = title_humanize(arena, path, out);
  if (e.code || !metadata_text(nickname))
    return e;
  char *p;
  size_t n = out->n + 4 + nickname.n;
  e = arena_alloc(arena, n + 1, 1, (void **)&p);
  if (e.code)
    return e;
  memcpy(p, out->p, out->n);
  memcpy(p + out->n, " · ", 4);
  memcpy(p + out->n + 4, nickname.p, nickname.n);
  p[n] = 0;
  *out = (Str){p, (uint32_t)n};
  return ERR_SUCCESS;
}
Err title_display(Arena *arena, Str full, Str *out) {
  size_t offsets[82], n = 0, at = 0;
  uint32_t cp;
  while (at < full.n && n < 82) {
    size_t before = at;
    if (!str_decode_next(full, &at, &cp))
      return err_make(ERR_INVALID, "invalid title text");
    if (str_linebreak_codepoint(cp)) {
      at = before;
      break;
    }
    offsets[n++] = before;
  }
  if (n <= 80) {
    *out = (Str){full.p, (uint32_t)at};
    return ERR_SUCCESS;
  }
  size_t boundary = 80;
  for (size_t i = 81; i > 0; i--) {
    size_t index = i - 1, pos = offsets[index];
    str_decode_next(full, &pos, &cp);
    if (str_space_codepoint(cp) &&
        str_trim((Str){full.p, (uint32_t)offsets[index]}, true).n) {
      boundary = index;
      break;
    }
  }
  Str prefix = str_trim((Str){full.p, (uint32_t)offsets[boundary]}, true);
  /* rstrip only: preserve leading whitespace. */
  size_t left = (size_t)(prefix.p - full.p);
  prefix = (Str){full.p, (uint32_t)(left + prefix.n)};
  char *p;
  Err e = arena_alloc(arena, prefix.n + 4, 1, (void **)&p);
  if (e.code)
    return e;
  memcpy(p, prefix.p, prefix.n);
  memcpy(p + prefix.n, "…", 3);
  p[prefix.n + 3] = 0;
  *out = (Str){p, prefix.n + 3};
  return ERR_SUCCESS;
}
