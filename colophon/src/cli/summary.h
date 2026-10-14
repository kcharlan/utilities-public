#ifndef CP_SUMMARY_H
#define CP_SUMMARY_H
#include <stdbool.h>
#include <stddef.h>
#include "out/payload.h"
Err summary_run(const char *output,size_t page_size,const PayloadInputs *inputs);
#endif
