from pathlib import Path

import model_sentinel.build_info as build_info


def test_source_checkout_build_info_uses_unambiguous_defaults() -> None:
    assert build_info.format_build_info() == (
        "build=source revision=unpackaged "
        "source_sha256=unpackaged built=unpackaged"
    )


def test_build_info_can_show_short_or_complete_packaged_hash(monkeypatch) -> None:
    source_hash = "a" * 64
    monkeypatch.setattr(build_info, "BUILD_KIND", "standalone")
    monkeypatch.setattr(build_info, "BUILD_REVISION", "0123456789ab")
    monkeypatch.setattr(build_info, "BUILD_SOURCE_HASH", source_hash)
    monkeypatch.setattr(build_info, "BUILD_TIME_UTC", "2026-08-15T12:34:56Z")

    assert build_info.format_build_info() == (
        "build=standalone revision=0123456789ab "
        f"source_sha256={source_hash[:12]} built=2026-08-15T12:34:56Z"
    )
    assert build_info.format_build_info(full_hash=True) == (
        "build=standalone revision=0123456789ab "
        f"source_sha256={source_hash} built=2026-08-15T12:34:56Z"
    )


def test_runtime_entrypoint_resolves_a_synthetic_relative_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert build_info.runtime_entrypoint("./synthetic-model-sentinel") == str(
        (tmp_path / "synthetic-model-sentinel").resolve()
    )


def test_runtime_entrypoint_reports_unknown_for_an_empty_value() -> None:
    assert build_info.runtime_entrypoint("") == "unknown"
