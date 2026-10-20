r"""Offline simulation of a deterministic auto-close veto.

Rule, fixed before computing any result:
  An alert the model would auto-close is routed to an analyst instead when its
  RELATED ALERTS enrichment, as rendered to the model, lists a related alert that
  (1) shares a user account or host with it, checked against soc_triage's own
      identity and asset lookups (a shared IP address or file name does not count), and
  (2) carries a credential access, persistence or defense evasion technique:
      T1003, T1110 (credential access); T1547, T1053 (persistence); T1027, T1070 (defense evasion).

The rule reads only technique IDs and entities that the pipeline shows the
model. It never reads labels. It is evaluated against stored runs, so no model
is called.

Usage:
  uv run python -m evallab.veto runs/v1-lightning-q4-on.jsonl runs/v1-lightning-q4-on-t1-r*.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Callable

from evallab.soc_bridge import preflight
from evallab.summarize import load_run

VETO_PREFIXES = ("T1003", "T1110", "T1547", "T1053", "T1027", "T1070")


def qualifies(event: dict, is_subject_entity: Callable[[str], bool]) -> bool:
    technique = (event.get("technique_id") or "").split(".")[0]
    return technique in VETO_PREFIXES and is_subject_entity(event.get("shared_entity") or "")


def related_events() -> tuple[dict[str, list[dict]], Callable[[str], bool], dict[str, str]]:
    preflight()
    from soc_triage.enrichment.base import ResilientEnrichment, RetryPolicy
    from soc_triage.enrichment.stubs import LocalEnrichment
    from soc_triage.environment import host_by_name, user_by_name
    from soc_triage.evaluation.runner import load_corpus
    from soc_triage.pipeline.graph import TriagePipeline
    from soc_triage.pipeline.model import StubModel
    from soc_triage.pipeline.prompts import ENRICH_CLOSE

    alerts, labels = load_corpus()
    stub = StubModel()
    pipe = TriagePipeline(ResilientEnrichment(LocalEnrichment(alerts), RetryPolicy(max_attempts=3)), stub)
    index: dict[str, list[dict]] = {}
    for alert in alerts:
        pipe.run(alert)
        prompt = stub.calls[-1][1]
        events: list[dict] = []
        if "RELATED ALERTS [" in prompt:
            body = prompt.split("RELATED ALERTS [", 1)[1].split("]:", 1)[1].split(ENRICH_CLOSE, 1)[0]
            try:
                events = json.loads(body).get("events", [])
            except (json.JSONDecodeError, AttributeError):
                events = []
        index[alert["alert_id"]] = [e for e in events if e.get("alert_id") != alert["alert_id"]]
    expected = {aid: getattr(lab.disposition, "value", lab.disposition) for aid, lab in labels.items()}
    return index, (lambda e: bool(host_by_name(e) or user_by_name(e))), expected


def simulate(rows: list[dict], vetoed: set[str]) -> dict[str, list[str]]:
    autos = [r for r in rows if r.get("status") == "ok" and r.get("auto_closed")]
    hit = [r for r in autos if r["alert_id"] in vetoed]
    return {
        "auto_closed": [r["alert_id"] for r in autos],
        "vetoed": [r["alert_id"] for r in hit],
        "prevented": [r["alert_id"] for r in hit if r["outcome"] == "false_close"],
        "blocked_correct": [r["alert_id"] for r in hit if r["outcome"] == "correct"],
        "missed": [r["alert_id"] for r in autos if r["outcome"] == "false_close" and r["alert_id"] not in vetoed],
    }


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+")
    args = p.parse_args(argv)

    index, is_subject, expected = related_events()
    vetoed = {aid for aid, events in index.items() if any(qualifies(e, is_subject) for e in events)}
    by_label = Counter(expected[a] for a in vetoed)
    print(f"veto-eligible alerts in corpus: {len(vetoed)} of {len(index)} "
          f"(escalate {by_label.get('escalate', 0)}, close_benign {by_label.get('close_benign', 0)})")
    print(f"alert-0073 veto-eligible: {'alert-0073' in vetoed}\n")

    totals: Counter = Counter()
    for path in args.runs:
        meta, rows = load_run(path)
        s = simulate(rows, vetoed)
        for k, v in s.items():
            totals[k] += len(v)
        line = (f"{meta['label']:36} auto_closed {len(s['auto_closed']):3}  vetoed {len(s['vetoed']):3}  "
                f"prevented {len(s['prevented'])}  blocked_correct {len(s['blocked_correct']):3}  missed {len(s['missed'])}")
        if s["prevented"] or s["missed"]:
            line += f"  prevented={s['prevented']} missed={s['missed']}"
        print(line)
    print(f"\nTOTAL auto_closed {totals['auto_closed']}  vetoed {totals['vetoed']}  prevented {totals['prevented']}  "
          f"blocked_correct {totals['blocked_correct']}  missed {totals['missed']}")


if __name__ == "__main__":
    main()
