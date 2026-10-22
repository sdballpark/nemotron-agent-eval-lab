"""Export compact, publishable summaries of the experiment runs.

Raw run files (runs/*.jsonl) stay out of the repository: they hold full model
traces and are large. This writes, per run:
- results/triage/<label>.json: header identity and one row per alert with the
  decision, outcome, status, injection flags, tokens and latency. Every table and
  McNemar test in docs/experiments is computed from these fields.
- results/gateway/<label>.json: header identity and every episode with its tool
  calls, gateway responses, state diff and gate violations.
results/MANIFEST.json records the SHA-256 of each source run file so published
numbers can be traced to the exact raw data.

Only runs cited by a document under docs/ are published. EXCLUDED lists run
groups that exist on disk but no document references; they stay local.

The export aborts if any value matches an API-key pattern and replaces the home
directory with "~".

Usage: uv run python -m evallab.export_results
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS = REPO_ROOT / "runs"
OUT = REPO_ROOT / "results"

# Day 2 exploratory runs, made before the rendering experiments. No document cites them.
EXCLUDED = {
    "v1-lightning-q4-on", "v1-lightning-q4-off",
    "v1-lightning-hosted-on", "v1-lightning-hosted-off", "v1-lightning-hosted-on-rerun-infra",
    "v1-lightning-hosted-on-t1",  # raw rendering, hosted; EXP-004 compares on gaps-v1 only
}

SECRET_PATTERNS = [re.compile(p) for p in (r"nvapi-[A-Za-z0-9_\-]{10,}", r"AIza[0-9A-Za-z_\-]{20,}",
                                            r"\bsk-[A-Za-z0-9_\-]{20,}")]
HOME = str(Path.home())

HEADER_KEYS = ("run_label", "started_utc", "soc_triage_head", "corpus_fingerprint", "prompt_sha256", "prompt_version",
               "related_render", "corpus_variant", "retries", "power", "concurrency", "packages", "python",
               "ollama_version", "gateway_head", "max_turns", "repeats", "roles", "scenarios")
ENDPOINT_KEYS = ("name", "base_url", "model", "reasoning", "max_tokens", "temperature", "top_p")
ALERT_KEYS = ("alert_id", "corpus_slice", "expected", "predicted", "outcome", "status", "confidence",
              "suspected_injection", "flagged_injection", "obeyed_injection", "auto_closed", "attempts",
              "repair_used", "prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens", "reasoning_chars", "model_latency_s", "wall_s")
EPISODE_KEYS = ("scenario", "variant", "role", "repeat", "status", "turns", "calls",
                "privileged_or_unexposed_attempts", "approvals_created", "state_diff", "gate_violations",
                "prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens", "model_latency_s")
# Added 2026-10-22; written only when the run recorded them, so older runs export unchanged.
OPTIONAL_KEYS = frozenset({"total_tokens", "reasoning_tokens"})


class SecretFound(ValueError):
    pass


def scrub(value: Any) -> Any:
    """Replace the home path with ~ and refuse anything that looks like a key."""
    if isinstance(value, str):
        for p in SECRET_PATTERNS:
            if p.search(value):
                raise SecretFound(f"value matches secret pattern {p.pattern}")
        return value.replace(HOME, "~")
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def group_of(stem: str) -> str:
    return re.sub(r"-r\d+$", "", stem)


def _header(h: dict) -> dict:
    out = {k: h[k] for k in HEADER_KEYS if k in h}
    ep = h.get("endpoint") or {}
    out["endpoint"] = {k: ep[k] for k in ENDPOINT_KEYS if k in ep}
    return out


def _short_error(e: Any) -> Any:
    return e[:200] if isinstance(e, str) else e


def export_file(src: Path, kind: str) -> dict:
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows or rows[0].get("type") != "header":
        raise ValueError(f"{src} has no header")
    if kind == "triage":
        items = [{**{k: r.get(k) for k in ALERT_KEYS if k not in OPTIONAL_KEYS or k in r}, "error": _short_error(r.get("error"))}
                 for r in rows if r.get("type") == "alert"]
        body = {"header": _header(rows[0]), "alerts": sorted(items, key=lambda x: x["alert_id"])}
    else:
        items = [{**{k: r.get(k) for k in EPISODE_KEYS if k not in OPTIONAL_KEYS or k in r}, "error": _short_error(r.get("error"))}
                 for r in rows if r.get("type") == "episode"]
        body = {"header": _header(rows[0]), "episodes": sorted(items, key=lambda x: (x["role"], x["scenario"],
                                                                                    x["variant"], x["repeat"]))}
    return scrub(body)


def main() -> None:
    triage = [p for p in sorted(RUNS.glob("v1-*.jsonl")) if group_of(p.stem) not in EXCLUDED]
    groups = {"triage": triage, "gateway": sorted(RUNS.glob("gw-v1-*.jsonl"))}
    if OUT.exists():
        shutil.rmtree(OUT)
    manifest = {"lab_commit": subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                                             capture_output=True, text=True, check=True).stdout.strip(),
                "excluded_groups": sorted(EXCLUDED), "files": []}
    for kind, files in groups.items():
        (OUT / kind).mkdir(parents=True, exist_ok=True)
        for src in files:
            body = export_file(src, kind)
            dest = OUT / kind / f"{src.stem}.json"
            dest.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            manifest["files"].append({"kind": kind, "result": str(dest.relative_to(REPO_ROOT)),
                                      "source": f"runs/{src.name}",
                                      "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                                      "records": len(body.get("alerts") or body.get("episodes") or [])})
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"exported {len(manifest['files'])} runs to {OUT.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
