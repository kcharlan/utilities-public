#ifndef COLOPHON_GEN_ASSETS_H
#define COLOPHON_GEN_ASSETS_H
#include <stddef.h>
#include <stdint.h>
#define CP_DECLARE_ASSET(name) \
    extern const unsigned char cp_asset_##name[]; \
    extern const size_t cp_asset_##name##_len
CP_DECLARE_ASSET(page_template);
CP_DECLARE_ASSET(font_css);
CP_DECLARE_ASSET(page_css);
CP_DECLARE_ASSET(page_js);
CP_DECLARE_ASSET(ofl);
CP_DECLARE_ASSET(curated_bundled);
CP_DECLARE_ASSET(curated_bundled_claude);
CP_DECLARE_ASSET(ccusage_fast_multiplier_overrides);
CP_DECLARE_ASSET(curated_price_history);
#undef CP_DECLARE_ASSET
#define CP_DECLARE_RANGES(name) \
    extern const uint32_t cp_pricing_##name##_ranges[][2]; \
    extern const size_t cp_pricing_##name##_ranges_count
CP_DECLARE_RANGES(numeric);
CP_DECLARE_RANGES(extend);
CP_DECLARE_RANGES(prepend);
#undef CP_DECLARE_RANGES
#endif
