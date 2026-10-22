"""EXP-005: four-model triage comparison on gaps-v1."""
from __future__ import annotations

from evallab.analysis.common import MODELS, contested_ids, count, load_group, majority, mcnemar, median_range, ok

PAIRS = (("gemini", "qwen14b"), ("gemini", "lt-hosted"), ("gemini", "lt-local"),
         ("qwen14b", "lt-hosted"), ("qwen14b", "lt-local"))


def compute() -> dict:
    contested = contested_ids()
    out = {"contested": contested, "models": {}, "pairs": {}}
    groups = {m: load_group(p) for m, p in MODELS.items()}
    for m, runs in groups.items():
        ids = sorted(runs[0])
        unc = [a for a in ids if a not in contested]
        full = [sum(ok(r[a]) for a in ids) for r in runs]
        uncs = [sum(ok(r[a]) for a in unc) for r in runs]
        benign = [r[a] for r in runs for a in unc if r[a]["expected"] == "close_benign" and r[a]["status"] == "ok"]
        out["models"][m] = {
            "repeats": len(runs),
            "full_mean": sum(full) / len(full), "full_range": (min(full), max(full)),
            "unc_mean": sum(uncs) / len(uncs), "unc_range": (min(uncs), max(uncs)),
            "fpr": (sum(r["predicted"] == "escalate" for r in benign), len(benign)),
            "false_closes": sum(r[a]["status"] == "ok" and r[a]["expected"] == "escalate"
                                and r[a]["predicted"] == "close_benign" for r in runs for a in ids),
            "triages": len(runs) * len(ids),
            "flips": sum(0 < count(runs, a) < len(runs) for a in ids),
            "maj_full": sum(majority(runs, a) for a in ids), "maj_unc": sum(majority(runs, a) for a in unc),
            "latency": median_range([[r[a]["model_latency_s"] for a in ids if r[a]["status"] == "ok"] for r in runs]),
            "tokens": median_range([[r[a]["completion_tokens"] for a in ids
                                     if r[a]["status"] == "ok" and r[a]["completion_tokens"] is not None] for r in runs]),
        }
    for x, y in PAIRS:
        X, Y = groups[x], groups[y]
        ids = sorted(X[0])
        for sub, sel in (("full", ids), ("uncontested", [a for a in ids if a not in contested])):
            xo = [a for a in sel if majority(X, a) and not majority(Y, a)]
            yo = [a for a in sel if majority(Y, a) and not majority(X, a)]
            out["pairs"][(x, y, sub)] = (xo, yo, mcnemar(len(xo), len(yo)))
    return out


def main() -> None:
    res = compute()
    ms = res["models"]
    print("EXP-005  four-model triage comparison, corpus v1, gaps-v1\n")
    rows = [
        ("Per-repeat full, mean (range)", lambda d: f"{d['full_mean']:.1f} ({d['full_range'][0]}-{d['full_range'][1]})"),
        ("Per-repeat uncontested, mean (range)", lambda d: f"{d['unc_mean']:.1f} ({d['unc_range'][0]}-{d['unc_range'][1]})"),
        ("Majority vote full", lambda d: f"{d['maj_full']}/100"),
        ("Majority vote uncontested", lambda d: f"{d['maj_unc']}/{100 - len(res['contested'])}"),
        ("False escalations, uncontested benign", lambda d: f"{d['fpr'][0]}/{d['fpr'][1]}"),
        ("False closes", lambda d: f"{d['false_closes']}/{d['triages']}"),
        ("Alerts changing between repeats", lambda d: str(d["flips"])),
        ("Median latency per repeat (s)", lambda d: f"{d['latency'][0]:.1f}-{d['latency'][1]:.1f}"),
        ("Median completion tokens per repeat", lambda d: f"{d['tokens'][0]:.0f}-{d['tokens'][1]:.0f}"),
    ]
    print(f"{'':40}" + "".join(f"{m:>16}" for m in ms))
    for label, fmt in rows:
        print(f"{label:40}" + "".join(f"{fmt(ms[m]):>16}" for m in ms))
    print("\nPaired majority vote, exact McNemar")
    for (x, y, sub), (xo, yo, p) in res["pairs"].items():
        print(f"  {x} vs {y:10} {sub:12} {x}-only {len(xo)}  {y}-only {len(yo)}  p={p:.3f}")


if __name__ == "__main__":
    main()
