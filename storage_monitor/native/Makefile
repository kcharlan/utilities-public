CC ?= clang
BUILD_DIR ?= build
# Required flags survive the installer's explicit CFLAGS= override.
override CFLAGS += -std=c17 -O2 -Wall -Wextra -Werror -D_DARWIN_C_SOURCE -pthread
SOURCE = src/storage_monitor_walk.c

.PHONY: all sanitize tsan clean
all: $(BUILD_DIR)/storage_monitor_walk
sanitize: $(BUILD_DIR)/sanitize/storage_monitor_walk
tsan: $(BUILD_DIR)/tsan/storage_monitor_walk

$(BUILD_DIR)/storage_monitor_walk: $(SOURCE) Makefile
	mkdir -p "$(@D)"
	$(CC) $(CPPFLAGS) $(CFLAGS) $(SOURCE) $(LDFLAGS) -o "$@"

$(BUILD_DIR)/sanitize/storage_monitor_walk: $(SOURCE) Makefile
	mkdir -p "$(@D)"
	$(CC) $(CPPFLAGS) $(CFLAGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(SOURCE) $(LDFLAGS) -o "$@"

$(BUILD_DIR)/tsan/storage_monitor_walk: $(SOURCE) Makefile
	mkdir -p "$(@D)"
	$(CC) $(CPPFLAGS) $(CFLAGS) -O1 -g -fsanitize=thread $(SOURCE) $(LDFLAGS) -o "$@"

clean:
	rm -rf -- "$(BUILD_DIR)"
