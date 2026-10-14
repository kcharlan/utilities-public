#include "runner.h"
#include "scan/resource.h"
#include <stdint.h>
typedef struct {
    uintptr_t created, value, error, released[3];
    bool copy_ok, fail_boolean;
    size_t calls, releases;
} FakeResources;
static void *create(void *context, const char *path) {
    FakeResources *f = context; f->calls++;
    ASSERT_STREQ("/synthetic/ordinary.app", path);
    return (void *)f->created;
}
static bool copy(void *context, void *url, const void *key, void **value, void **error) {
    FakeResources *f = context; f->calls++;
    ASSERT_EQ(f->created, (uintptr_t)url); ASSERT_EQ(99, (uintptr_t)key);
    *value = (void *)f->value; *error = (void *)f->error;
    return f->copy_ok;
}
static Err boolean(void *context, void *value, bool *result) {
    FakeResources *f = context; f->calls++;
    ASSERT_EQ(f->value, (uintptr_t)value);
    if (f->fail_boolean) return err_make(ERR_INVALID, "synthetic native failure");
    *result = true; return ERR_SUCCESS;
}
static void release(void *context, void *object) {
    FakeResources *f = context;
    ASSERT_TRUE(f->releases < 3);
    f->released[f->releases++] = (uintptr_t)object;
}
static ResourceOps operations(FakeResources *f) {
    return (ResourceOps){f, create, copy, boolean, release};
}
TEST(resource_non_darwin_has_no_owned_resources) {
    FakeResources f = {.created = 11, .value = 12, .copy_ok = true};
    ResourceOps ops = operations(&f); bool result = true;
    ASSERT_EQ(ERR_OK, test_resource_property(false, "/synthetic/ordinary.app",
                                            (void *)99, &ops, &result).code);
    ASSERT_FALSE(result); ASSERT_EQ(0, f.calls); ASSERT_EQ(0, f.releases);
}
TEST(resource_property_releases_all_references_in_source_order) {
    FakeResources cases[] = {
        {.created=11,.value=12,.copy_ok=true},
        {.created=11,.error=13},
        {.created=11,.copy_ok=true},
        {0},
        {.created=11,.value=12,.error=13,.copy_ok=true,.fail_boolean=true},
    };
    for (size_t i = 0; i < 5; i++) {
        FakeResources *f = &cases[i]; ResourceOps ops = operations(f); bool result = false;
        Err e = test_resource_property(true,"/synthetic/ordinary.app",(void *)99,&ops,&result);
        ASSERT_EQ(i == 4 ? ERR_INVALID : ERR_OK, e.code);
        if (i == 4) ASSERT_STREQ("synthetic native failure",e.message);
        else ASSERT_EQ(i == 0, result);
        size_t n = 0;
        if (f->created) {
            if (f->value) ASSERT_EQ(f->value, f->released[n++]);
            if (f->error) ASSERT_EQ(f->error, f->released[n++]);
            ASSERT_EQ(f->created, f->released[n++]);
        }
        ASSERT_EQ(n,f->releases);
    }
}
