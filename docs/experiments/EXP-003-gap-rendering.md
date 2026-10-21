# EXP-003: Readable gaps with the raw window

## Question
EXP-002 rendered both related-alert gaps and the correlation window as text (hours-v1). It removed the "year" misreading and the alert-0073 false closes, but benign accuracy fell, mainly on alert-0032 and alert-0033. The EXP-002 traces cited "within 24 hours" when escalating, which suggested the window text made recurrence salient. EXP-003 separates the two changes: readable gaps, with the window left as soc_triage renders it.

This experiment is exploratory. The variant was chosen after seeing the EXP-002 results.

## Change
evallab/rendering.py, render "gaps-v1". minutes_apart 365 becomes time_apart "6 hours 5 minutes". window_minutes stays the integer 1440. Everything else in the prompt is byte-identical, verified by tests/test_rendering.py.

## Configuration
- Corpus v1 (dcb80e7067ff), soc_triage e77188f, prompt triage-v1.
- Local Q4 (nemotron-lightning-q4-32k), reasoning on, temperature 1.0, top_p 0.95, max_tokens 8192.
- 5 repeats: runs/v1-lightning-q4-on-t1-gaps-r1 to r5.
- Comparisons: raw minutes (runs/v1-lightning-q4-on-t1-r1 to r5) and hours-v1 (runs/v1-lightning-q4-on-t1-hours-r1 to r5), same configuration.

## Predictions and outcomes
The predictions were committed in 9f629b1 before any gaps-v1 run.

| # | Prediction | Outcome | Verdict |
|---|---|---|---|
| 1 | "year" mentions fall below 40 of 500, not necessarily to 0 | 5/500 (raw 40/500), Fisher exact p < 0.0001 | Supported |
| 2 | alert-0073 false closes fall below 2 of 5 | 0/5 | Supported in direction, not significant |
| 3 | alert-0032 and alert-0033 each correct in at least 3 of 5, and uncontested majority vote no lower than 82 of 84 | alert-0032 2/5, alert-0033 2/5, uncontested majority 79/84 | Not supported |

## Results across the three renderings
Same configuration, 5 repeats each.

| | Raw minutes | hours-v1 | gaps-v1 |
|---|---|---|---|
| "year" mentions | 40/500 | 0/500 | 5/500 |
| False closes | 2/500 | 0/500 | 0/500 |
| alert-0073 false closes | 2/5 | 0/5 | 0/5 |
| alert-0032 correct | 5/5 | 1/5 | 2/5 |
| alert-0033 correct | 4/5 | 1/5 | 2/5 |
| Per-repeat full, mean | 87.4 | 82.8 | 83.0 |
| Per-repeat uncontested, mean | 81.0 | 79.0 | 79.6 |
| Majority vote, full | 88/100 | 85/100 | 81/100 |
| Majority vote, uncontested | 83/84 | 81/84 | 79/84 |
| Length errors | 6/500 | 9/500 | 7/500 |

gaps-v1 against raw, majority vote (exact McNemar):
- Full: 0 alerts correct only under gaps-v1, 7 correct only under raw (alert-0032, alert-0033, alert-0053, alert-0057, alert-0065, alert-0067, alert-0099). p = 0.016.
- Uncontested: 0 against 4 (alert-0032, alert-0033, alert-0057, alert-0099). p = 0.125.

alert-0057 is malicious. It was lost to length errors (2 of 5), not to false closes.

## What this changes
The EXP-002 interpretation is refuted. The window text was not the cause of the benign losses: gaps-v1 kept the raw window and lost more benign closes than hours-v1, not fewer.

Revised hypothesis, not established: when the model correctly understands that related alerts are hours apart, recurring benign activity looks clustered, and Nemotron treats clustered recurrence as suspicious. Raw minutes, whether misread as a year or simply not read as a duration, made the recurrence look distant. That helped benign closes, and it is also what allowed alert-0073 to close. On this reading, the raw format was masking a recurrence bias rather than supporting correct judgment.

Alternative not ruled out: general prompt sensitivity, where any change to the related-alerts block shifts benign decisions regardless of meaning. A control that changes form without changing meaning, for example renaming the minutes_apart key while keeping the integers, would separate the two.

## Implications
- Both readable renderings eliminated the observed false closes across 1,000 triages. For an auto-close system where a false close is the costly failure, hours-v1 is the better of the two: no false closes, no "year" misreadings, and higher accuracy than gaps-v1.
- The remaining benign cost is a model judgment problem about recurrence, not a rendering problem. The candidate levers are a prompt change (triage-v2 guidance that documented, recurring baseline activity is not suspicious in itself) and deterministic handling of known baselines. Both belong on corpus v2 as confirmatory tests.

## Operational incident
The laptop entered sleep at 8:01 PM and woke at 3:38 AM, despite the AC idle timeout being set to never. Windows' Kernel-Power events 42 and 107 and Power-Troubleshooter event 1 record it. The likely cause is the lid-close action, which is separate from the idle timeout. The run resumed on its own. The request in flight at the time (alert-0079, repeat 2) failed with a CUDA error, an HTTP 500 from Ollama, which is classified as an infra error. alert-0079 was correct in the other 4 repeats, so its majority vote is unaffected and no rerun was needed. The lid action was set to do nothing on AC for the rest of the run, then restored.

## Limitations
- Corpus v1, one model configuration, 5 repeats per arm. Several comparisons were made across EXP-002 and EXP-003, so the single p = 0.016 should be read with that in mind.
- The "year" proxy was validated on raw runs only.
- The repeats score the same 100 alerts and are not independent samples.
