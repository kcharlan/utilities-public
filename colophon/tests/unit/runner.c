#include "runner.h"

#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>

static TestCase *first;
static TestCase **tail = &first;
static jmp_buf failure;
static unsigned count;
static unsigned failed;

void test_register(TestCase *test) {
    *tail = test;
    tail = &test->next;
}

_Noreturn void test_fail(const char *file, int line, const char *expression) {
    fprintf(stderr, "%s:%d: assertion failed: %s\n", file, line, expression);
    longjmp(failure, 1);
}

int main(void) {
    for (TestCase *test = first; test != NULL; test = test->next) {
        ++count;
        if (setjmp(failure) == 0) {
            test->run();
            printf("PASS %s\n", test->name);
        } else {
            ++failed;
            printf("FAIL %s\n", test->name);
        }
    }
    printf("%u test(s), %u failure(s)\n", count, failed);
    return failed == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
