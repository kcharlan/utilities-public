from __future__ import annotations

from pathlib import Path


FIXTURES = {
    "pack_manifest_minimal.yaml": {
        "provenance": "# Curated from docs/cognitive_switchyard_design.md sections 4.1-4.2.",
        "markers": ("name:", "phases:", "execution:"),
    },
    "plan_reference_minimal.plan.md": {
        "provenance": "<!-- Curated from reference/work/execution/done/001_clean_acr_loop.plan.md -->",
        "markers": ("PLAN_ID:", "# Plan:", "## Testing"),
    },
    "status_reference_minimal.status": {
        "provenance": "# Curated from reference/work/execution/done/001_clean_acr_loop.status",
        "markers": ("STATUS:", "TEST_RESULT:", "NOTES:"),
    },
    "resolution_reference_minimal.md": {
        "provenance": "<!-- Curated from reference/work/execution/RESOLUTION.md -->",
        "markers": ("# Dependency Resolution Report", "## Constraints", "## Parallel Opportunities"),
    },
}


def test_curated_packet_zero_fixtures_exist_and_are_readable(repo_root: Path) -> None:
    fixtures_dir = repo_root / "tests" / "fixtures"

    assert fixtures_dir.is_dir()

    for fixture_name, fixture_requirements in FIXTURES.items():
        fixture_path = fixtures_dir / fixture_name

        assert fixture_path.is_file(), f"missing fixture: {fixture_name}"
        contents = fixture_path.read_text(encoding="utf-8")
        assert contents.strip(), f"empty fixture: {fixture_name}"
        assert contents.splitlines()[0] == fixture_requirements["provenance"]
        for marker in fixture_requirements["markers"]:
            assert marker in contents, f"fixture {fixture_name} missing marker {marker!r}"
