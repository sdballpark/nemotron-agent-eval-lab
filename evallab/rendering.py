r"""Alternative rendering of the RELATED ALERTS enrichment.

soc_triage reports related-alert gaps as integer minutes (minutes_apart) and the
correlation window as window_minutes=1440. Day 2 traces showed models reading
365 minutes as about a year and 1440 minutes as a year (docs/day2-status.md).

"hours-v1" keeps every event, field and ordering, and replaces the two integers
with text: time_apart "6 hours 5 minutes" and window "24 hours". The source data
does not record which alert came first, so the text says how far apart the
alerts are, not before or after.

Hypothesis, fixed before any run with this rendering (EXP-002):
  On corpus v1 with local Q4, reasoning on, temperature 1.0, top_p 0.95 and
  max_tokens 8192, over 5 repeats:
  1. Reasoning traces mentioning "year" fall well below the 40 of 500 seen with raw minutes.
  2. alert-0073 false closes fall below the 2 of 5 seen with raw minutes.
  3. Majority-vote accuracy is not lower than with raw minutes.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

RENDERS = (None, "hours-v1")


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
    model_config = ConfigDict(extra="forbid", frozen=True)

    window: str
    events: tuple[RelatedEventDisplay, ...] = ()

    @property
    def count(self) -> int:
        return len(self.events)


def to_display(data) -> RelatedEventsDisplay:
    return RelatedEventsDisplay(
        window=duration_text(data.window_minutes),
        events=tuple(
            RelatedEventDisplay(alert_id=e.alert_id, title=e.title, technique_id=e.technique_id,
                                time_apart=duration_text(e.minutes_apart), shared_entity=e.shared_entity)
            for e in data.events
        ),
    )


class ReadableTimeEnrichment:
    """Passes every lookup through unchanged, except related(), whose data is shown in hours and minutes."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def related(self, **kwargs):
        result = self._inner.related(**kwargs)
        if result.data is None:
            return result
        return result.model_copy(update={"data": to_display(result.data)})


def wrap_enrichment(enrichment, related_render: str | None):
    if related_render is None:
        return enrichment
    if related_render == "hours-v1":
        return ReadableTimeEnrichment(enrichment)
    raise ValueError(f"Unknown related_render {related_render!r}. Known: {RENDERS}")
