#define _DARWIN_C_SOURCE
#include "runner.h"
#include "antigravity_fixture.h"
#include "opencode_fixture.h"
#include "meta/metadata.h"
#include "opencode/db.h"
#include "price/priority.h"
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

/* A writer whose SQLite deletes its WAL on last close (Codex's bundled build)
 * leaves a WAL-mode database with neither -wal nor -shm. macOS's system SQLite
 * cannot read that through a read-only connection (SQLITE_CANTOPEN); Homebrew
 * SQLite, which Colophon links, creates both files and reads normally. Every
 * read-only reader must keep reading such a database. */
static bool sidecar_exists(const char *path, const char *suffix) {
    char sidecar[700]; snprintf(sidecar, sizeof sidecar, "%s%s", path, suffix);
    struct stat st; return !stat(sidecar, &st);
}
static void close_without_wal(sqlite3 *writer, const char *path) {
    sqlite3_stmt *stmt = NULL;
    ASSERT_EQ(SQLITE_OK, sqlite3_prepare_v2(writer, "PRAGMA journal_mode=WAL", -1, &stmt, NULL));
    ASSERT_EQ(SQLITE_ROW, sqlite3_step(stmt));
    ASSERT_STREQ("wal", (const char *)sqlite3_column_text(stmt, 0));
    ASSERT_EQ(SQLITE_OK, sqlite3_finalize(stmt));
    /* Explicit: macOS's system SQLite persists the WAL by default. */
    int persist = 0;
    ASSERT_EQ(SQLITE_OK, sqlite3_file_control(writer, "main", SQLITE_FCNTL_PERSIST_WAL, &persist));
    ASSERT_EQ(SQLITE_OK, sqlite3_close(writer));
    ASSERT_FALSE(sidecar_exists(path, "-wal")); ASSERT_FALSE(sidecar_exists(path, "-shm"));
    unsigned char header[20]; FILE *in = fopen(path, "rb"); ASSERT_TRUE(in);
    ASSERT_EQ(sizeof header, fread(header, 1, sizeof header, in)); ASSERT_EQ(0, fclose(in));
    ASSERT_EQ(2, header[18]); ASSERT_EQ(2, header[19]);
}
static void remove_database(const char *path) {
    const char *suffixes[] = {"", "-wal", "-shm"};
    for (size_t i = 0; i < 3; i++) {
        char file[700]; snprintf(file, sizeof file, "%s%s", path, suffixes[i]); unlink(file);
    }
}
static void scratch_home(char *home, size_t size, const char *name) {
    const char *scratch = getenv("TMPDIR"); ASSERT_TRUE(scratch && scratch[0]);
    int length = snprintf(home, size, "%s/%s.XXXXXX", scratch, name);
    ASSERT_TRUE(length > 0 && (size_t)length < size); ASSERT_TRUE(mkdtemp(home));
}
static sqlite3 *writer_open(const char *path, const char *sql) {
    sqlite3 *writer = NULL; ASSERT_EQ(SQLITE_OK, sqlite3_open(path, &writer));
    ASSERT_EQ(SQLITE_OK, sqlite3_exec(writer, sql, NULL, NULL, NULL));
    return writer;
}
TEST(closed_wal_codex_metadata_reads) {
    char home[256]; scratch_home(home, sizeof home, "closed-wal-metadata");
    char path[300]; snprintf(path, sizeof path, "%s/state_5.sqlite", home);
    close_without_wal(writer_open(path, "CREATE TABLE threads (id, name); INSERT INTO threads VALUES ('synthetic-id', 'Synthetic title')"), path);
    CodexMetadata m = {0}; ASSERT_EQ(ERR_OK, metadata_load(home, &m).code);
    ASSERT_FALSE(m.errors);
    MetadataThread *row = omap_get(&m.threads, STR_LIT("synthetic-id")); ASSERT_TRUE(row);
    ASSERT_TRUE(str_equal(STR_LIT("Synthetic title"), row->values[META_NAME].value.bytes));
    metadata_destroy(&m);
    remove_database(path); ASSERT_EQ(0, rmdir(home));
}
TEST(closed_wal_codex_priority_trace_reads) {
    char home[256]; scratch_home(home, sizeof home, "closed-wal-priority");
    char path[300], runtime[300], turns[340];
    snprintf(path, sizeof path, "%s/logs_2.sqlite", home);
    snprintf(runtime, sizeof runtime, "%s/runtime", home); ASSERT_EQ(0, mkdir(runtime, 0700));
    snprintf(turns, sizeof turns, "%s/priority-turns.json", runtime);
    close_without_wal(writer_open(path, "CREATE TABLE logs (ts INTEGER, feedback_log_body TEXT);"
        "INSERT INTO logs VALUES (1, 'session_loop{thread_id=synthetic-thread}:turn{turn.id=synthetic-turn}: "
        "websocket request: {\"type\":\"response.create\",\"service_tier\":\"priority\",\"model\":\"synthetic-model\"}')"), path);
    PriorityTurns p = {0}; ASSERT_EQ(ERR_OK, priority_load(home, runtime, &p).code);
    ASSERT_FALSE(p.messages);
    PriorityEntry *entry = omap_get(&p.turns, STR_LIT("synthetic-turn")); ASSERT_TRUE(entry);
    ASSERT_TRUE(str_equal(STR_LIT("synthetic-thread"), entry->thread_id));
    ASSERT_TRUE(str_equal(STR_LIT("synthetic-model"), entry->model));
    priority_destroy(&p);
    ASSERT_EQ(0, unlink(turns)); ASSERT_EQ(0, rmdir(runtime));
    remove_database(path); ASSERT_EQ(0, rmdir(home));
}
TEST(closed_wal_opencode_reads) {
    OpencodeFixture f; opencode_fixture_open(&f); opencode_fixture_session(&f, "synthetic-session");
    close_without_wal(f.writer, f.path); f.writer = NULL;
    OpencodeStore s = {0};
    ASSERT_EQ(ERR_OK, opencode_store_add_database(&s, (Str){f.path, (uint32_t)strlen(f.path)}, true).code);
    ASSERT_EQ(ERR_OK, opencode_store_read(&s, NULL).code);
    ASSERT_EQ(OC_DB_OK, s.databases[0].status); ASSERT_EQ(1, s.session_count);
    ASSERT_TRUE(str_equal(STR_LIT("synthetic-session"), s.sessions[0]->id));
    opencode_store_destroy(&s); opencode_fixture_close(&f);
}
TEST(closed_wal_antigravity_conversation_and_summary_read) {
    AntigravityFixture f; antigravity_fixture_open(&f);
    antigravity_fixture_summary(&f, "CREATE TABLE conversation_summaries(conversation_id,title);"
        "INSERT INTO conversation_summaries VALUES('" AG_SYNTHETIC_ID "','Synthetic closed WAL title')");
    close_without_wal(f.writer, f.path); f.writer = NULL;
    char summary[600]; snprintf(summary, sizeof summary, "%s/antigravity/conversation_summaries.db", f.home);
    close_without_wal(writer_open(summary, "SELECT 1"), summary);
    AntigravityStore s = {0}; antigravity_fixture_read(&f, &s);
    ASSERT_EQ(AG_DB_OK, s.databases[0].status); ASSERT_EQ(1, s.session_count);
    ASSERT_TRUE(s.sessions[0]->summary_valid);
    ASSERT_TRUE(str_equal(STR_LIT("Synthetic closed WAL title"), s.sessions[0]->title));
    antigravity_store_destroy(&s);
    remove_database(summary); antigravity_fixture_close(&f);
}
