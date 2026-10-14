#ifndef COLOPHON_TEST_RUNNER_H
#define COLOPHON_TEST_RUNNER_H

#include <stdint.h>
#include <string.h>

typedef struct TestCase {
    const char *name;
    void (*run)(void);
    struct TestCase *next;
} TestCase;

void test_register(TestCase *test);
_Noreturn void test_fail(const char *file, int line, const char *expression);

#define TEST(name) \
    static void test_##name(void); \
    static TestCase case_##name = {#name, test_##name, NULL}; \
    static void __attribute__((constructor)) register_##name(void) { \
        test_register(&case_##name); \
    } \
    static void test_##name(void)
#define ASSERT_TRUE(expression) do { \
    if (!(expression)) test_fail(__FILE__, __LINE__, #expression); \
} while (0)
#define ASSERT_FALSE(expression) ASSERT_TRUE(!(expression))
#define ASSERT_EQ(expected, actual) do { \
    if (!((expected) == (actual))) \
        test_fail(__FILE__, __LINE__, #expected " == " #actual); \
} while (0)
#define ASSERT_STREQ(expected, actual) do { \
    const char *test_expected = (expected); \
    const char *test_actual = (actual); \
    if (test_expected == NULL || test_actual == NULL || \
        strcmp(test_expected, test_actual) != 0) \
        test_fail(__FILE__, __LINE__, #expected " equals " #actual); \
} while (0)

#endif
