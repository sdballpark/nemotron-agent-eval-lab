"""Bridge between the frozen agentic-soc-triage pipeline and the lab adapter.

The soc_triage repo is imported by path, never modified. preflight() pins it
to the commit the corpus and published results came from.

Model failures raise TriageCallError, not soc_triage's ModelError. The decide
node catches ModelError and records an abstain, which is right in production
(the alert reaches a human) but wrong in evaluation, where an abstain can score
as correct. TriageCallError escapes the graph so the harness records an error.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from evallab.adapter import Completion, EndpointConfig, complete, make_client

SOC_TRIAGE_ROOT = Path(os.environ.get("SOC_TRIAGE_ROOT", str(Path.home() / "ai/projects/agentic-soc-triage")))
EXPECTED_HEAD = "e77188f"
TRACING_VARS = ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")
FALSY = {"", "0", "false", "no", "off"}

# Verbatim from soc_triage.pipeline.model.OpenAICompatibleModel.decide.
REPAIR_TEMPLATE = (
    "That response was not valid. Error:\n"
    "{error}\n\n"
    "Reply with ONLY a JSON object matching the required "
    "schema. No prose, no code fences."
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def preflight(root: Path = SOC_TRIAGE_ROOT, expected_head: str = EXPECTED_HEAD) -> str:
    """Refuse to run unless tracing is off and soc_triage is at the pinned commit."""
    for var in TRACING_VARS:
        if os.environ.get(var, "").strip().lower() not in FALSY:
            raise RuntimeError(f"{var} is set. Tracing would send alert data off this machine. Unset it.")
    head = _git(root, "rev-parse", "HEAD")
    if not head.startswith(expected_head):
        raise RuntimeError(f"soc_triage HEAD is {head[:12]}, expected {expected_head}.")
    if _git(root, "status", "--porcelain"):
        raise RuntimeError("soc_triage working tree has uncommitted changes.")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return head


class TriageCallError(Exception):
    """A model call that produced no usable decision. Never scored as a disposition."""

    def __init__(self, message: str, attempts: list[Completion]) -> None:
        super().__init__(message)
        self.attempts = attempts


class AdapterTriageModel:
    """soc_triage TriageModel backed by the lab adapter."""

    def __init__(self, cfg: EndpointConfig) -> None:
        from soc_triage.pipeline.model import ModelDecision, ModelError, extract_json

        self._decision_cls = ModelDecision
        self._model_error = ModelError
        self._extract_json = extract_json
        self.cfg = cfg
        self.name = cfg.name
        self._client = make_client(cfg)
        self.attempts: list[Completion] = []

    def _call(self, messages: list[dict]) -> Completion:
        result = complete(self._client, self.cfg, messages)
        self.attempts.append(result)
        if result.status != "ok":
            raise TriageCallError(
                f"adapter status {result.status}: {result.error or result.finish_reason}",
                list(self.attempts),
            )
        return result

    def _parse(self, text: str):
        return self._decision_cls.model_validate(self._extract_json(text))

    def decide(self, system_prompt: str, user_prompt: str):
        self.attempts = []
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        first = self._call(messages)
        try:
            return self._parse(first.content)
        except (self._model_error, ValidationError) as first_error:
            messages += [
                {"role": "assistant", "content": first.content},
                {"role": "user", "content": REPAIR_TEMPLATE.format(error=first_error)},
            ]
            second = self._call(messages)
            try:
                return self._parse(second.content)
            except (self._model_error, ValidationError) as second_error:
                raise TriageCallError(f"invalid after repair: {second_error}", list(self.attempts)) from second_error


def build_pipeline(cfg: EndpointConfig, alerts: list[dict], retries: int):
    """Same enrichment chain as scripts/run_eval.py without fault injection."""
    from soc_triage.enrichment.base import ResilientEnrichment, RetryPolicy
    from soc_triage.enrichment.stubs import LocalEnrichment
    from soc_triage.pipeline.graph import TriagePipeline

    model = AdapterTriageModel(cfg)
    enrichment = ResilientEnrichment(LocalEnrichment(alerts), RetryPolicy(max_attempts=retries))
    return TriagePipeline(enrichment, model), model
