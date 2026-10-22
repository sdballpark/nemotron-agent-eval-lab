"""The results export must never publish a key and must not leak the home path."""
import json
from pathlib import Path

import pytest

from evallab.export_results import HOME, SecretFound, export_file, scrub


def test_scrub_rejects_key_shaped_values():
    for bad in ("nvapi-" + "a" * 40, "AIza" + "b" * 35, "token sk-" + "c" * 30):
        with pytest.raises(SecretFound):
            scrub({"nested": [bad]})


def test_scrub_replaces_home_path():
    assert scrub({"p": f"{HOME}/ai/projects/x"}) == {"p": "~/ai/projects/x"}


def test_triage_export_keeps_decisions_and_drops_traces(tmp_path: Path):
    src = tmp_path / "v1-test.jsonl"
    header = {"type": "header", "run_label": "v1-test", "endpoint": {"name": "e", "model": "m", "api_key_env": "X"}}
    alert = {"type": "alert", "alert_id": "alert-0001", "expected": "escalate", "predicted": "escalate",
             "outcome": "correct", "status": "ok", "attempt_log": [{"content": "long trace", "reasoning": "x" * 5000}]}
    src.write_text("\n".join(json.dumps(r) for r in (header, alert)) + "\n")
    body = export_file(src, "triage")
    assert body["alerts"][0]["predicted"] == "escalate" and "attempt_log" not in body["alerts"][0]
    assert "api_key_env" not in body["header"]["endpoint"]
