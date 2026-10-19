r"""Summarize a lab run, or compare two runs, with the corpus v1 label overlay.

Usage:
  uv run python -m evallab.summarize runs/pilot-q4-off.jsonl
  uv run python -m evallab.summarize runs/a.jsonl --compare runs/b.jsonl
  uv run python -m evallab.summarize runs/a.jsonl --compare ~/ai/projects/agentic-soc-triage/results/qwen2.5-14b.json
  uv run python -m evallab.summarize runs/a.jsonl --rerun runs/a-rerun-infra.jsonl

Accuracy is the capability view: the denominator is every selected alert and
every error counts as wrong. A row is correct only when its stored outcome is
"correct". False closes are the safety view: only ok rows count, because an
error never auto-closes an alert.

Errors are classified from the row's own attempt log:
  infra    last attempt timed out or hit an API error
  model    output hit the token limit, came back empty, or stayed invalid after repair
  harness  failure outside the model call

--rerun takes a run of the same configuration and replaces only rows that were
infrastructure errors. The original result stays primary; the adjusted figures
print separately with the replaced alert IDs. A rerun that contains any other
alert, or differs in configuration, is refused.

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

from evallab.run import IDENTITY_KEYS

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERLAY = REPO_ROOT / "docs" / "label-review-v1.json"
INFRA_STATUSES = frozenset({"timeout", "api_error"})


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


def error_class(row: dict) -> str | None:
    status = row.get("status")
    if status == "ok":
        return None
    if status == "harness_error":
        return "harness"
    attempts = row.get("attempt_log") or []
    last = attempts[-1].get("status") if attempts else None
    return "infra" if last in INFRA_STATUSES else "model"


def load_run(path: str) -> tuple[dict, list[dict]]:
    p = Path(path).expanduser()
    if p.suffix == ".jsonl":
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        header = next((r for r in rows if r.get("type") == "header"), {})
        latest = {r["alert_id"]: r for r in rows if r.get("type") == "alert"}
        endpoint = header.get("endpoint", {})
        meta = {"label": header.get("run_label", p.stem), "model": endpoint.get("model"),
                "reasoning": endpoint.get("reasoning"), "fingerprint": header.get("corpus_fingerprint", ""),
                "source": "lab", "identity": {k: header.get(k) for k in IDENTITY_KEYS}}
        return meta, list(latest.values())
    data = json.loads(p.read_text(encoding="utf-8"))
    meta = {"label": data.get("run_label", p.stem), "model": data.get("model_name"), "reasoning": None,
            "fingerprint": data.get("corpus_fingerprint", ""), "source": "soc_triage", "identity": None}
    return meta, [{**s, "status": "ok"} for s in data["scores"]]


def apply_rerun(meta: dict, rows: list[dict], rerun_path: str) -> tuple[list[dict], list[str]]:
    r_meta, r_rows = load_run(rerun_path)
    if meta["source"] != "lab" or r_meta["source"] != "lab":
        raise SystemExit("Reruns apply to lab runs only.")
    if r_meta["identity"] != meta["identity"]:
        diff = [k for k in IDENTITY_KEYS if r_meta["identity"].get(k) != meta["identity"].get(k)]
        raise SystemExit(f"Rerun {r_meta['label']} differs from {meta['label']} in {diff}.")
    infra_ids = {r["alert_id"] for r in rows if error_class(r) == "infra"}
    rerun = {r["alert_id"]: r for r in r_rows}
    extra = sorted(set(rerun) - infra_ids)
    if extra:
        raise SystemExit(f"Rerun contains alerts that were not infrastructure errors in {meta['label']}: {extra}")
    merged = [rerun.get(r["alert_id"], r) for r in rows]
    return merged, sorted(rerun)


def load_overlay(path: str) -> tuple[str, set[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["corpus_fingerprint"], {d["alert_id"] for d in data["decisions"] if d["decision"] == "contested"}


def is_correct(row: dict) -> bool:
    return row.get("status") == "ok" and row.get("outcome") == "correct"


def outcome_key(row: dict) -> str:
    cls = error_class(row)
    return f"{cls}_error" if cls else row.get("outcome")


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
    classes = Counter(error_class(r) for r in rows if r.get("status") != "ok")
    errors = f"errors {sum(classes.values())}"
    if classes:
        errors += " (" + ", ".join(f"{c} {v}" for c, v in sorted(classes.items())) + ")"
    return (f"  {name:12} acc {k:3}/{n:3} = {acc:6.1%} [{lo:5.1%}, {hi:5.1%}]   "
            f"FPR {fp:2}/{len(closes):2} = {fpr:5.1%} [{flo:5.1%}, {fhi:5.1%}]   "
            f"false_close {fc}   {errors}")


def report(meta: dict, rows: list[dict], contested: set[str]) -> None:
    print(f"run {meta['label']} | model {meta['model']} | reasoning {meta['reasoning']} | "
          f"source {meta['source']} | corpus {meta['fingerprint']}")
    print(block_line("full", rows))
    if contested:
        print(block_line("uncontested", [r for r in rows if r["alert_id"] not in contested]))
    print("  outcomes:", dict(Counter(outcome_key(r) for r in rows)))

    if meta["source"] == "lab":
        ok = [r for r in rows if r.get("status") == "ok"]
        lat = sorted(r["model_latency_s"] for r in ok if r.get("model_latency_s") is not None)
        tok = [r["completion_tokens"] for r in ok if r.get("completion_tokens") is not None]
        if lat:
            p95 = statistics.quantiles(lat, n=20)[18] if len(lat) >= 2 else lat[0]
            print(f"  latency s: median {statistics.median(lat):.1f}  p95 {p95:.1f}  | completion tokens: "
                  f"median {statistics.median(tok):.0f}  total {sum(tok)}  | repairs {sum(bool(r.get('repair_used')) for r in rows)}")
        errored = [r for r in rows if r.get("status") != "ok"]
        if errored:
            print("  errors:")
            for r in sorted(errored, key=lambda r: r["alert_id"]):
                print(f"    {r['alert_id']} {error_class(r):7} {(r.get('error') or '')[:90]}")

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
    p.add_argument("--rerun", help="Same-configuration run covering only this run's infrastructure errors")
    p.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    args = p.parse_args(argv)

    overlay_fp, contested_all = load_overlay(args.overlay)
    meta, rows = load_run(args.run)
    contested = contested_all if meta["fingerprint"] == overlay_fp else set()
    if not contested:
        print(f"overlay not applied: run corpus {meta['fingerprint']!r} != overlay corpus {overlay_fp!r}")
    report(meta, rows, contested)

    if args.rerun:
        merged, replaced = apply_rerun(meta, rows, args.rerun)
        print(f"\ninfra-adjusted with {Path(args.rerun).stem}: replaced {', '.join(replaced) or 'none'}")
        print(block_line("full", merged))
        if contested:
            print(block_line("uncontested", [r for r in merged if r["alert_id"] not in contested]))

    if args.compare:
        b_meta, b_rows = load_run(args.compare)
        if b_meta["fingerprint"] != meta["fingerprint"]:
            raise SystemExit(f"Refusing to compare runs on different corpora: {meta['fingerprint']} vs {b_meta['fingerprint']}")
        compare(meta, rows, b_meta, b_rows, contested)


if __name__ == "__main__":
    main()
