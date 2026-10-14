#include "model.h"
#include "gen/assets.h"
#include "parse/tokenstream.h"
#include <string.h>
#include <stdlib.h>
static bool in_ranges(uint32_t cp, const uint32_t ranges[][2], size_t n) {
  size_t lo = 0, hi = n;
  while (lo < hi) {
    size_t mid = lo + (hi - lo) / 2;
    if (cp < ranges[mid][0])
      hi = mid;
    else if (cp > ranges[mid][1])
      lo = mid + 1;
    else
      return true;
  }
  return false;
}
bool price_character_extend(uint32_t cp) {
  return in_ranges(cp, cp_pricing_extend_ranges,
                   cp_pricing_extend_ranges_count);
}
bool price_character_prepend(uint32_t cp) {
  return in_ranges(cp, cp_pricing_prepend_ranges,
                   cp_pricing_prepend_ranges_count);
}
size_t price_literal_parts(Str haystack, Str needle, Str suffix, bool last) {
  size_t offset=0, result=SIZE_MAX, width=(size_t)needle.n+suffix.n;
  uint32_t previous=0, cp;
  while (offset<haystack.n) {
    size_t start=offset;
    if (!str_decode_next(haystack,&offset,&cp)) break;
    if (width<=haystack.n-start && !memcmp(haystack.p+start,needle.p,needle.n) &&
        !memcmp(haystack.p+start+needle.n,suffix.p,suffix.n) && !price_character_prepend(previous)) {
      size_t end=start+width; uint32_t next;
      if (!str_decode_next(haystack,&end,&next) || !price_character_extend(next)) {
        result=start; if (!last) break;
      }
    }
    previous=cp;
  }
  return result;
}
static bool numeric(uint32_t cp) {
  return in_ranges(cp, cp_pricing_numeric_ranges,
                   cp_pricing_numeric_ranges_count);
}
static bool curated(Str model) {
  const char *p = (const char *)cp_asset_curated_bundled;
  size_t depth = 0;
  for (size_t i = 0; i < cp_asset_curated_bundled_len; i++) {
    if (p[i] == '{' || p[i] == '[') {
      depth++;
    } else if (p[i] == '}' || p[i] == ']') {
      depth--;
    } else if (p[i] == '"') {
      size_t start = ++i;
      for (; i < cp_asset_curated_bundled_len && p[i] != '"'; i++)
        if (p[i] == '\\')
          i++;
      size_t next = i + 1;
      while (next < cp_asset_curated_bundled_len &&
             (p[next] == ' ' || p[next] == '\n' || p[next] == '\r' ||
              p[next] == '\t'))
        next++;
      /* Only the pinned catalog's outer model keys are normalization names. */
      if (depth == 1 && i - start == model.n &&
          !memcmp(p + start, model.p, model.n) &&
          next < cp_asset_curated_bundled_len && p[next] == ':')
        return true;
    }
  }
  return false;
}
static bool hyphen(Str text, size_t *at) {
  uint32_t cp;
  size_t next = *at;
  if (!str_decode_next(text, &next, &cp) || cp != '-')
    return false;
  size_t after = next;
  if (str_decode_next(text, &after, &cp) && price_character_extend(cp))
    return false;
  *at = next;
  return true;
}
static bool digits(Str text, size_t *at, size_t count, bool ascii) {
  for (size_t i = 0; i < count; i++) {
    uint32_t cp;
    size_t next = *at;
    if (!str_decode_next(text, &next, &cp) ||
        !(ascii ? (cp >= '0' && cp <= '9') : numeric(cp)))
      return false;
    if (!ascii)
      for (;;) {
        size_t after = next;
        if (!str_decode_next(text, &after, &cp) || !price_character_extend(cp))
          break;
        next = after;
      }
    *at = next;
  }
  return true;
}
Str normalize_codex_model(Str value) {
  value = token_model_trim(value);
  size_t next = 7;
  uint32_t cp;
  if (value.n >= 7 && !memcmp(value.p, "openai/", 7) &&
      (!str_decode_next(value, &next, &cp) || !price_character_extend(cp))) {
    value.p += 7;
    value.n -= 7;
  }
  if (str_equal(value, STR_LIT("gpt-5.6")) ||
      str_equal(value, STR_LIT("gpt-daybreak-blue-latest")))
    return STR_LIT("gpt-5.6-sol");
  if (str_equal(value, STR_LIT("gpt-reserve")))
    return STR_LIT("gpt-5.6-luna");
  if (str_equal(value, STR_LIT("gpt-daybreak-red-latest")))
    return STR_LIT("gpt-5.6-cyber");
  if (curated(value))
    return value;
  bool ascii = true;
  for (size_t i = 0; i < value.n; i++)
    if ((unsigned char)value.p[i] >= 128)
      ascii = false;
  size_t offset = 0;
  uint32_t previous = 0;
  while (offset < value.n) {
    size_t start = offset;
    if (!str_decode_next(value, &offset, &cp))
      break;
    if (cp == '-' && (ascii || !price_character_prepend(previous))) {
      size_t at = start;
      if (hyphen(value, &at) && digits(value, &at, 4, ascii) &&
          hyphen(value, &at) && digits(value, &at, 2, ascii) &&
          hyphen(value, &at) && digits(value, &at, 2, ascii) && at == value.n) {
        Str base = {value.p, (uint32_t)start};
        if (curated(base))
          return base;
      }
    }
    previous = cp;
  }
  return value;
}
double codex_api_fast_multiplier(Str model) {
  Str key=normalize_codex_model(model);
  if (str_equal(key,STR_LIT("gpt-5.5"))) return 2.5;
  const Str models[]={STR_LIT("gpt-5.4"),STR_LIT("gpt-5.4-mini"),STR_LIT("gpt-5.6-sol"),
    STR_LIT("gpt-5.6-terra"),STR_LIT("gpt-5.6-luna"),STR_LIT("gpt-6-astra")};
  for (size_t i=0;i<sizeof models/sizeof *models;i++) if (str_equal(key,models[i])) return 2.0;
  return 0;
}
Err normalize_codex_model_memo(Arena *arena,Omap *memo,Str raw,Str *out) {
  Str *cached=omap_get(memo,raw);
  if(cached){*out=*cached;return ERR_SUCCESS;}
  Err e=arena_alloc(arena,sizeof *cached,_Alignof(Str),(void **)&cached);
  if(e.code)return e;
  e=str_copy(arena,normalize_codex_model(raw),cached);if(e.code)return e;
  e=omap_put(memo,raw,cached);if(!e.code)*out=*cached;return e;
}
typedef struct { Str value, identity; } Candidate;
static Err candidate_append(Arena *arena, Candidate **items, size_t *count, Str value) {
  value=token_model_trim(value);
  if (!value.n) return ERR_SUCCESS;
  Str identity;
  Err error=str_nfc(arena,value,"price.candidate",&identity);
  if (error.code) return error;
  for (size_t i=0;i<*count;i++) if (str_equal((*items)[i].identity,identity)) return ERR_SUCCESS;
  if (*count==SIZE_MAX/sizeof **items) return err_make(ERR_NOMEM,"candidate overflow");
  Candidate *grown=realloc(*items,(*count+1)*sizeof **items);
  if (!grown) return err_make(ERR_NOMEM,"candidate allocation failed");
  *items=grown;
  Str copy;
  error=str_copy(arena,value,&copy);
  if (error.code) return error;
  grown[(*count)++]=(Candidate){copy,identity};
  return ERR_SUCCESS;
}
static Err candidate_join(Arena *arena, Candidate **items,size_t *count,Str a,Str b) {
  char *bytes;
  Err e=arena_alloc(arena,(size_t)a.n+b.n,1,(void **)&bytes);
  if (e.code) return e;
  memcpy(bytes,a.p,a.n); memcpy(bytes+a.n,b.p,b.n);
  return candidate_append(arena,items,count,(Str){bytes,a.n+b.n});
}
Err models_dev_candidates(Arena *arena,Str raw,ModelCandidates *out) {
  Candidate *items=NULL; size_t count=0; Err error=ERR_SUCCESS;
#define APPEND(v) do {error=candidate_append(arena,&items,&count,(v));if(error.code)goto done;}while(0)
#define JOIN(a,b) do {error=candidate_join(arena,&items,&count,(a),(b));if(error.code)goto done;}while(0)
  Str trimmed=token_model_trim(raw); APPEND(trimmed);
  if (price_literal_parts(trimmed,STR_LIT("openai/"),STR_LIT(""),false)==0)
    APPEND(((Str){trimmed.p+7,trimmed.n-7}));
  if (price_literal_parts(trimmed,STR_LIT("anthropic."),STR_LIT(""),false)==0)
    APPEND(((Str){trimmed.p+10,trimmed.n-10}));
  size_t dot=price_literal_parts(trimmed,STR_LIT("."),STR_LIT(""),true);
  if (dot!=SIZE_MAX && price_literal_parts(trimmed,STR_LIT("claude-"),STR_LIT(""),false)!=SIZE_MAX) {
    Str tail={trimmed.p+dot+1,trimmed.n-(uint32_t)dot-1};
    if (price_literal_parts(tail,STR_LIT("claude-"),STR_LIT(""),false)==0) APPEND(tail);
  }
  for (size_t i=0;i<count;i++) {
    Str v=items[i].value;
    size_t at=price_literal_parts(v,STR_LIT("@"),STR_LIT(""),false);
    if (at!=SIZE_MAX) {
      Str base={v.p,(uint32_t)at}, suffix={v.p+at+1,v.n-(uint32_t)at-1};
      size_t end=0;
      if (digits(suffix,&end,8,false) && end==suffix.n) {
        Str dated; char *bytes;
        error=arena_alloc(arena,(size_t)base.n+1+suffix.n,1,(void **)&bytes);
        if(error.code)goto done;
        memcpy(bytes,base.p,base.n); bytes[base.n]='-';memcpy(bytes+base.n+1,suffix.p,suffix.n);
        dated=(Str){bytes,base.n+1+suffix.n}; APPEND(dated);
      }
      APPEND(base);
    } else if (price_literal_parts(v,STR_LIT("claude-"),STR_LIT(""),false)==0) JOIN(v,STR_LIT("@default"));
    size_t offset=0; uint32_t previous=0,cp;
    while(offset<v.n) {
      size_t start=offset;
      if (!str_decode_next(v,&offset,&cp)) break;
      if(cp=='-'&&!price_character_prepend(previous)) {
        size_t end=start;
        bool date=hyphen(v,&end)&&digits(v,&end,4,false)&&hyphen(v,&end)&&digits(v,&end,2,false)&&hyphen(v,&end)&&digits(v,&end,2,false)&&end==v.n;
        end=start;
        date=date||(hyphen(v,&end)&&digits(v,&end,8,false)&&end==v.n);
        if(date) APPEND(((Str){v.p,(uint32_t)start}));
        end=start;
        if (price_literal_parts((Str){v.p+start,v.n-(uint32_t)start},STR_LIT("-v"),STR_LIT(""),false)==0) {
          end=start+2; size_t first=end;
          while (digits(v,&end,1,false)) {}
          if(end>first && price_literal_parts((Str){v.p+end,v.n-(uint32_t)end},STR_LIT(":"),STR_LIT(""),false)==0) {
            first=++end; while(digits(v,&end,1,false)){}
            if(end>first&&end==v.n) APPEND(((Str){v.p,(uint32_t)start}));
          }
        }
      }
      previous=cp;
    }
  }
  error=arena_alloc(arena,count*sizeof(Str),_Alignof(Str),(void **)&out->items);
  if(!error.code) {out->count=count;for(size_t i=0;i<count;i++)out->items[i]=items[i].value;}
done:
  free(items); return error;
#undef APPEND
#undef JOIN
}
