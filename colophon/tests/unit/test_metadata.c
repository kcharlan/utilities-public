#define _DARWIN_C_SOURCE
#include "runner.h"
#include "meta/metadata.h"
#include <dirent.h>
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static size_t descriptors(void) {
    DIR *directory = opendir("/dev/fd"); ASSERT_TRUE(directory);
    size_t count = 0; struct dirent *entry;
    while ((entry = readdir(directory))) if (entry->d_name[0] != '.') count++;
    closedir(directory); return count;
}
TEST(metadata_closes_sqlite_and_owns_surviving_values) {
    char home[] = "/tmp/colophon-metadata-unit.XXXXXX"; ASSERT_TRUE(mkdtemp(home));
    char path[512]; snprintf(path, sizeof path, "%s/state_5.sqlite", home);
    sqlite3 *writer = NULL; ASSERT_EQ(SQLITE_OK, sqlite3_open(path, &writer));
    ASSERT_EQ(SQLITE_OK, sqlite3_exec(writer, "CREATE TABLE threads (id, name); INSERT INTO threads VALUES ('synthetic-id', 'Synthetic title')", NULL, NULL, NULL));
    ASSERT_EQ(SQLITE_OK, sqlite3_close(writer));
    size_t before = descriptors();
    for (int i = 0; i < 32; i++) {
        CodexMetadata m = {0}; ASSERT_EQ(ERR_OK, metadata_load(home, &m).code);
        MetadataThread *row = omap_get(&m.threads, STR_LIT("synthetic-id")); ASSERT_TRUE(row);
        ASSERT_EQ(META_TEXT, row->values[META_NAME].kind);
        ASSERT_TRUE(str_equal(STR_LIT("Synthetic title"), row->values[META_NAME].value.bytes));
        /* A writer can take an exclusive lock while owned metadata remains live. */
        ASSERT_EQ(SQLITE_OK, sqlite3_open(path, &writer));
        ASSERT_EQ(SQLITE_OK, sqlite3_exec(writer, "BEGIN EXCLUSIVE; ROLLBACK", NULL, NULL, NULL));
        ASSERT_EQ(SQLITE_OK, sqlite3_close(writer));
        metadata_destroy(&m);
        ASSERT_EQ(before, descriptors());
    }
    ASSERT_EQ(SQLITE_OK, sqlite3_open(path, &writer));
    ASSERT_EQ(SQLITE_OK, sqlite3_exec(writer, "DROP TABLE threads; CREATE TABLE threads (name)", NULL, NULL, NULL));
    ASSERT_EQ(SQLITE_OK, sqlite3_close(writer));
    for (int i = 0; i < 32; i++) {
        CodexMetadata m = {0}; ASSERT_EQ(ERR_OK, metadata_load(home, &m).code);
        ASSERT_TRUE(m.errors); ASSERT_TRUE(!m.errors->next);
        ASSERT_TRUE(str_equal(STR_LIT("state_5.sqlite: threads table missing id column"), m.errors->text));
        metadata_destroy(&m); ASSERT_EQ(before, descriptors());
    }
    ASSERT_EQ(0, unlink(path)); ASSERT_EQ(0, rmdir(home));
}
