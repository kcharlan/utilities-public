#ifndef CP_PROGRESS_H
#define CP_PROGRESS_H
#include "util/err.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
bool progress_tty(void);
Err progress_scan_start(double *start);
typedef struct {bool tty,active;size_t width;double start;} ScanDisplay;
Err progress_update(uint64_t done,uint64_t total,void *context);
void progress_close(ScanDisplay *display);
#endif
