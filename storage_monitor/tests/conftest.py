import os
from pathlib import Path
import subprocess
import pytest


@pytest.fixture(scope="session")
def walker_binary(tmp_path_factory):
    configured = os.environ.get("STORAGE_MONITOR_WALKER")
    if configured:
        binary = Path(configured)
        assert binary.is_file() and os.access(binary, os.X_OK), "invalid STORAGE_MONITOR_WALKER"
        return binary
    build = tmp_path_factory.mktemp("native-build")
    result = subprocess.run(["make", "-C", str(Path(__file__).resolve().parents[1] / "native"), f"BUILD_DIR={build}", "all"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "storage_monitor_walk"


@pytest.fixture(autouse=True)
def native_walker_environment(monkeypatch, walker_binary):
    monkeypatch.setenv("STORAGE_MONITOR_WALKER", str(walker_binary))


@pytest.fixture(scope="session")
def bulk_fault_library(tmp_path_factory):
    """Inject unavailable attributes/APIs without changing production code."""
    build = tmp_path_factory.mktemp("bulk-fault")
    source = build / "fault.c"
    source.write_text(r'''
#include <sys/attr.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

static int test_bulk(int fd, struct attrlist *attrs, void *buffer, size_t size, uint64_t options) {
    const char *mode = getenv("SMW_TEST_BULK_MODE");
    if (mode && (!strcmp(mode, "unsupported") || !strcmp(mode, "invalid"))) {
        errno = !strcmp(mode, "unsupported") ? ENOTSUP : EINVAL;
        return -1;
    }
    struct attrlist request = *attrs;
    if (mode && !strcmp(mode, "missing")) request.fileattr &= ~ATTR_FILE_DATALENGTH;
    return getattrlistbulk(fd, &request, buffer, size, options);
}
static int test_fstat(int fd, struct stat *st) {
    int result = fstat(fd, st);
    const char *mode = getenv("SMW_TEST_BULK_MODE");
    if (!result && mode && !strcmp(mode, "mount-race") && S_ISDIR(st->st_mode)) st->st_dev++;
    return result;
}
__attribute__((used)) static struct { const void *replacement; const void *original; }
interpose[] __attribute__((section("__DATA,__interpose"))) = {
    {(const void *)test_bulk, (const void *)getattrlistbulk},
    {(const void *)test_fstat, (const void *)fstat}
};
''')
    library = build / "fault.dylib"
    result = subprocess.run(["clang", "-std=c17", "-Wall", "-Wextra", "-Werror", "-D_DARWIN_C_SOURCE", "-dynamiclib", str(source), "-o", str(library)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return library
