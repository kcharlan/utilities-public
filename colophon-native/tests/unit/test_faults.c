#define _POSIX_C_SOURCE 200809L
#include "runner.h"
#include "testing/hooks.h"
#include <pthread.h>
#include <stdlib.h>
TEST(fault_points_independent_counters_reset_and_malformed_policy) {
    ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT", "scan:3,build_corpus:2", 1));
    bool a = cp_fault("scan"), b = cp_fault("build_corpus"), c = cp_fault("scan"),
         d = cp_fault("build_corpus"), e = cp_fault("scan");
    ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
    bool absent = cp_fault("scan");
    ASSERT_FALSE(a || b || c || absent);
    ASSERT_TRUE(d && e);
    ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT", "scan:3,build_corpus:2", 1));
    a = cp_fault("scan");
    ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
    (void)cp_fault("scan");
    ASSERT_FALSE(a);
    ASSERT_EQ(
        0, setenv("COLOPHON_TEST_FAULT", "scan:bad,scan,scan:2,build_corpus:0,scan_prefix,,", 1));
    a = cp_fault("scan");
    b = cp_fault("scan");
    c = cp_fault("build_corpus");
    ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
    (void)cp_fault("scan");
    ASSERT_TRUE(a && b);
    ASSERT_FALSE(c);
}
typedef struct {
    int hits;
} FaultWorker;
static void *fault_worker(void *context) {
    FaultWorker *worker = context;
    for (int i = 0; i < 1000; i++) {
        worker->hits += cp_fault("scan");
        worker->hits += cp_fault("build_corpus");
    }
    return NULL;
}
TEST(fault_points_thread_safe_occurrence_counters) {
    ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT", "scan:640,build_corpus:320", 1));
    pthread_t threads[8];
    FaultWorker workers[8] = {0};
    for (int i = 0; i < 8; i++)
        ASSERT_EQ(0, pthread_create(&threads[i], NULL, fault_worker, &workers[i]));
    int hits = 0;
    for (int i = 0; i < 8; i++) {
        ASSERT_EQ(0, pthread_join(threads[i], NULL));
        hits += workers[i].hits;
    }
    ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
    (void)cp_fault("scan");
    ASSERT_EQ(2, hits);
}
