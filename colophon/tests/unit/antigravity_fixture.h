#ifndef CP_ANTIGRAVITY_FIXTURE_H
#define CP_ANTIGRAVITY_FIXTURE_H
#include "antigravity/scan.h"
#include <sqlite3.h>
/* Invented UUID namespace; all mutable files are external private scratch. */
#define AG_SYNTHETIC_ID "00000000-0000-4000-8000-000000000001"
typedef struct { char home[256],path[512];sqlite3 *writer; } AntigravityFixture;
void antigravity_fixture_open(AntigravityFixture *f);
void antigravity_fixture_sql(AntigravityFixture *f,const char *sql);
void antigravity_fixture_annotation(AntigravityFixture *f,const char *bytes);
void antigravity_fixture_summary(AntigravityFixture *f,const char *sql);
void antigravity_fixture_read(AntigravityFixture *f,AntigravityStore *s);
void antigravity_fixture_close(AntigravityFixture *f);
#endif
