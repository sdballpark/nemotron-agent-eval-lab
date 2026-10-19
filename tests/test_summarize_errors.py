import json

import pytest

from evallab.summarize import apply_rerun, error_class, load_run

IDENTITY = {"soc_triage_head": "h", "corpus_fingerprint": "f", "prompt_sha256": "p",
            "endpoint": {"model": "m", "reasoning": True}, "retries": 3}


def row(alert_id, status="ok", last=None):
    return {"type": "alert", "alert_id": alert_id, "status": status, "expected": "escalate",
            "outcome": "correct" if status == "ok" else None,
            "attempt_log": [{"status": last}] if last else []}


def write(path, rows, identity):
    lines = [{"type": "header", "run_label": path.stem, **identity}, *rows]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def test_error_class():
    assert error_class(row("a")) is None
    assert error_class(row("a", "model_error", "timeout")) == "infra"
    assert error_class(row("a", "model_error", "api_error")) == "infra"
    assert error_class(row("a", "model_error", "length")) == "model"
    assert error_class(row("a", "model_error", "ok")) == "model"
    assert error_class(row("a", "harness_error")) == "harness"


def test_rerun_replaces_only_infra_errors(tmp_path):
    base, rerun = tmp_path / "base.jsonl", tmp_path / "rerun.jsonl"
    write(base, [row("a1"), row("a2", "model_error", "timeout"), row("a3", "model_error", "length")], IDENTITY)
    write(rerun, [row("a2")], IDENTITY)
    meta, rows = load_run(str(base))
    merged, replaced = apply_rerun(meta, rows, str(rerun))
    assert replaced == ["a2"]
    assert [r["status"] for r in merged] == ["ok", "ok", "model_error"]


def test_rerun_rejects_alert_that_was_not_an_infra_error(tmp_path):
    base, rerun = tmp_path / "base.jsonl", tmp_path / "rerun.jsonl"
    write(base, [row("a2", "model_error", "timeout"), row("a3", "model_error", "length")], IDENTITY)
    write(rerun, [row("a3")], IDENTITY)
    meta, rows = load_run(str(base))
    with pytest.raises(SystemExit):
        apply_rerun(meta, rows, str(rerun))


def test_rerun_rejects_different_configuration(tmp_path):
    base, rerun = tmp_path / "base.jsonl", tmp_path / "rerun.jsonl"
    write(base, [row("a2", "model_error", "timeout")], IDENTITY)
    write(rerun, [row("a2")], {**IDENTITY, "retries": 1})
    meta, rows = load_run(str(base))
    with pytest.raises(SystemExit):
        apply_rerun(meta, rows, str(rerun))
