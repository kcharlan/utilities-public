#ifndef CP_TEST_CACHE_FAULTS_H
#define CP_TEST_CACHE_FAULTS_H
#ifdef COLOPHON_TESTING
#include "util/err.h"
Err test_cache_replace_backup(const char *home, const char *old);
Err test_cache_prune_barrier(void);
#endif
#endif
