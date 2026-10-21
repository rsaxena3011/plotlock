"""Load the baked-in demo fixture bundles (offline, reproducible)."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_NAMES = ["plot-1-clean", "plot-2-burned", "plot-3-cloudy", "plot-4-duplicate"]


def load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"unknown fixture: {name}")
    return json.loads(path.read_text())


def list_fixtures() -> list[dict]:
    out = []
    for name in FIXTURE_NAMES:
        data = load_fixture(name)
        out.append({
            "bundle_id": data["bundle_id"],
            "label": data["plot"]["label"],
            "expected_verdict": data.get("expected_verdict"),
            "expected_registration": data.get("expected_registration"),
        })
    return out
