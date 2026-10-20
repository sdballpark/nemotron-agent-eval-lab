r"""Summarize repeated runs of one configuration.

Usage:
  uv run python -m evallab.repeats runs/v1-lightning-q4-on-t1-r*.jsonl --baseline runs/v1-lightning-q4-on.jsonl

Repeats must share one identity (soc_triage HEAD, corpus, prompt hash, endpoint
configuration, retries) and cover the same alerts. The baseline is a single run
of the same model, typically at other sampling settings, shown for comparison.

Repeats score the same alerts, so they are not independent samples. Mean and
range describe run-to-run variation. The majority-vote line scores each alert
once: correct when it was correct in more than half of the repeats.
"""
from __future__ import annotations

import argparse
import statistics
from collections import Counter

from evallab.summarize import (DEFAULT_OVERLAY, error_class, is_correct, load_overlay, load_run,
                               mcnemar_exact, wilson)


def is_length_error(row: dict) -> bool:
    attempts = row.get("attempt_log") or []
    return error_class(row) == "model" and bool(attempts) and attempts[-1].get("status") == "length"


def correct_counts(runs: list[dict[str, dict]], ids: list[str]) -> dict[str, int]:
    return {i: sum(is_correct(run[i]) for run in runs) for i in ids}


def majority_correct(counts: dict[str, int], n_runs: int) -> dict[str, bool]:
    return {i: k * 2 > n_runs for i, k in counts.items()}


def run_line(label: str, rows: dict[str, dict], contested: set[str]) -> str:
    ids = sorted(rows)
    unc = [i for i in ids if i not in contested]
    ok = [rows[i] for i in ids if rows[i].get("status") == "ok"]
    closes_unc = [rows[i] for i in unc if rows[i].get("status") == "ok" and rows[i]["expected"] == "close_benign"]
    fp_unc = sum(r["outcome"] == "false_positive" for r in closes_unc)
    fc = sum(r["outcome"] == "false_close" for r in ok)
    errs = Counter(error_class(rows[i]) for i in ids if rows[i].get("status") != "ok")
    length = sum(is_length_error(rows[i]) for i in ids)
    tok = [r["completion_tokens"] for r in ok if r.get("completion_tokens") is not None]
    lat = [r["model_latency_s"] for r in ok if r.get("model_latency_s") is not None]
    err_text = ", ".join(f"{c} {v}" for c, v in sorted(errs.items())) or "none"
    tok_med = f"{statistics.median(tok):.0f}" if tok else "n/a"
    lat_med = f"{statistics.median(lat):.1f}s" if lat else "n/a"
    return (f"  {label:34} full {sum(is_correct(rows[i]) for i in ids):3}/{len(ids)}  "
            f"unc {sum(is_correct(rows[i]) for i in unc):2}/{len(unc)}  FPR_unc {fp_unc:2}/{len(closes_unc):2}  "
            f"false_close {fc}  errors: {err_text} (length {length})  tokens_med {tok_med}  latency_med {lat_med}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+")
    p.add_argument("--baseline")
    p.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    args = p.parse_args(argv)

    loaded = [load_run(path) for path in args.runs]
    metas = [m for m, _ in loaded]
    identity = metas[0]["identity"]
    if identity is None or any(m["identity"] != identity for m in metas):
        raise SystemExit("Repeats must be lab runs with identical configuration.")
    runs = [{r["alert_id"]: r for r in rows} for _, rows in loaded]
    ids = sorted(runs[0])
    if any(sorted(run) != ids for run in runs):
        raise SystemExit("Repeats do not cover the same alerts. Finish or resume the incomplete runs first.")

    overlay_fp, contested_all = load_overlay(args.overlay)
    contested = contested_all if metas[0]["fingerprint"] == overlay_fp else set()
    unc = [i for i in ids if i not in contested]
    ep = identity["endpoint"]
    n = len(runs)
    print(f"{n} repeats | model {ep['model']} | reasoning {ep['reasoning']} | temperature {ep.get('temperature')} "
          f"| top_p {ep.get('top_p')} | max_tokens {ep['max_tokens']} | {len(ids)} alerts, {len(unc)} uncontested")
    for meta, run in zip(metas, runs):
        print(run_line(meta["label"], run, contested))

    full = [sum(is_correct(run[i]) for i in ids) for run in runs]
    uncs = [sum(is_correct(run[i]) for i in unc) for run in runs]
    print(f"\n  per-repeat full: mean {statistics.mean(full):.1f}  range {min(full)}-{max(full)}   "
          f"uncontested: mean {statistics.mean(uncs):.1f}  range {min(uncs)}-{max(uncs)}")
    total_fc = sum(r["outcome"] == "false_close" for run in runs for r in run.values() if r.get("status") == "ok")
    print(f"  false closes across all {n * len(ids)} triages: {total_fc}")

    counts = correct_counts(runs, ids)
    maj = majority_correct(counts, n)
    mk_full, mk_unc = sum(maj[i] for i in ids), sum(maj[i] for i in unc)
    lo, hi = wilson(mk_full, len(ids))
    ulo, uhi = wilson(mk_unc, len(unc))
    print(f"  majority vote: full {mk_full}/{len(ids)} [{lo:.1%}, {hi:.1%}]   "
          f"uncontested {mk_unc}/{len(unc)} [{ulo:.1%}, {uhi:.1%}]")

    flips = [i for i in ids if 0 < counts[i] < n]
    print(f"\n  alerts that changed between repeats: {len(flips)}")
    for i in flips:
        mark = " contested" if i in contested else ""
        print(f"    {i} correct {counts[i]}/{n} expected={runs[0][i]['expected']}{mark}")
    never = [i for i in unc if counts[i] == 0]
    print(f"  uncontested alerts wrong in every repeat: {', '.join(never) or 'none'}")
    length_by_alert = Counter(i for run in runs for i in ids if is_length_error(run[i]))
    print(f"  length errors by alert: {dict(sorted(length_by_alert.items())) or 'none'}")

    if args.baseline:
        b_meta, b_rows = load_run(args.baseline)
        if b_meta["fingerprint"] != metas[0]["fingerprint"]:
            raise SystemExit("Baseline was scored on a different corpus.")
        b = {r["alert_id"]: r for r in b_rows}
        missing = [i for i in ids if i not in b]
        if missing:
            raise SystemExit(f"Baseline is missing alerts: {missing[:5]}")
        bep = (b_meta["identity"] or {}).get("endpoint", {})
        print(f"\nbaseline {b_meta['label']} (temperature {bep.get('temperature')}, top_p {bep.get('top_p')})")
        print(run_line(b_meta["label"], b, contested))
        for name, sel in (("full", ids), ("uncontested", unc)):
            only_maj = [i for i in sel if maj[i] and not is_correct(b[i])]
            only_base = [i for i in sel if is_correct(b[i]) and not maj[i]]
            line = (f"  majority vs baseline {name:12} majority-only {len(only_maj)}  baseline-only {len(only_base)}  "
                    f"McNemar exact p={mcnemar_exact(len(only_maj), len(only_base)):.3f}")
            if only_maj:
                line += f"  majority-only: {', '.join(only_maj)}"
            if only_base:
                line += f"  baseline-only: {', '.join(only_base)}"
            print(line)


if __name__ == "__main__":
    main()
