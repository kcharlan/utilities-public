#define _DARWIN_C_SOURCE
#include "reader.h"
#include "classify.h"
#include "util/sha256.h"
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static Err object_read(Str bytes, JsonRead *out) {
    *out = json_read(bytes, BYTES, JSON_CONSTANTS_ALLOW, "log.line");
    if (out->status == JSON_NOMEM) return err_make(ERR_NOMEM, "log JSON allocation failed");
    return ERR_SUCCESS;
}
Err reader_observe_line(const ReaderRawLine *line, void *context,
    Err (*observer)(void *, const ReaderRawLine *, const JsonRead *)) {
    JsonRead json = {0};
    Err err = object_read(line->bytes,&json);
    if (!err.code) err = observer(context,line,&json);
    json_read_free(&json);
    return err;
}

static Err decode(Str bytes, bool terminated, const ReaderCallbacks *callbacks,
                  const ReaderRawLine *raw, DecodedLine *out) {
    *out = (DecodedLine){.status = terminated ? LINE_MALFORMED : LINE_PARTIAL};
    if (terminated) {
        size_t i = 0;
        while (i < bytes.n && strchr(" \t\n\r\v\f", (unsigned char)bytes.p[i]) && bytes.p[i]) i++;
        if (i == bytes.n) {
            out->status = LINE_BLANK;
            return callbacks && callbacks->decoded_line ?
                callbacks->decoded_line(callbacks->context, raw, &out->json) : ERR_SUCCESS;
        }
    }
    Err err = object_read(bytes, &out->json);
    if (err.code) return err;
    if (callbacks && callbacks->decoded_line) {
        err = callbacks->decoded_line(callbacks->context, raw, &out->json);
        if (err.code) return err;
    }
    if (out->json.doc && yyjson_is_obj(yyjson_doc_get_root(out->json.doc))) {
        out->status = LINE_OK; return ERR_SUCCESS;
    }
    json_read_free(&out->json);
    if (!terminated) return ERR_SUCCESS;
    const char *markers[] = {"{\"timestamp\"", "{\"type\""};
    size_t start = 1;
    while (start < bytes.n) {
        const char *candidate = NULL;
        for (size_t i = 0; i < 2; i++) {
            const char *found = memmem(bytes.p + start, bytes.n - start, markers[i], strlen(markers[i]));
            if (found && (!candidate || found < candidate)) candidate = found;
        }
        if (!candidate) break;
        size_t offset = (size_t)(candidate - bytes.p);
        err = object_read((Str){candidate, bytes.n - (uint32_t)offset}, &out->json);
        if (err.code) return err;
        if (out->json.doc && yyjson_is_obj(yyjson_doc_get_root(out->json.doc))) {
            out->status = LINE_RECOVERED; return ERR_SUCCESS;
        }
        json_read_free(&out->json);
        start = offset + 1;
    }
    return ERR_SUCCESS;
}

Err reader_decode(Str bytes, bool terminated, DecodedLine *out) {
    return decode(bytes, terminated, NULL, NULL, out);
}

static Err consume_line(Str bytes, bool terminated, const ReaderCallbacks *callbacks, ReaderResult *out) {
    ReaderRawLine raw = {out->physical_lines++, bytes, terminated};
    Err err = ERR_SUCCESS;
    if (callbacks && callbacks->raw_line) {
        err = callbacks->raw_line(callbacks->context, &raw);
        if (err.code) return err;
    }
    DecodedLine decoded;
    err = decode(bytes, terminated, callbacks, &raw, &decoded);
    Str key = {0};
    if (err.code) goto done;
    if (decoded.status == LINE_MALFORMED) out->malformed++;
    if (decoded.status == LINE_RECOVERED) out->recovered++;
    if (decoded.status == LINE_PARTIAL) out->partial_final_line = true;
    if (!decoded.json.doc) goto done;
    yyjson_val *record = yyjson_doc_get_root(decoded.json.doc);
    err = record_type_key(record, &key);
    if (err.code) goto done;
    if (!record_type_known(key)) {
        uint64_t *count = omap_get(&out->unknown_types, key);
        if (!count) {
            count = calloc(1, sizeof *count);
            if (!count) { err = err_make(ERR_NOMEM, "unknown type count allocation failed"); goto done; }
            err = omap_put(&out->unknown_types, key, count);
            if (err.code) { free(count); goto done; }
        }
        (*count)++;
    }
    yyjson_val *payload = obj_get_last(record, STR_LIT("payload"));
    ReaderRecord fact = {raw.index, out->decoded_records++, terminated,
        decoded.status == LINE_RECOVERED, record, yyjson_is_obj(payload) ? payload : NULL, key};
    if (callbacks && callbacks->record) err = callbacks->record(callbacks->context, &fact);
done:
    free((void *)key.p);
    json_read_free(&decoded.json);
    return err;
}

static ssize_t read_at(int fd, void *buffer, size_t size, int64_t offset) {
    ssize_t count;
    do { count = pread(fd, buffer, size, (off_t)offset); } while (count < 0 && errno == EINTR);
    return count;
}

Err reader_fingerprint(int fd, int64_t size, char output[65]) {
    char text[256];
    if (size < 0) return err_make(ERR_INVALID, "negative snapshot size");
    int64_t tail_start = size > 4096 ? size - 4096 : 0;
    unsigned char tail[4096];
    ssize_t count = read_at(fd, tail, (size_t)(size - tail_start), tail_start);
    if (count < 0) return err_make(ERR_IO, "log fingerprint read failed: %s", err_system(errno,text));
    sha256_hex(tail, (size_t)count, output);
    return ERR_SUCCESS;
}
Err reader_read_fd(int fd, const DiscoveredLog *snapshot, const ReaderCallbacks *callbacks, ReaderResult *out) {
    char text[256];
    Err fingerprint = reader_fingerprint(fd, snapshot->size, out->tail_sha256);
    if (fingerprint.code) return fingerprint;
    ssize_t count;
    const size_t chunk_size = 1024 * 1024;
    char *chunk = malloc(chunk_size), *line = NULL;
    size_t length = 0, capacity = 0;
    Err err = ERR_SUCCESS;
    if (!chunk) return err_make(ERR_NOMEM, "log read buffer allocation failed");
    int64_t offset = 0;
    while (offset < snapshot->size) {
        if (callbacks && callbacks->chunk) {
            err = callbacks->chunk(callbacks->context);
            if (err.code) break;
        }
        size_t request = snapshot->size - offset > (int64_t)chunk_size ? chunk_size : (size_t)(snapshot->size - offset);
        count = read_at(fd, chunk, request, offset);
        if (count < 0) { err = err_make(ERR_IO, "log stream read failed: %s", err_system(errno,text)); break; }
        if (!count) break;
        offset += count;
        size_t start = 0;
        while (start < (size_t)count) {
            const char *end = memchr(chunk + start, '\n', (size_t)count - start);
            size_t piece = end ? (size_t)(end - chunk) - start : (size_t)count - start;
            if (piece > UINT32_MAX - length) { err = err_make(ERR_INVALID, "log line exceeds string capacity"); break; }
            if (length + piece > capacity) {
                size_t grown = capacity ? capacity : chunk_size;
                while (grown < length + piece) grown *= 2;
                char *next = realloc(line, grown);
                if (!next) { err = err_make(ERR_NOMEM, "log line allocation failed"); break; }
                line = next; capacity = grown;
            }
            if (piece) memcpy(line + length, chunk + start, piece);
            length += piece;
            if (end) {
                err = consume_line((Str){line ? line : "", (uint32_t)length}, true, callbacks, out);
                length = 0;
                if (err.code) break;
            }
            start += piece + (end != NULL);
        }
        if (err.code) break;
    }
    if (!err.code && length) err = consume_line((Str){line, (uint32_t)length}, false, callbacks, out);
    free(line); free(chunk);
    return err;
}

Err reader_read_log(const DiscoveredLog *snapshot, const ReaderCallbacks *callbacks, ReaderResult *out) {
    char text[256];
    if (!snapshot->path.p || memchr(snapshot->path.p, 0, snapshot->path.n)) return err_make(ERR_INVALID, "invalid log path");
    /* DiscoveredLog paths are NUL-terminated interned spellings. */
    int fd = open(snapshot->path.p, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return err_make(ERR_IO, "log open failed: %s", err_system(errno,text));
    Err err = reader_read_fd(fd, snapshot, callbacks, out);
    if (close(fd) < 0 && !err.code) err = err_make(ERR_IO, "log close failed: %s", err_system(errno,text));
    return err;
}

void reader_result_destroy(ReaderResult *result) {
    for (OmapEntry *entry = result->unknown_types.first; entry; entry = entry->next) free(entry->value);
    omap_destroy(&result->unknown_types);
    *result = (ReaderResult){0};
}
