#include "sort.h"
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
static void merge_sort(char *p, char *tmp, size_t n, size_t w, SortCompare cmp,
                       void *ctx) {
    if (n < 2)
        return;
    size_t mid = n / 2;
    merge_sort(p, tmp, mid, w, cmp, ctx);
    merge_sort(p + mid * w, tmp, n - mid, w, cmp, ctx);
    size_t i = 0, j = mid, k = 0;
    while (i < mid && j < n) {
        size_t pick = cmp(p + i * w, p + j * w, ctx) <= 0 ? i++ : j++;
        memcpy(tmp + k++ * w, p + pick * w, w);
    }
    while (i < mid) {
        memcpy(tmp + k++ * w, p + i++ * w, w);
    }
    while (j < n) {
        memcpy(tmp + k++ * w, p + j++ * w, w);
    }
    memcpy(p, tmp, n * w);
}
Err stable_sort(void *p, size_t n, size_t w, SortCompare cmp, void *ctx) {
    if (n < 2)
        return ERR_SUCCESS;
    if (!w || !p || !cmp)
        return err_make(ERR_INVALID, "invalid sort arguments");
    if (n > SIZE_MAX / w)
        return err_make(ERR_NOMEM, "sort size overflow");
    char *tmp = malloc(n * w);
    if (!tmp)
        return err_make(ERR_NOMEM, "sort allocation failed");
    merge_sort(p, tmp, n, w, cmp, ctx);
    free(tmp);
    return ERR_SUCCESS;
}
