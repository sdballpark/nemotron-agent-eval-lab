r"""Resumable evaluation run over the soc_triage corpus.

Writes runs/<label>.jsonl: one header line, then one line per alert. Metrics
are computed by a separate summarize step, never here, so a scoring change
never forces a rerun.

Usage:
  uv run python -m evallab.run --endpoint lightning-q4-local --reasoning off \
      --label pilot-q4-off --power "plugged in, Vantage Performance" --alerts alert-0001,alert-0002

Sampling overrides (--temperature, --top-p) and --related-render become part of
the run identity, so a run with different settings can never resume into or be
merged with another run. --related-render raw (the default) is recorded as null,
matching runs made before the option existed.

--concurrency N triages N alerts at once, each worker with its own pipeline.
Only the main thread writes the run file, so lines land in completion order,
not corpus order. Concurrency is recorded but is not part of the run identity.
Keep it at 1 for local endpoints: parallel requests on one GPU distort latency.

If the provider quota runs out (QuotaExhausted), the run stops. Alerts already
written are kept, the alert in flight is not written, and the same command
resumes once the quota resets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import tomllib
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from evallab.adapter import EndpointConfig, QuotaExhausted, complete, make_client
from evallab.rendering import RENDERS
from evallab.soc_bridge import TriageCallError, build_pipeline, preflight

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "endpoints.toml"
RUNS_DIR = REPO_ROOT / "runs"
PACKAGES = ("openai", "pydantic", "langgraph", "langchain-core")
IDENTITY_KEYS = ("soc_triage_head", "corpus_fingerprint", "prompt_sha256", "endpoint", "retries", "related_render")


def _val(x):
    return getattr(x, "value", x)


def _sum(values):
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_endpoint(name: str, reasoning: bool, max_tokens: int | None = None,
                  temperature: float | None = None, top_p: float | None = None) -> EndpointConfig:
    tables = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if name not in tables:
        sys.exit(f"Unknown endpoint {name!r}. Known: {sorted(tables)}")
    fields = dict(tables[name])
    if max_tokens:
        fields["max_tokens"] = max_tokens
    if temperature is not None:
        fields["temperature"] = temperature
    if top_p is not None:
        fields["top_p"] = top_p
    return EndpointConfig(name=f"{name}-reasoning-{'on' if reasoning else 'off'}", reasoning=reasoning, **fields)


def ollama_version(base_url: str) -> str | None:
    if not any(h in base_url for h in ("localhost", "127.0.0.1")):
        return None
    root = base_url.rsplit("/v1", 1)[0]
    try:
        with urllib.request.urlopen(f"{root}/api/version", timeout=5) as r:
            return json.load(r).get("version")
    except Exception:
        return None


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--endpoint", required=True)
    p.add_argument("--reasoning", choices=["on", "off"], required=True)
    p.add_argument("--max-tokens", type=int, help="Override the config value. Reasoning-on runs need more than 1200.")
    p.add_argument("--temperature", type=float, help="Override the config value (0.0 in config).")
    p.add_argument("--top-p", type=float, help="Override the config value (unset in config).")
    p.add_argument("--related-render", choices=["raw", *[r for r in RENDERS if r]], default="raw",
                   help="How related-alert time gaps are shown. raw is soc_triage's integer minutes.")
    p.add_argument("--label", required=True, help="Run name. Output goes to runs/<label>.jsonl")
    p.add_argument("--power", required=True, help="Power state as observed, or 'hosted' for remote endpoints")
    p.add_argument("--alerts", help="Comma-separated alert IDs. Default: whole corpus")
    p.add_argument("--limit", type=int)
    p.add_argument("--retries", type=int, default=3, help="Enrichment retries. 3 matches the original runs.")
    p.add_argument("--concurrency", type=int, default=1,
                   help="Alerts triaged at once. Keep 1 for local endpoints.")
    args = p.parse_args(argv)
    if args.concurrency < 1:
        sys.exit("--concurrency must be at least 1")

    head = preflight()
    from soc_triage.disposition import Disposition
    from soc_triage.evaluation.metrics import score_alert
    from soc_triage.evaluation.runner import corpus_fingerprint, load_corpus
    from soc_triage.pipeline.prompts import PROMPT_VERSION, SYSTEM_PROMPT

    cfg = load_endpoint(args.endpoint, args.reasoning == "on", args.max_tokens, args.temperature, args.top_p)
    related_render = None if args.related_render == "raw" else args.related_render
    alerts, labels = load_corpus()

    selected = alerts
    if args.alerts:
        wanted = {a.strip() for a in args.alerts.split(",") if a.strip()}
        unknown = wanted - {a["alert_id"] for a in alerts}
        if unknown:
            sys.exit(f"Unknown alert IDs: {sorted(unknown)}")
        selected = [a for a in alerts if a["alert_id"] in wanted]
    if args.limit:
        selected = selected[: args.limit]

    identity = {
        "soc_triage_head": head,
        "corpus_fingerprint": corpus_fingerprint(),
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "endpoint": cfg.model_dump(),
        "retries": args.retries,
        "related_render": related_render,
    }

    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{args.label}.jsonl"
    done: set[str] = set()
    resuming = path.exists()
    if resuming:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows or rows[0].get("type") != "header":
            sys.exit(f"{path} has no header line. Use a new --label.")
        mismatched = [k for k in IDENTITY_KEYS if rows[0].get(k) != identity[k]]
        if mismatched:
            sys.exit(f"{path} was started with different {mismatched}. Use a new --label.")
        done = {r["alert_id"] for r in rows if r.get("type") == "alert"}

    client = make_client(cfg)
    try:
        warm = complete(client, cfg, [{"role": "user", "content": "Reply with the word OK."}])
    except QuotaExhausted as e:
        sys.exit(f"Quota exhausted at warm-up, nothing written: {e}")
    if warm.status not in ("ok", "length"):
        sys.exit(f"Warm-up failed: {warm.status} {warm.error}")

    todo = [a for a in selected if a["alert_id"] not in done]
    print(f"{path.name}: {len(selected)} selected, {len(done)} already done, {len(todo)} to run. "
          f"Concurrency {args.concurrency}. Warm-up {warm.latency_s:.1f}s.", flush=True)

    tls = threading.local()

    def triage(alert: dict) -> dict:
        if not hasattr(tls, "pipe"):
            tls.pipe = build_pipeline(cfg, alerts, args.retries, related_render)
        pipeline, model = tls.pipe
        aid = alert["alert_id"]
        label = labels[aid]
        model.attempts = []
        case, trail, status, error = None, [], "ok", None
        started = time.perf_counter()
        try:
            case, trail = pipeline.run(alert)
            attempts = list(model.attempts)
        except QuotaExhausted:
            raise  # stop the run; this alert is not written
        except TriageCallError as e:
            status, error, attempts = "model_error", str(e), e.attempts
        except Exception as e:  # anything that is not a model failure
            status, error, attempts = "harness_error", f"{type(e).__name__}: {e}", list(model.attempts)
        wall = time.perf_counter() - started

        if status == "ok" and case is None:
            status, error = "harness_error", "pipeline returned no case"

        if status == "ok":
            record = score_alert(case, label, alert["tactic"]).model_dump(mode="json")
            record["suspected_injection"] = case.suspected_injection
            record["auto_closed"] = case.disposition is Disposition.CLOSE_BENIGN and not case.suspected_injection
        else:
            record = {
                "alert_id": aid, "technique_id": alert["technique_id"], "tactic": alert["tactic"],
                "corpus_slice": _val(label.corpus_slice), "expected": _val(label.disposition),
                "predicted": None, "outcome": None, "confidence": None, "enrichment_completeness": None,
                "degraded": None, "obeyed_injection": None, "flagged_injection": None,
                "suspected_injection": None, "auto_closed": None,
            }

        return {
            "type": "alert", **record, "status": status, "error": error,
            "attempts": len(attempts), "repair_used": len(attempts) > 1,
            "prompt_tokens": _sum(a.prompt_tokens for a in attempts),
            "completion_tokens": _sum(a.completion_tokens for a in attempts),
            "reasoning_chars": sum(len(a.reasoning) for a in attempts),
            "model_latency_s": round(sum(a.latency_s for a in attempts), 3),
            "wall_s": round(wall, 3), "trail": trail,
            "attempt_log": [a.model_dump() for a in attempts],
        }

    stopped: str | None = None
    with path.open("a", encoding="utf-8") as out:
        if resuming:
            out.write(json.dumps({"type": "resume", "utc": _utc(), "power": args.power,
                                  "concurrency": args.concurrency,
                                  "warmup_latency_s": round(warm.latency_s, 3)}) + "\n")
        else:
            out.write(json.dumps({
                "type": "header", "run_label": args.label, "started_utc": _utc(), **identity,
                "prompt_version": PROMPT_VERSION, "power": args.power, "concurrency": args.concurrency,
                "packages": {name: version(name) for name in PACKAGES},
                "python": sys.version.split()[0], "ollama_version": ollama_version(cfg.base_url),
                "selected_alerts": len(selected), "warmup_latency_s": round(warm.latency_s, 3),
            }) + "\n")
        out.flush()

        counts: dict[str, int] = {}
        pool = ThreadPoolExecutor(max_workers=args.concurrency)
        try:
            futures = [pool.submit(triage, a) for a in todo]
            for index, fut in enumerate(as_completed(futures), start=1):
                record = fut.result()
                out.write(json.dumps(record) + "\n")
                out.flush()
                key = record["outcome"] or record["status"]
                counts[key] = counts.get(key, 0) + 1
                print(f"[{index}/{len(todo)}] {record['alert_id']} {record['corpus_slice']:11} "
                      f"expected={record['expected']:12} predicted={record['predicted']!s:12} {key:16} "
                      f"attempts={record['attempts']} {record['wall_s']:.1f}s", flush=True)
        except QuotaExhausted as e:
            stopped = str(e)
        finally:
            # Ctrl+C, a crash or a spent quota: drop queued alerts. In-flight ones finish
            # but are not written; resume reruns them.
            pool.shutdown(wait=False, cancel_futures=True)

    print("counts:", counts, flush=True)
    if stopped:
        sys.exit(f"Stopped, quota exhausted: {stopped}\nWritten alerts are kept. Rerun the same command after the quota resets.")


if __name__ == "__main__":
    main()
