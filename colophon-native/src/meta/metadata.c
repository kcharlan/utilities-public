#define _DARWIN_C_SOURCE
#include "metadata.h"
#include "util/fileio.h"
#include "util/json_read.h"
#include "util/pynum.h"
#include "util/sort.h"
#include "util/time.h"
#include <dirent.h>
#include <errno.h>
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

MetadataColumn metadata_thread_column(const MetadataThread *row, size_t position) {
    return row->order_count ? row->order[position] : (MetadataColumn)position;
}

const char *const metadata_columns[META_COLUMNS] = {
    "id", "name", "title", "cwd", "git_branch", "git_origin_url", "git_sha", "source",
    "originator", "archived", "first_user_message", "agent_nickname", "agent_role",
    "agent_path", "rollout_path"
};
static Str text(const char *s) { return (Str){s, (uint32_t)strlen(s)}; }
bool metadata_text(Str value) { return value.p && str_trim(value, true).n; }
static Err allocate(Arena *arena, size_t size, void **out) {
    Err e = arena_alloc(arena, size, _Alignof(max_align_t), out);
    if (!e.code) memset(*out, 0, size);
    return e;
}
static Err error_append(CodexMetadata *m, const char *prefix, const char *message) {
    MetadataError *item;
    Err e = allocate(&m->arena, sizeof *item, (void **)&item);
    if (e.code) return e;
    size_t a = strlen(prefix), b = strlen(message);
    if (a + b + 2 > UINT32_MAX) return err_make(ERR_NOMEM, "metadata error too large");
    char *buffer;
    e = arena_alloc(&m->arena, a + b + 3, 1, (void **)&buffer);
    if (e.code) return e;
    memcpy(buffer, prefix, a); memcpy(buffer + a, ": ", 2); memcpy(buffer + a + 2, message, b);
    buffer[a+b+2] = 0; item->text = (Str){buffer, (uint32_t)(a+b+2)};
    if (m->last_error) m->last_error->next = item; else m->errors = item;
    m->last_error = item;
    return ERR_SUCCESS;
}
static Err put_text(Arena *arena, Omap *map, Str key, Str value) {
    Str *owned;
    Err e = allocate(arena, sizeof *owned, (void **)&owned);
    if (!e.code) e = str_copy(arena, value, owned);
    if (!e.code) e = omap_put(map, key, owned);
    return e;
}
static Err join(const char *home, const char *name, char **path) {
    size_t a = strlen(home), b = strlen(name);
    char *raw = malloc(a+b+2);
    if (!raw) return err_make(ERR_NOMEM, "metadata path allocation failed");
    snprintf(raw, a+b+2, "%s%s%s", home, a ? "/" : "", name);
    Str normalized;
    Err e = file_lexical_path(text(raw), false, &normalized);
    free(raw);
    if (!e.code) *path = (char *)normalized.p;
    return e;
}
Err metadata_database_uri(const char *path, char **uri) {
    char *absolute = NULL;
    if (path[0] == '/') absolute = strdup(path);
    else {
        char *cwd = getcwd(NULL, 0);
        if (!cwd) return err_make(ERR_IO, "cannot read working directory");
        Err e = join(cwd, path, &absolute); free(cwd);
        if (e.code) return e;
    }
    if (!absolute) return err_make(ERR_NOMEM, "metadata path allocation failed");
    size_t n = strlen(absolute), used = 5;
    char *result = malloc(n*3+14);
    if (!result) { free(absolute); return err_make(ERR_NOMEM, "SQLite URI allocation failed"); }
    memcpy(result, "file:", 5);
    const char hex[] = "0123456789ABCDEF";
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)absolute[i];
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
            c == '/' || c == '-' || c == '_' || c == '.' || c == '~') result[used++] = (char)c;
        else { result[used++] = '%'; result[used++] = hex[c >> 4]; result[used++] = hex[c & 15]; }
    }
    memcpy(result+used, "?mode=ro", 9); free(absolute); *uri = result;
    return ERR_SUCCESS;
}
static Err sqlite_error(sqlite3 *db) { return err_make(ERR_IO, "%s", sqlite3_errmsg(db)); }
static Err prepare(sqlite3 *db, const char *sql, sqlite3_stmt **stmt) {
    return sqlite3_prepare_v2(db, sql, -1, stmt, NULL) == SQLITE_OK ? ERR_SUCCESS : sqlite_error(db);
}
/* Every selected TEXT cell is validated before predicates discard a row.
 * STRICT JSON mode's leading-BOM rejection does not apply to SQLite text. */
static Err cell(Arena *arena, sqlite3_stmt *stmt, int column, MetadataValue *out) {
    int kind = sqlite3_column_type(stmt, column);
    if (kind == SQLITE_NULL) return ERR_SUCCESS;
    if (kind == SQLITE_INTEGER) { out->kind = META_INTEGER; out->value.integer = sqlite3_column_int64(stmt, column); return ERR_SUCCESS; }
    if (kind == SQLITE_FLOAT) { out->kind = META_REAL; out->value.real = sqlite3_column_double(stmt, column); return ERR_SUCCESS; }
    int count = sqlite3_column_bytes(stmt, column);
    const void *bytes = kind == SQLITE_TEXT ? (const void *)sqlite3_column_text(stmt, column) : sqlite3_column_blob(stmt, column);
    if (!bytes && count) return err_make(ERR_NOMEM, "SQLite value allocation failed");
    Str value = {(const char *)(bytes ? bytes : ""), (uint32_t)count};
    if (kind == SQLITE_TEXT) {
        if (!str_utf8_scalar_valid(value))
            return err_make(ERR_IO, "Could not decode to UTF-8 column '%s'", sqlite3_column_name(stmt, column));
        if (!count) return ERR_SUCCESS;
    }
    out->kind = kind == SQLITE_TEXT ? META_TEXT : META_BLOB;
    return str_copy(arena, value, &out->value.bytes);
}
static bool value_equal(MetadataValue a, MetadataValue b) {
    if ((a.kind == META_INTEGER || a.kind == META_REAL) && (b.kind == META_INTEGER || b.kind == META_REAL)) {
        PyNum x = {a.kind == META_REAL, a.kind == META_INTEGER ? a.value.integer : 0, a.kind == META_REAL ? a.value.real : 0};
        PyNum y = {b.kind == META_REAL, b.kind == META_INTEGER ? b.value.integer : 0, b.kind == META_REAL ? b.value.real : 0};
        return pynum_equal(x, y);
    }
    return a.kind == b.kind && (a.kind == META_ABSENT || str_equal(a.value.bytes, b.value.bytes));
}
static bool row_equal(const MetadataThread *a, const MetadataThread *b) {
    for (size_t i = 0; i < META_COLUMNS; i++) if (!value_equal(a->values[i], b->values[i])) return false;
    return true;
}
static Err columns(sqlite3 *db, const char *sql, Omap *out) {
    sqlite3_stmt *stmt = NULL;
    Err e = prepare(db, sql, &stmt);
    int rc = SQLITE_DONE;
    while (!e.code && (rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        MetadataValue name = {0}; Arena arena = {0};
        e = cell(&arena, stmt, 1, &name);
        if (!e.code && name.kind == META_TEXT) e = omap_put(out, name.value.bytes, (void *)1);
        arena_destroy(&arena);
    }
    if (!e.code && rc != SQLITE_DONE) e = sqlite_error(db);
    sqlite3_finalize(stmt); return e;
}
static Err read_threads(sqlite3 *db, const char *name, CodexMetadata *m) {
    Omap available = {0}, ambiguous = {0}; sqlite3_stmt *stmt = NULL;
    Err e = columns(db, "PRAGMA table_info(threads)", &available);
    if (!e.code && !omap_get(&available, STR_LIT("id"))) e = err_make(ERR_IO, "threads table missing id column");
    char sql[512] = "SELECT "; size_t used = strlen(sql), count = 0; int selected[META_COLUMNS];
    for (int i = 0; !e.code && i < META_COLUMNS; i++) if (omap_get(&available, text(metadata_columns[i]))) {
        used += (size_t)snprintf(sql+used, sizeof sql-used, "%s\"%s\"", count ? ", " : "", metadata_columns[i]);
        selected[count++] = i;
    }
    if (!e.code) { snprintf(sql+used, sizeof sql-used, " FROM threads"); e = prepare(db, sql, &stmt); }
    int rc = SQLITE_DONE;
    while (!e.code && (rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        MetadataThread *row;
        e = allocate(&m->arena, sizeof *row, (void **)&row);
        for (size_t i = 0; !e.code && i < count; i++) e = cell(&m->arena, stmt, (int)i, &row->values[selected[i]]);
        if (e.code) break;
        MetadataValue id = row->values[META_ID];
        if (id.kind != META_TEXT || !metadata_text(id.value.bytes) || omap_get(&ambiguous, id.value.bytes)) continue;
        MetadataThread *old = omap_get(&m->threads, id.value.bytes);
        if (old && !row_equal(old, row)) {
            e = omap_put(&ambiguous, id.value.bytes, (void *)1);
            omap_delete(&m->threads, id.value.bytes, NULL);
            if (!e.code) e = error_append(m, name, "conflicting duplicate threads id");
        } else e = omap_put(&m->threads, id.value.bytes, row);
    }
    if (!e.code && rc != SQLITE_DONE) e = sqlite_error(db);
    for (OmapEntry *entry = m->threads.first; !e.code && entry; entry = entry->next) {
        MetadataValue rollout = ((MetadataThread *)entry->value)->values[META_ROLLOUT_PATH];
        if (rollout.kind == META_TEXT && metadata_text(rollout.value.bytes)) e = put_text(&m->arena, &m->rollout_paths, entry->key, rollout.value.bytes);
    }
    sqlite3_finalize(stmt); omap_destroy(&available); omap_destroy(&ambiguous); return e;
}
static Err read_edges(sqlite3 *db, const char *name, CodexMetadata *m) {
    sqlite3_stmt *stmt = NULL; Omap available = {0}, ambiguous = {0};
    Err e = prepare(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='thread_spawn_edges'", &stmt);
    int rc = e.code ? SQLITE_ERROR : sqlite3_step(stmt);
    if (!e.code && rc != SQLITE_ROW && rc != SQLITE_DONE) e = sqlite_error(db);
    sqlite3_finalize(stmt); stmt = NULL;
    if (e.code || rc == SQLITE_DONE) return e;
    e = columns(db, "PRAGMA table_info(thread_spawn_edges)", &available);
    const char *sql = NULL;
    if (!e.code && omap_get(&available, STR_LIT("child_thread_id")) && omap_get(&available, STR_LIT("parent_thread_id")))
        sql = "SELECT \"child_thread_id\", \"parent_thread_id\" FROM thread_spawn_edges";
    else if (!e.code && omap_get(&available, STR_LIT("child_id")) && omap_get(&available, STR_LIT("parent_id")))
        sql = "SELECT \"child_id\", \"parent_id\" FROM thread_spawn_edges";
    if (!e.code && !sql) { e = error_append(m, name, "unrecognized thread_spawn_edges columns"); goto done; }
    if (!e.code) e = prepare(db, sql, &stmt);
    while (!e.code && (rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        MetadataValue child = {0}, parent = {0};
        e = cell(&m->arena, stmt, 0, &child);
        if (!e.code) e = cell(&m->arena, stmt, 1, &parent);
        if (e.code) break;
        if (child.kind != META_TEXT || parent.kind != META_TEXT || !metadata_text(child.value.bytes) ||
            !metadata_text(parent.value.bytes) || omap_get(&ambiguous, child.value.bytes)) continue;
        Str *old = omap_get(&m->spawn_parents, child.value.bytes);
        if (old && !str_equal(*old, parent.value.bytes)) {
            e = omap_put(&ambiguous, child.value.bytes, (void *)1);
            omap_delete(&m->spawn_parents, child.value.bytes, NULL);
            if (!e.code) e = error_append(m, name, "conflicting thread_spawn_edges parents");
        } else e = put_text(&m->arena, &m->spawn_parents, child.value.bytes, parent.value.bytes);
    }
    if (!e.code && rc != SQLITE_DONE) e = sqlite_error(db);
done:
    sqlite3_finalize(stmt); omap_destroy(&available); omap_destroy(&ambiguous); return e;
}
static Err read_database(const char *path, const char *name, CodexMetadata *m) {
    char *uri = NULL; sqlite3 *db = NULL;
    Err e = metadata_database_uri(path, &uri);
    if (!e.code && sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, NULL) != SQLITE_OK) e = sqlite_error(db);
    free(uri);
    if (!e.code && sqlite3_busy_timeout(db, 1000) != SQLITE_OK) e = sqlite_error(db);
    if (!e.code && sqlite3_exec(db, "BEGIN", NULL, NULL, NULL) != SQLITE_OK) e = sqlite_error(db);
    if (!e.code) e = read_threads(db, name, m);
    if (!e.code) e = read_edges(db, name, m);
    if (db) sqlite3_close(db);
    return e;
}
typedef struct { char *path, *name; Str number; } Candidate;
static int candidate_compare(const void *left, const void *right, void *unused) {
    (void)unused;
    const Candidate *a = left, *b = right;
    if (a->number.n != b->number.n) return a->number.n > b->number.n ? -1 : 1;
    int order = str_compare(a->number, b->number);
    return order ? -order : strcmp(a->path, b->path);
}
static Err databases(const char *home, CodexMetadata *m) {
    Candidate *items = NULL; size_t count = 0; Err e = ERR_SUCCESS;
    DIR *directory = opendir(home[0] ? home : ".");
    /* pathlib.glob suppresses directory listing OSErrors in the pinned Python. */
    if (!directory) return ERR_SUCCESS;
    struct dirent *entry;
    while (!e.code && (entry = readdir(directory))) {
        const char *name = entry->d_name; size_t n = strlen(name);
        if (n < 14 || strncmp(name, "state_", 6) || strcmp(name+n-7, ".sqlite")) continue;
        size_t end = n-7, start = 6, i = start;
        while (i < end && name[i] >= '0' && name[i] <= '9') i++;
        if (i != end) continue;
        while (start+1 < end && name[start] == '0') start++;
        Candidate item = {0};
        item.name = strdup(name);
        if (!item.name) { e = err_make(ERR_NOMEM, "metadata candidate allocation failed"); break; }
        item.number = (Str){item.name+start, (uint32_t)(end-start)};
        e = join(home, name, &item.path);
        Candidate *grown = e.code ? NULL : realloc(items, (count+1)*sizeof *items);
        if (!e.code && !grown) e = err_make(ERR_NOMEM, "metadata candidate allocation failed");
        if (e.code) { free(item.name); free(item.path); break; }
        items = grown; items[count++] = item;
    }
    closedir(directory);
    if (!e.code) e = stable_sort(items, count, sizeof *items, candidate_compare, NULL);
    for (size_t i = 0; !e.code && i < count; i++) {
        CodexMetadata db = {0}; Err attempt = read_database(items[i].path, items[i].name, &db);
        if (attempt.code) {
            metadata_destroy(&db);
            e = attempt.code == ERR_NOMEM ? attempt : error_append(m, items[i].name, attempt.message);
        } else {
            m->database_arena = db.arena; m->threads = db.threads;
            m->spawn_parents = db.spawn_parents; m->rollout_paths = db.rollout_paths;
            if (db.errors) { if (m->last_error) m->last_error->next = db.errors; else m->errors = db.errors; m->last_error = db.last_error; }
            break;
        }
    }
    for (size_t i = 0; i < count; i++) { free(items[i].path); free(items[i].name); }
    free(items); return e;
}
typedef struct { int64_t seconds; Str fraction; } IndexKey;
static Str json_string(yyjson_val *v) {
    return yyjson_is_str(v) ? (Str){yyjson_get_str(v), (uint32_t)yyjson_get_len(v)} : (Str){0};
}
static bool index_key(Arena *arena, Str timestamp, IndexKey *key, Err *error) {
    int64_t ms;
    if (!timestamp.p || !time_parse_rfc3339(timestamp, "metadata.index.updated_at", &ms)) return false;
    const char *dot = memchr(timestamp.p, '.', timestamp.n);
    Str fraction = STR_LIT("");
    if (dot) {
        const char *end = dot+1;
        while (end < timestamp.p+timestamp.n && *end >= '0' && *end <= '9') end++;
        size_t prefix = (size_t)(dot-timestamp.p), suffix = timestamp.n-(size_t)(end-timestamp.p);
        char *whole = malloc(prefix+suffix);
        if (!whole) { *error = err_make(ERR_NOMEM, "metadata timestamp allocation failed"); return false; }
        memcpy(whole, timestamp.p, prefix); memcpy(whole+prefix, end, suffix);
        bool valid = time_parse_rfc3339((Str){whole, (uint32_t)(prefix+suffix)}, "metadata.index.updated_at", &ms);
        free(whole);
        if (!valid) return false;
        while (end > dot+1 && end[-1] == '0') end--;
        fraction = (Str){dot+1, (uint32_t)(end-dot-1)};
    }
    (void)floordiv_i64(ms, 1000, &key->seconds);
    *error = str_copy(arena, fraction, &key->fraction);
    return !error->code;
}
static Err index_line(CodexMetadata *m, Omap *updated, Str line) {
    JsonRead read = json_read(line, STRICT, JSON_CONSTANTS_ALLOW, "metadata.index");
    Err e = ERR_SUCCESS;
    if (read.status == JSON_NOMEM) e = err_make(ERR_NOMEM, "metadata JSON allocation failed");
    yyjson_val *root = read.status == JSON_OK ? yyjson_doc_get_root(read.doc) : NULL;
    if (yyjson_is_obj(root)) {
        Str id = json_string(obj_get_last(root, STR_LIT("id")));
        Str title = json_string(obj_get_last(root, STR_LIT("thread_name")));
        IndexKey key;
        if (metadata_text(id) && metadata_text(title) && index_key(&m->arena,
                json_string(obj_get_last(root, STR_LIT("updated_at"))), &key, &e)) {
            IndexKey *old = omap_get(updated, id);
            if (!old || key.seconds > old->seconds || (key.seconds == old->seconds && str_compare(key.fraction, old->fraction) >= 0)) {
                IndexKey *owned;
                e = allocate(&m->arena, sizeof *owned, (void **)&owned);
                if (!e.code) { *owned = key; e = omap_put(updated, id, owned); }
                if (!e.code) e = put_text(&m->arena, &m->index_titles, id, title);
            }
        }
    }
    json_read_free(&read); return e;
}
static Err read_index(const char *home, CodexMetadata *m) {
    char *path = NULL; Err e = join(home, "session_index.jsonl", &path);
    if (e.code) return e;
    FILE *file = fopen(path, "rb"); free(path);
    char system[256];
    if (!file) return errno == ENOENT ? ERR_SUCCESS : error_append(m, "session_index.jsonl", err_system(errno, system));
    Omap updated = {0}; char *line = NULL; size_t capacity = 0; ssize_t n;
    while (!e.code && (n = getline(&line, &capacity, file)) >= 0) {
        if ((uint64_t)n > UINT32_MAX) continue;
        e = index_line(m, &updated, (Str){line, (uint32_t)n});
    }
    if (!e.code && ferror(file)) e = error_append(m, "session_index.jsonl", err_system(errno, system));
    free(line); fclose(file); omap_destroy(&updated); return e;
}
static Err read_global(const char *home, CodexMetadata *m) {
    char *path = NULL, *bytes = NULL; size_t n = 0;
    Err e = join(home, ".codex-global-state.json", &path);
    if (e.code) return e;
    e = file_read_all(path, &bytes, &n); int saved = errno; free(path);
    if (e.code) return e.code == ERR_NOMEM ? e : saved == ENOENT ? ERR_SUCCESS : error_append(m, ".codex-global-state.json", e.message);
    if (n > UINT32_MAX) { free(bytes); return ERR_SUCCESS; }
    JsonRead read = json_read((Str){bytes, (uint32_t)n}, STRICT, JSON_CONSTANTS_ALLOW, "metadata.global");
    free(bytes);
    if (read.status == JSON_NOMEM) e = err_make(ERR_NOMEM, "metadata JSON allocation failed");
    yyjson_val *root = read.status == JSON_OK ? yyjson_doc_get_root(read.doc) : NULL;
    yyjson_val *titles = obj_get_last(obj_get_last(root, STR_LIT("thread-titles")), STR_LIT("titles"));
    Omap dict = {0};
    if (yyjson_is_obj(titles)) e = json_object_dict(titles, &dict);
    for (OmapEntry *entry = dict.first; !e.code && entry; entry = entry->next) {
        Str title = json_string(entry->value);
        if (metadata_text(entry->key) && metadata_text(title)) e = put_text(&m->arena, &m->desktop_titles, entry->key, title);
    }
    omap_destroy(&dict); json_read_free(&read); return e;
}
Err metadata_load(const char *home, CodexMetadata *out) {
    Err e = databases(home, out);
    if (!e.code) e = read_index(home, out);
    if (!e.code) e = read_global(home, out);
    return e;
}
void metadata_destroy(CodexMetadata *m) {
    omap_destroy(&m->threads); omap_destroy(&m->index_titles); omap_destroy(&m->desktop_titles);
    omap_destroy(&m->spawn_parents); omap_destroy(&m->rollout_paths);
    arena_destroy(&m->arena); arena_destroy(&m->database_arena); memset(m, 0, sizeof *m);
}
