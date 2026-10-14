#ifndef CP_READER_H
#define CP_READER_H
#include "scan/discover.h"
#include "util/json_read.h"

typedef enum { LINE_OK, LINE_RECOVERED, LINE_MALFORMED, LINE_BLANK, LINE_PARTIAL } LineStatus;
typedef struct { LineStatus status; JsonRead json; } DecodedLine;
/* Output owns a per-line document; caller calls json_read_free(&out->json).
 * Unterminated input never uses blank suppression or suffix recovery. */
Err reader_decode(Str bytes, bool terminated, DecodedLine *out);

typedef struct { uint64_t index; Str bytes; bool terminated; } ReaderRawLine;
typedef struct {
    uint64_t line, rec;
    bool terminated, recovered;
    yyjson_val *record, *payload;
    Str kind;
} ReaderRecord;
typedef struct {
    void *context;
    Err (*chunk)(void *context); /* Before each borrowed 1 MiB read. */
    Err (*raw_line)(void *context, const ReaderRawLine *line);
    Err (*record)(void *context, const ReaderRecord *record);
    /* Original full-line decode, before object filtering/suffix recovery. The
     * raw bytes, document and status are borrowed only for this call. Scalars
     * and arrays are included; failed originals never expose recovered JSON. */
    Err (*decoded_line)(void *context, const ReaderRawLine *line, const JsonRead *json);
} ReaderCallbacks;
/* Standalone consumers observe the same original decoder, without display
 * recovery. Outcome/document is borrowed; freed before this returns. */
Err reader_observe_line(const ReaderRawLine *line, void *context,
    Err (*observer)(void *, const ReaderRawLine *, const JsonRead *));
typedef struct {
    uint64_t malformed, recovered, physical_lines, decoded_records;
    bool partial_final_line;
    Omap unknown_types; /* owns copied keys and malloc-owned uint64_t values */
    char tail_sha256[65];
} ReaderResult;
/* Zero-initialize result; always destroy it, including after failure. Frozen
 * snapshot values are never refreshed. Opens once, fingerprints before lines,
 * and closes on every path. read_fd borrows fd and never closes/seeks it.
 * Callbacks may be NULL. raw_line runs before display decode for EVERY physical
 * line. record runs only for decoded objects. All callback data is borrowed and
 * expires on return; retain only copied facts, never raw JSON. Both indices start
 * at 0, rec advances only for objects. payload is NULL for nonobject payloads.
 * Callback Err aborts immediately unchanged; IO/allocation failures propagate.
 * On error the result is partial and must not be cached as a successful parse. */
Err reader_read_log(const DiscoveredLog *snapshot, const ReaderCallbacks *callbacks, ReaderResult *out);
Err reader_read_fd(int fd, const DiscoveredLog *snapshot, const ReaderCallbacks *callbacks, ReaderResult *out);
/* Shared frozen-size tail fingerprint. Borrows fd; pread never changes offset. */
Err reader_fingerprint(int fd, int64_t size, char output[65]);
void reader_result_destroy(ReaderResult *result);
#endif
