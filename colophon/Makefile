CC := clang
BUILD ?= build
RELEASE_BIN ?= colophon
SQLITE_PREFIX ?= /opt/homebrew/opt/sqlite
OPTFLAGS ?= -O2
override CFLAGS += -std=c17 $(OPTFLAGS) -g -Wall -Wextra -Wpedantic -Werror -fno-fast-math -ffp-contract=off
override CPPFLAGS += -Isrc -Ivendor/yyjson -Ivendor/zstd -I$(SQLITE_PREFIX)/include
override LDLIBS += -lpthread -lcurl -framework CoreFoundation -L$(SQLITE_PREFIX)/lib -lsqlite3

ZSTD_SOURCES := vendor/zstd/common/debug.c vendor/zstd/common/entropy_common.c \
                vendor/zstd/common/error_private.c vendor/zstd/common/fse_decompress.c \
                vendor/zstd/common/xxhash.c vendor/zstd/common/zstd_common.c \
                vendor/zstd/decompress/huf_decompress.c vendor/zstd/decompress/zstd_ddict.c \
                vendor/zstd/decompress/zstd_decompress.c vendor/zstd/decompress/zstd_decompress_block.c
SOURCES := $(shell find src -name '*.c' ! -path 'src/testing/*' | LC_ALL=C sort) vendor/yyjson/yyjson.c $(ZSTD_SOURCES) $(BUILD)/gen/assets.c
UNIT_SUPPORT := src/testing/hooks.c src/testing/cache_faults.c src/testing/codec_roundtrip.c src/testing/phase_times.c
UNIT_SOURCES := $(filter-out src/main.c,$(SOURCES)) $(wildcard tests/unit/*.c) $(UNIT_SUPPORT)
RELEASE_OBJECTS := $(patsubst %.c,$(BUILD)/release/%.o,$(SOURCES))
UNIT_OBJECTS := $(patsubst %.c,$(BUILD)/unit/%.o,$(UNIT_SOURCES))
ASSET_INPUTS := assets/page_template.html assets/font.css assets/page.css assets/page.js \
                assets/OFL.txt assets/curated_bundled.json assets/curated_price_history.json \
                assets/pricing_numeric_ranges.txt assets/pricing_extend_ranges.txt \
                assets/pricing_prepend_ranges.txt assets/MANIFEST
REAL_HOME := $(HOME)
export PYTHONDONTWRITEBYTECODE := 1
export PLAYWRIGHT_BROWSERS_PATH := $(REAL_HOME)/Library/Caches/ms-playwright
export COLOPHON_BIN := $(CURDIR)/$(RELEASE_BIN)
PYTEST_ARGS ?=

.PHONY: all test-unit test-cli test-browser test sanitize tsan check-assets check-sort clean
all: $(RELEASE_BIN)

$(BUILD)/gen/assets.c: tools/embed.pl $(ASSET_INPUTS) src/gen/assets.h
	perl tools/embed.pl $@
$(RELEASE_BIN): $(RELEASE_OBJECTS)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(LDFLAGS) $^ $(LDLIBS) -o $@
$(BUILD)/unit-tests: $(UNIT_OBJECTS)
	$(CC) $(CFLAGS) $(LDFLAGS) $^ $(LDLIBS) -o $@
$(BUILD)/release/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@
$(BUILD)/unit/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) -Itests/unit $(CFLAGS) -DCOLOPHON_TESTING -MMD -MP -c $< -o $@

# Upstream libzstd.mk namespaces xxhash; assembly and legacy formats stay off.
ZSTD_CPPFLAGS := -DXXH_NAMESPACE=ZSTD_ -DZSTD_DISABLE_ASM=1 -DZSTD_LEGACY_SUPPORT=0
$(BUILD)/release/vendor/zstd/%.o $(BUILD)/unit/vendor/zstd/%.o: override CPPFLAGS += $(ZSTD_CPPFLAGS)

test-unit: $(BUILD)/unit-tests
	@tests/run-unit.sh "$(REAL_HOME)" "$(CURDIR)/$(BUILD)/unit-tests"
test-cli: all
	@tests/run-pytest.sh "$(REAL_HOME)" tests/test_cli.py $(PYTEST_ARGS)
test-browser: all
	@tests/run-pytest.sh "$(REAL_HOME)" tests/test_browser.py $(PYTEST_ARGS)
test: check-sort check-assets test-unit test-cli test-browser
sanitize:
	ASAN_OPTIONS=halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 $(MAKE) BUILD=build/sanitize RELEASE_BIN=build/sanitize/colophon OPTFLAGS=-O1 CFLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' LDFLAGS='-fsanitize=address,undefined' test
# TSan covers all retained C units, including their concurrency assertions.
tsan:
	TSAN_OPTIONS=halt_on_error=1 $(MAKE) BUILD=build/tsan RELEASE_BIN=build/tsan/colophon OPTFLAGS=-O1 CFLAGS='-fsanitize=thread -fno-omit-frame-pointer' LDFLAGS='-fsanitize=thread' test-unit
check-assets:
	@perl tools/check_assets.pl
check-sort:
	@rg -n '\bqsort\b' src; sort_status=$$?; \
	case $$sort_status in \
	0) echo 'unstable sort is forbidden in src' >&2; exit 1 ;; \
	1) exit 0 ;; \
	*) echo "stable-sort search failed (status $$sort_status)" >&2; exit "$$sort_status" ;; \
	esac
clean:
	@if test -e build; then rm -r -- build; fi
	@if test -e colophon; then rm -- colophon; fi
-include $(RELEASE_OBJECTS:.o=.d) $(UNIT_OBJECTS:.o=.d)
