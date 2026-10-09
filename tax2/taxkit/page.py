"""Normalize all rule years and assemble an offline page without runtime metadata."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path

from .config import load_config, normalize_qif_overrides
from .rules_loader import load_rules
from .utils import discover_year_files

ASSET_ROOT = Path(__file__).resolve().parents[1] / "web"


def _inventory(directory: Path) -> dict[str, dict]:
    """Validate every numeric-year source before applying the existing YAML preference."""
    validated = {}
    for year, paths in discover_year_files(directory).items():
        for path in paths:
            if not path.is_file():
                raise ValueError(f"Invalid rules file {path}: expected a regular file")
            model = load_rules(str(path)).model_dump(mode="json")
            if year not in validated or path.suffix == ".yaml":
                validated[year] = model
    return {str(year): validated[year] for year in sorted(validated)}


def build_payload(rules_root: Path, *, rules_source: str, built_at: str | None = None) -> dict:
    if rules_source not in ("bundled", "custom"):
        raise ValueError("rules_source must be bundled or custom")
    federal = _inventory(rules_root / "federal")
    if not federal:
        raise ValueError(f"No federal rules in {rules_root / 'federal'}")
    states = []
    state_root = rules_root / "states"
    if state_root.is_dir():
        for directory in sorted(state_root.iterdir(), key=lambda path: path.name.upper()):
            if not directory.is_dir():
                continue
            rules = _inventory(directory)
            years = sorted(map(int, rules))
            latest = rules[str(years[-1])] if years else {}
            code = directory.name.upper()
            states.append({"code": code, "display_name": latest.get("display_name") or directory.name,
                           "years": years, "qif": latest.get("qif"), "rules": rules})
    if not any(state["years"] for state in states):
        raise ValueError(f"No valid state rules in {state_root}")
    cfg = load_config()
    return {"schema": 1, "app": {"name": "Tax2", "version": "3.0"},
            "built_at": built_at if built_at is not None else datetime.now(timezone.utc).isoformat(),
            "rules_source": rules_source, "federal": federal, "states": states,
            "config": {"default_states": cfg["default_states"],
                       "qif_overrides": normalize_qif_overrides(cfg["qif_overrides"])}}


def render_page(payload: dict) -> bytes:
    sources = {}
    names = ("styles.css", "vendor/preact.umd.js", "vendor/hooks.umd.js", "vendor/htm.umd.js",
             "engine.js", "app.js", "vendor/preact.LICENSE", "vendor/htm.LICENSE")
    for name in names:
        source = (ASSET_ROOT / name).read_text(encoding="utf-8")
        if "</script" in source.lower():
            raise ValueError(f"Unsafe inline asset: {name}")
        sources[name] = source
    scripts = "\n".join(f"<script>{sources[name]}</script>" for name in names[1:6])
    licenses = "\n".join(escape(sources[name]) for name in names[6:])
    page = (ASSET_ROOT / "template.html").read_text(encoding="utf-8")
    for token, value in (("{{CSS}}", sources["styles.css"]), ("{{SCRIPTS}}", scripts), ("{{LICENSES}}", licenses)):
        page = page.replace(token, value)
    data = json.dumps(payload, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    return page.replace("{{PAYLOAD}}", data).encode("utf-8")
