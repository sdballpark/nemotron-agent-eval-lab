r"""Alternative renderings of the RELATED ALERTS enrichment.

soc_triage reports related-alert gaps as integer minutes (minutes_apart) and the
correlation window as window_minutes=1440. Day 2 traces showed models reading
365 minutes as about a year and 1440 minutes as a year (docs/day2-status.md).

Every rendering keeps every event, field and ordering. The source data does not
record which alert came first, so gap text says how far apart alerts are, not
before or after.

  hours-v1  time_apart "6 hours 5 minutes" and window "24 hours"
  gaps-v1   time_apart "6 hours 5 minutes"; window_minutes stays the integer 1440

Hypothesis, fixed before any run with hours-v1 (EXP-002):
  On corpus v1 with local Q4, reasoning on, temperature 1.0, top_p 0.95 and
  max_tokens 8192, over 5 repeats:
  1. Reasoning traces mentioning "year" fall well below the 40 of 500 seen with raw minutes.
  2. alert-0073 false closes fall below the 2 of 5 seen with raw minutes.
  3. Majority-vote accuracy is not lower than with raw minutes.
  Outcome: docs/experiments/EXP-002-time-rendering.md (1 supported, 2 supported in
  direction, 3 not supported).

Hypothesis, fixed before any run with gaps-v1 (EXP-003, exploratory: the variant
was chosen after seeing EXP-002 results):
  Same corpus, model configuration and 5 repeats as EXP-002.
  1. Reasoning traces mentioning "year" fall below the 40 of 500 seen with raw
     minutes. This tests whether the raw window integer alone still triggers the
     misreading, so 0 of 500 is not predicted.
  2. alert-0073 false closes fall below the 2 of 5 seen with raw minutes.
  3. alert-0032 and alert-0033 each close correctly in at least 3 of 5 repeats, and
     uncontested majority-vote accuracy is no lower than 82 of 84.
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict

RENDERS = (None, "hours-v1", "gaps-v1")


def _unit(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def duration_text(minutes: int) -> str:
    hours, mins = divmod(int(minutes), 60)
    if hours == 0:
        return _unit(mins, "minute")
    if mins == 0:
        return _unit(hours, "hour")
    return f"{_unit(hours, 'hour')} {_unit(mins, 'minute')}"


class RelatedEventDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: str
    title: str
    technique_id: str
    time_apart: str
    shared_entity: str


class RelatedEventsDisplay(BaseModel):
    """hours-v1: gaps and window as text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window: str
    events: tuple[RelatedEventDisplay, ...] = ()

    @property
    def count(self) -> int:
        return len(self.events)


class RelatedEventsGapsDisplay(BaseModel):
    """gaps-v1: gaps as text, window as soc_triage renders it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_minutes: int
    events: tuple[RelatedEventDisplay, ...] = ()

    @property
    def count(self) -> int:
        return len(self.events)


def _events(data) -> tuple[RelatedEventDisplay, ...]:
    return tuple(
        RelatedEventDisplay(alert_id=e.alert_id, title=e.title, technique_id=e.technique_id,
                            time_apart=duration_text(e.minutes_apart), shared_entity=e.shared_entity)
        for e in data.events
    )


def to_display(data) -> RelatedEventsDisplay:
    return RelatedEventsDisplay(window=duration_text(data.window_minutes), events=_events(data))


def to_gaps_display(data) -> RelatedEventsGapsDisplay:
    return RelatedEventsGapsDisplay(window_minutes=data.window_minutes, events=_events(data))


class ReadableTimeEnrichment:
    """Passes every lookup through unchanged, except related(), whose data is transformed for display."""

    def __init__(self, inner, transform: Callable) -> None:
        self._inner = inner
        self._transform = transform

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def related(self, **kwargs):
        result = self._inner.related(**kwargs)
        if result.data is None:
            return result
        return result.model_copy(update={"data": self._transform(result.data)})


def wrap_enrichment(enrichment, related_render: str | None):
    if related_render is None:
        return enrichment
    if related_render == "hours-v1":
        return ReadableTimeEnrichment(enrichment, to_display)
    if related_render == "gaps-v1":
        return ReadableTimeEnrichment(enrichment, to_gaps_display)
    raise ValueError(f"Unknown related_render {related_render!r}. Known: {RENDERS}")
