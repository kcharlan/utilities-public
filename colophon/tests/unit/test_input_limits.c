#define _DARWIN_C_SOURCE
#include "corpus/workspaces.h"
#include "price/catalog.h"
#include "runner.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

TEST(workspace_alias_file_over_limit_is_rejected) {
  char path[1024]; snprintf(path, sizeof path, "%s/colophon-workspace-limit.XXXXXX", getenv("TMPDIR"));
  int fd = mkstemp(path); ASSERT_TRUE(fd >= 0);
  ASSERT_EQ(0, ftruncate(fd, 65537)); ASSERT_EQ(0, close(fd));
  WorkspaceAliases aliases = {0};
  ASSERT_EQ(ERR_OK, workspace_aliases_load(path, &aliases).code);
  ASSERT_EQ(1, aliases.errors.count);
  ASSERT_TRUE(strstr(aliases.errors.items[0].p, "too large"));
  workspace_aliases_destroy(&aliases); ASSERT_EQ(0, unlink(path));
}
TEST(catalog_cache_file_over_limit_is_rejected) {
  char path[1024]; snprintf(path, sizeof path, "%s/colophon-catalog-limit.XXXXXX", getenv("TMPDIR"));
  int fd = mkstemp(path); ASSERT_TRUE(fd >= 0);
  ASSERT_EQ(0, ftruncate(fd, 33554433)); ASSERT_EQ(0, close(fd));
  CatalogResult catalog = {0};
  ASSERT_EQ(ERR_OK, catalog_load_offline(path, STR_LIT("https://example.invalid"), &catalog).code);
  ASSERT_TRUE(catalog.messages);
  ASSERT_TRUE(strstr(catalog.messages->text.p, "too large"));
  catalog_result_destroy(&catalog); ASSERT_EQ(0, unlink(path));
}
