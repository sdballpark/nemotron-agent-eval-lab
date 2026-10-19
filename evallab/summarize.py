r"""Summarize a lab run, or compare two runs, with the corpus v1 label overlay.

Usage:
  uv run python -m evallab.summarize runs/pilot-q4-off.jsonl
  uv run python -m evallab.summarize runs/a.jsonl --compare runs/b.jsonl
  uv run python -m evallab.summarize runs/a.jsonl --compare ~/ai/projects/agentic-soc-triage/results/qwen2.5-14b.json

Accuracy is the capability view: the denominator is every selected alert and
model or harness errors count as wrong. A row is correct only when its stored
outcome is "correct". False closes are the safety view: only ok rows count,
because an error never auto-closes an alert.

The overlay applies only when the run's corpus fingerprint matches the
overlay's, so a v2 run never picks up v1 review decisions.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERLAY = REPO_ROOT / "docs" / "label-review-v1.json"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pair counts."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load_run(path: str) -> tuple[dict, list[dict]]:
    p = Path(path).expanduser()
    if p.suffix == ".jsonl":
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        header = next((r for r in rows if r.get("type") == "header"), {})
        latest = {r["alert_id"]: r for r in rows if r.get("type") == "alert"}
        endpoint = header.get("endpoint", {})
        meta = {"label": header.get("run_label", p.stem), "model": endpoint.get("model"),
                "reasoning": endpoint.get("reasoning"), "fingerprint": header.get("corpus_fingerprint", ""),
                "source": "lab"}
        return meta, list(latest.values())
    data = json.loads(p.read_text(encoding="utf-8"))
    meta = {"label": data.get("run_label", p.stem), "model": data.get("model_name"), "reasoning": None,
            "fingerprint": data.get("corpus_fingerprint", ""), "source": "soc_triage"}
    return meta, [{**s, "status": "ok"} for s in data["scores"]]


def load_overlay(path: str) -> tuple[str, set[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["corpus_fingerprint"], {d["alert_id"] for d in data["decisions"] if d["decision"] == "contested"}


def is_correct(row: dict) -> bool:
    return row.get("status") == "ok" and row.get("outcome") == "correct"


def block_line(name: str, rows: list[dict]) -> str:
    n = len(rows)
    ok = [r for r in rows if r.get("status") == "ok"]
    k = sum(is_correct(r) for r in rows)
    lo, hi = wilson(k, n)
    closes = [r for r in ok if r["expected"] == "close_benign"]
    fp = sum(r["outcome"] == "false_positive" for r in closes)
    fc = sum(r["outcome"] == "false_close" for r in ok)
    flo, fhi = wilson(fp, len(closes))
    acc = k / n if n else math.nan
    fpr = fp / len(closes) if closes else math.nan
    return (f"  {name:12} acc {k:3}/{n:3} = {acc:6.1%} [{lo:5.1%}, {hi:5.1%}]   "
            f"FPR {fp:2}/{len(closes):2} = {fpr:5.1%} [{flo:5.1%}, {fhi:5.1%}]   "
            f"false_close {fc}   errors {n - len(ok)}")


def report(meta: dict, rows: list[dict], contested: set[str]) -> None:
    print(f"run {meta['label']} | model {meta['model']} | reasoning {meta['reasoning']} | "
          f"source {meta['source']} | corpus {meta['fingerprint']}")
    print(block_line("full", rows))
    if contested:
        print(block_line("uncontested", [r for r in rows if r["alert_id"] not in contested]))
    print("  outcomes:", dict(Counter(r.get("outcome") or r.get("status") for r in rows)))

    if meta["source"] == "lab":
        ok = [r for r in rows if r.get("status") == "ok"]
        lat = sorted(r["model_latency_s"] for r in ok if r.get("model_latency_s") is not None)
        tok = [r["completion_tokens"] for r in ok if r.get("completion_tokens") is not None]
        if lat:
            p95 = statistics.quantiles(lat, n=20)[18] if len(lat) >= 2 else lat[0]
            print(f"  latency s: median {statistics.median(lat):.1f}  p95 {p95:.1f}  | completion tokens: "
                  f"median {statistics.median(tok):.0f}  total {sum(tok)}  | repairs {sum(bool(r.get('repair_used')) for r in rows)}")

    adversarial = [r for r in rows if r.get("corpus_slice") == "adversarial"]
    if adversarial:
        print("  adversarial:")
        for r in sorted(adversarial, key=lambda r: r["alert_id"]):
            mark = " contested" if r["alert_id"] in contested else ""
            print(f"    {r['alert_id']} expected={r['expected']:12} predicted={r.get('predicted')!s:12} "
                  f"obeyed={r.get('obeyed_injection')!s:5} flagged={r.get('flagged_injection')!s:5}{mark}")


def compare(a_meta: dict, a_rows: list[dict], b_meta: dict, b_rows: list[dict], contested: set[str]) -> None:
    a = {r["alert_id"]: r for r in a_rows}
    b = {r["alert_id"]: r for r in b_rows}
    shared = sorted(set(a) & set(b))
    print(f"\ncompare A={a_meta['label']} vs B={b_meta['label']} on {len(shared)} shared alerts")
    for name, ids in (("full", shared), ("uncontested", [i for i in shared if i not in contested])):
        if not ids:
            continue
        a_k = sum(is_correct(a[i]) for i in ids)
        b_k = sum(is_correct(b[i]) for i in ids)
        only_a = [i for i in ids if is_correct(a[i]) and not is_correct(b[i])]
        only_b = [i for i in ids if is_correct(b[i]) and not is_correct(a[i])]
        print(f"  {name:12} A {a_k}/{len(ids)}  B {b_k}/{len(ids)}  A-only correct {len(only_a)}  "
              f"B-only correct {len(only_b)}  McNemar exact p={mcnemar_exact(len(only_a), len(only_b)):.3f}")
        if only_a:
            print(f"    A-only: {', '.join(only_a)}")
        if only_b:
            print(f"    B-only: {', '.join(only_b)}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.add_argument("--compare")
    p.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    args = p.parse_args(argv)

    overlay_fp, contested_all = load_overlay(args.overlay)
    meta, rows = load_run(args.run)
    contested = contested_all if meta["fingerprint"] == overlay_fp else set()
    if not contested:
        print(f"overlay not applied: run corpus {meta['fingerprint']!r} != overlay corpus {overlay_fp!r}")
    report(meta, rows, contested)

    if args.compare:
        b_meta, b_rows = load_run(args.compare)
        if b_meta["fingerprint"] != meta["fingerprint"]:
            raise SystemExit(f"Refusing to compare runs on different corpora: {meta['fingerprint']} vs {b_meta['fingerprint']}")
        compare(meta, rows, b_meta, b_rows, contested)


if __name__ == "__main__":
    main()
