#ifndef CP_PAGE_H
#define CP_PAGE_H
#include "jsonw.h"
/* Replace head placeholders only; data is appended without substitution. */
Err page_render(const JsonWriter *payload,JsonWriter *page);
#endif
