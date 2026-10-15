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
Err claude_foundation_model_suffix(Str model,bool version,size_t *offset) {
  *offset=SIZE_MAX;
  CFStringRef string=CFStringCreateWithBytes(NULL,(const UInt8 *)model.p,model.n,kCFStringEncodingUTF8,false);
  if(!string)return err_make(ERR_NOMEM,"Claude model string allocation");
  id pool=send(send((id)objc_getClass("NSAutoreleasePool"),"alloc"),"init");
  CFStringRef pattern=version?CFSTR("-v\\d+:\\d+$"):CFSTR("-\\d{8}$");
  /* NSRegularExpressionSearch is Foundation's 1 << 10 NSString option. */
  CFRange match=((CFRange (*)(id,SEL,CFStringRef,unsigned long))objc_msgSend)(
      (id)string,sel_registerName("rangeOfString:options:"),pattern,1UL<<10);
  if(match.location>=0&&match.length>0&&match.location+match.length==CFStringGetLength(string)){
    CFRange first=CFStringGetRangeOfComposedCharactersAtIndex(string,match.location),
            last=CFStringGetRangeOfComposedCharactersAtIndex(string,match.location+match.length-1);
    if(first.location==match.location&&last.location+last.length==match.location+match.length){
      CFIndex bytes=0;CFStringGetBytes(string,CFRangeMake(0,match.location),kCFStringEncodingUTF8,0,false,NULL,0,&bytes);*offset=(size_t)bytes;
    }
  }
  CFRelease(string);((void (*)(id,SEL))objc_msgSend)(pool,sel_registerName("drain"));return ERR_SUCCESS;
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
