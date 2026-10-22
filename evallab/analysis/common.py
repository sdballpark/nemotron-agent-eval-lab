"""Shared loaders and statistics for the analysis scripts. Reads results/ only."""
from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "results"
OVERLAY = REPO / "docs" / "label-review-v1.json"

MODELS = {
    "gemini": "v1-gemini38flash-on-t1-gaps",
    "qwen14b": "v1-qwen14b-off-t07-gaps",
    "lt-hosted": "v1-lightning-hosted-on-t1-gaps",
    "lt-local": "v1-lightning-q4-on-t1-gaps",
}


def load_group(prefix: str, twins: bool = False) -> list[dict[str, dict]]:
    """One dict per repeat, alert_id -> exported alert row."""
    stem = prefix + ("-twins" if twins else "")
    files = sorted(p for p in (RESULTS / "triage").glob(f"{stem}-r*.json")
                   if re.fullmatch(rf"{re.escape(stem)}-r\d+", p.stem))
    return [{a["alert_id"]: a for a in json.loads(f.read_text(encoding="utf-8"))["alerts"]} for f in files]


def contested_ids() -> set[str]:
    try:
        from evallab.summarize import load_overlay
        return set(load_overlay(str(OVERLAY))[1])
    except Exception:
        data = json.loads(OVERLAY.read_text(encoding="utf-8"))
        rows = data.get("alerts", data) if isinstance(data, dict) else data
        return {r["alert_id"] for r in rows if r.get("decision") == "contested"}


def ok(r: dict) -> bool:
    return r.get("status") == "ok" and r.get("outcome") == "correct"


def count(runs: list[dict], aid: str) -> int:
    return sum(ok(r[aid]) for r in runs)


def majority(runs: list[dict], aid: str) -> bool:
    return count(runs, aid) * 2 > len(runs)


def mcnemar(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n)


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    n, r1, c1 = a + b + c + d, a + b, a + c
    p = lambda x: math.comb(c1, x) * math.comb(n - c1, r1 - x) / math.comb(n, r1)
    obs = p(a)
    return min(1.0, sum(p(x) for x in range(max(0, r1 + c1 - n), min(r1, c1) + 1) if p(x) <= obs * (1 + 1e-9)))


def median_range(values_per_repeat: list[list[float]]) -> tuple[float, float]:
    meds = [statistics.median(v) for v in values_per_repeat if v]
    return min(meds), max(meds)
