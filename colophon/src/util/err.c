#include "err.h"
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
const char *err_system(int number, char buffer[256]) {
    if (strerror_r(number, buffer, 256))
        snprintf(buffer, 256, "OS error %d", number);
    return buffer;
}
Err err_make(ErrCode code, const char *format, ...) {
    Err e = {.code = code};
    va_list ap;
    va_start(ap, format);
    if (format)
        vsnprintf(e.message, sizeof(e.message), format, ap);
    va_end(ap);
    return e;
}
