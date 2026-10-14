#include "logname.h"

static bool suffix_ci(Str name, const char *suffix, uint32_t n) {
    if (name.n < n) return false;
    for (uint32_t i = 0; i < n; i++) {
        char c = name.p[name.n - n + i];
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (c != suffix[i]) return false;
    }
    return true;
}

LogNameFormat log_name_format(Str path) {
    Str name = path;
    for (uint32_t i = path.n; i > 0; i--)
        if (path.p[i - 1] == '/') { name = (Str){path.p + i, path.n - i}; break; }
    bool zstd = suffix_ci(name, ".zst", 4);
    if (zstd) name.n -= 4;
    /* ".jsonl" holds no other dot, so it is the final suffix; length > 6
     * keeps it from starting the name. */
    if (name.n <= 6 || !suffix_ci(name, ".jsonl", 6)) return LOG_NAME_OTHER;
    return zstd ? LOG_NAME_ZSTD : LOG_NAME_PLAIN;
}
