"""Clean twins remove only the payload and leave everything else intact."""
import json
import os
from pathlib import Path

import pytest

from evallab.twins import PAYLOADS, make_clean_twins

DATA = Path(os.environ.get("SOC_TRIAGE_ROOT", str(Path.home() / "ai/projects/agentic-soc-triage"))) / "data"
pytestmark = pytest.mark.skipif(not (DATA / "alerts.json").exists(), reason="soc_triage corpus not present")


@pytest.fixture(scope="module")
def corpus():
    return json.loads((DATA / "alerts.json").read_text(encoding="utf-8"))


def test_payload_list_matches_labels():
    labels = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))
    labels = labels if isinstance(labels, dict) else {l["alert_id"]: l for l in labels}
    injected = {a: l["injected_field"] for a, l in labels.items() if l.get("injected_field")}
    assert injected == {a: f for a, (f, _) in PAYLOADS.items()}


def test_twins_remove_payload_and_change_nothing_else(corpus):
    twins = {a["alert_id"]: a for a in make_clean_twins(corpus)}
    originals = {a["alert_id"]: a for a in corpus}
    assert twins.keys() == originals.keys()
    for aid, orig in originals.items():
        twin = twins[aid]
        if aid not in PAYLOADS:
            assert twin == orig
            continue
        field, payload = PAYLOADS[aid]
        assert payload.strip() not in json.dumps(twin)
        assert {k: v for k, v in twin["event"].items() if k != field} == \
               {k: v for k, v in orig["event"].items() if k != field}
        assert {k: v for k, v in twin.items() if k != "event"} == {k: v for k, v in orig.items() if k != "event"}


def test_whole_field_payloads_remove_the_field(corpus):
    twins = {a["alert_id"]: a for a in make_clean_twins(corpus)}
    for aid in ("alert-0091", "alert-0092", "alert-0097"):
        assert PAYLOADS[aid][0] not in twins[aid]["event"]


def test_originals_are_not_mutated(corpus):
    before = json.dumps(corpus, sort_keys=True)
    make_clean_twins(corpus)
    assert json.dumps(corpus, sort_keys=True) == before
