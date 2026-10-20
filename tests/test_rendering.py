import pytest

from evallab.rendering import duration_text, wrap_enrichment
from evallab.soc_bridge import preflight

preflight()
from soc_triage.enrichment.base import ResilientEnrichment, RetryPolicy  # noqa: E402
from soc_triage.enrichment.stubs import LocalEnrichment  # noqa: E402
from soc_triage.evaluation.runner import load_corpus  # noqa: E402
from soc_triage.pipeline.graph import TriagePipeline  # noqa: E402
from soc_triage.pipeline.model import StubModel  # noqa: E402


@pytest.mark.parametrize("minutes,text", [
    (0, "0 minutes"), (1, "1 minute"), (45, "45 minutes"), (60, "1 hour"),
    (61, "1 hour 1 minute"), (365, "6 hours 5 minutes"), (1440, "24 hours"),
])
def test_duration_text(minutes, text):
    assert duration_text(minutes) == text


def test_unknown_render_is_rejected():
    with pytest.raises(ValueError):
        wrap_enrichment(object(), "days-v9")


def _prompt_and_trail(alerts, render, alert_id):
    stub = StubModel()
    enrichment = wrap_enrichment(ResilientEnrichment(LocalEnrichment(alerts), RetryPolicy(max_attempts=3)), render)
    pipeline = TriagePipeline(enrichment, stub)
    alert = next(a for a in alerts if a["alert_id"] == alert_id)
    _, trail = pipeline.run(alert)
    return stub.calls[-1][1], trail


def test_hours_render_changes_only_the_related_block():
    alerts = load_corpus()[0]
    raw, raw_trail = _prompt_and_trail(alerts, None, "alert-0073")
    hours, hours_trail = _prompt_and_trail(alerts, "hours-v1", "alert-0073")
    assert raw_trail == hours_trail
    assert raw.split("RELATED ALERTS", 1)[0] == hours.split("RELATED ALERTS", 1)[0]
    assert '"minutes_apart": 365' in raw and '"window_minutes": 1440' in raw
    assert '"time_apart": "6 hours 5 minutes"' in hours and '"window": "24 hours"' in hours
    assert "minutes_apart" not in hours and "window_minutes" not in hours
