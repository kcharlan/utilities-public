import pytest
from helpers import NativeRun

@pytest.fixture
def native(tmp_path):
    return NativeRun(tmp_path)

@pytest.fixture
def native_page(native):
    native.session()
    result = native.build()
    assert result.returncode == 0, result.stderr
    return native.page
