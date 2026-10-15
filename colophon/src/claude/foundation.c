#include "foundation.h"
#include <CoreFoundation/CoreFoundation.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <stdlib.h>
#include <string.h>
static id send(id value, const char *selector) {
  return ((id (*)(id, SEL))objc_msgSend)(value, sel_registerName(selector));
}
/* Decode through the actual system implementation rather than recreating
 * NSDecimalNumber's mantissa/exponent rounding and NSNumber coercion. */
static CFTypeRef decode(Str bytes) {
  CFDataRef data = CFDataCreate(NULL, (const UInt8 *)bytes.p, bytes.n);
  if (!data)
    return NULL;
  id pool = send(send((id)objc_getClass("NSAutoreleasePool"), "alloc"), "init");
  id value = ((id (*)(id, SEL, CFDataRef, unsigned long, id *))objc_msgSend)(
      (id)objc_getClass("NSJSONSerialization"),
      sel_registerName("JSONObjectWithData:options:error:"), data, 0, NULL);
  CFTypeRef result = value ? CFRetain((CFTypeRef)value) : NULL;
  CFRelease(data);
  ((void (*)(id, SEL))objc_msgSend)(pool, sel_registerName("drain"));
  return result;
}
bool claude_foundation_object_valid(Str bytes) {
  CFTypeRef object = decode(bytes);
  bool valid = object && CFGetTypeID(object) == CFDictionaryGetTypeID();
  if (object)
    CFRelease(object);
  return valid;
}
bool claude_foundation_number(Str literal, int64_t *integer, bool *boolean) {
  if (literal.n > UINT32_MAX - 2)
    return false;
  char *bytes = malloc((size_t)literal.n + 2);
  if (!bytes)
    return false;
  bytes[0] = '[';
  memcpy(bytes + 1, literal.p, literal.n);
  bytes[literal.n + 1] = ']';
  CFTypeRef array = decode((Str){bytes, literal.n + 2});
  free(bytes);
  if (!array)
    return false;
  bool valid = CFGetTypeID(array) == CFArrayGetTypeID() &&
               CFArrayGetCount((CFArrayRef)array) == 1;
  if (valid) {
    id value = (id)CFArrayGetValueAtIndex((CFArrayRef)array, 0);
    valid = CFGetTypeID((CFTypeRef)value) == CFNumberGetTypeID();
    if (valid) {
      *integer = ((int64_t (*)(id, SEL))objc_msgSend)(
          value, sel_registerName("longLongValue"));
      *boolean = ((bool (*)(id, SEL))objc_msgSend)(
          value, sel_registerName("boolValue"));
    }
  }
  CFRelease(array);
  return valid;
}
