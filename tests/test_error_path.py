"""The safety property: a failed model call is an error, never an abstain.

The adapter is replaced with a scripted fake, so these run offline against the
real soc_triage graph and enrichment.
"""
import json

import pytest

from evallab import soc_bridge
from evallab.adapter import Completion, EndpointConfig
from evallab.soc_bridge import TriageCallError, build_pipeline, preflight

preflight()
from soc_triage.evaluation.runner import load_corpus  # noqa: E402

CFG = EndpointConfig(name="fake", base_url="http://127.0.0.1:9/v1", model="fake",
                     reasoning=False, max_tokens=1200, temperature=0)
VALID = json.dumps({
    "disposition": "escalate", "confidence": 80, "summary": "s", "reasoning": "r",
    "recommended_action": "a", "citations": [], "suspected_injection": False, "injection_note": None,
})


def fake(status="ok", content=""):
    return Completion(endpoint="fake", model="fake", reasoning_enabled=False, status=status,
                      content=content, finish_reason="length" if status == "length" else "stop", latency_s=0.0)


@pytest.fixture(scope="module")
def alerts():
    return load_corpus()[0]


@pytest.fixture
def scripted(monkeypatch):
    calls = []

    def install(*responses):
        queue = list(responses)

        def fake_complete(client, cfg, messages):
            calls.append([dict(m) for m in messages])
            return queue.pop(0)

        monkeypatch.setattr(soc_bridge, "complete", fake_complete)
        return calls

    return install


def test_length_status_escapes_graph_instead_of_abstaining(alerts, scripted):
    calls = scripted(fake("length"))
    pipeline, _ = build_pipeline(CFG, alerts, retries=3)
    with pytest.raises(TriageCallError) as exc:
        pipeline.run(alerts[0])
    assert "length" in str(exc.value)
    assert [a.status for a in exc.value.attempts] == ["length"]
    assert len(calls) == 1


def test_invalid_twice_raises_after_one_repair(alerts, scripted):
    calls = scripted(fake(content="not json"), fake(content="still not json"))
    pipeline, _ = build_pipeline(CFG, alerts, retries=3)
    with pytest.raises(TriageCallError) as exc:
        pipeline.run(alerts[0])
    assert "invalid after repair" in str(exc.value)
    assert len(exc.value.attempts) == 2
    assert calls[1][-2] == {"role": "assistant", "content": "not json"}
    assert calls[1][-1]["content"].startswith("That response was not valid. Error:")


def test_repair_recovers_and_logs_both_attempts(alerts, scripted):
    scripted(fake(content="not json"), fake(content=VALID))
    pipeline, model = build_pipeline(CFG, alerts, retries=3)
    case, _ = pipeline.run(alerts[0])
    assert case.disposition.value == "escalate"
    assert len(model.attempts) == 2


def test_valid_first_attempt(alerts, scripted):
    calls = scripted(fake(content=VALID))
    pipeline, model = build_pipeline(CFG, alerts, retries=3)
    case, _ = pipeline.run(alerts[0])
    assert case.disposition.value == "escalate"
    assert len(model.attempts) == 1 and len(calls) == 1
