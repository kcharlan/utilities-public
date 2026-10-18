#ifndef CP_OPENCODE_FIXTURE_H
#define CP_OPENCODE_FIXTURE_H
#include <sqlite3.h>
typedef struct { char home[128], path[256]; sqlite3 *writer; } OpencodeFixture;
void opencode_fixture_open(OpencodeFixture *fixture);
void opencode_fixture_sql(OpencodeFixture *fixture, const char *sql);
void opencode_fixture_session(OpencodeFixture *fixture, const char *id);
void opencode_fixture_message(OpencodeFixture *fixture, const char *id, const char *session,
                              const char *type, int seq, const char *json);
void opencode_fixture_close(OpencodeFixture *fixture);
#endif
