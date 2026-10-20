# EXP-002: Readable time gaps in related-alert enrichment

## Question
Day 2 traces showed Nemotron Lightning reading related-alert gaps given as integer minutes as calendar time: 365 minutes read as about a year, and window_minutes 1440 read as a year. On alert-0073 that misreading made a credential dump on the same host look stale, and the model auto-closed a malicious alert in 2 of 5 local repeats. Does rendering the gaps with explicit units remove the misreading without costing accuracy?

## Change
evallab/rendering.py, render "hours-v1". The RELATED ALERTS enrichment keeps every event, field and ordering. Two integers become text: minutes_apart 365 becomes time_apart "6 hours 5 minutes", and window_minutes 1440 becomes window "24 hours". Everything else in the prompt is byte-identical, which is verified by tests/test_rendering.py.

## Configuration
- Corpus v1 (dcb80e7067ff), soc_triage e77188f, prompt triage-v1.
- Local Q4 (nemotron-lightning-q4-32k), reasoning on, temperature 1.0, top_p 0.95, max_tokens 8192.
- 5 repeats: runs/v1-lightning-q4-on-t1-hours-r1 to r5.
- Comparison: the 5 raw-minute repeats in the same configuration, runs/v1-lightning-q4-on-t1-r1 to r5.

## Predictions and outcomes
The predictions were committed in 942dc0c before any hours-v1 run.

| # | Prediction | Raw minutes | hours-v1 | Test | Verdict |
|---|---|---|---|---|---|
| 1 | Traces mentioning "year" fall well below 40 of 500 | 40/500 (8.0%) | 0/500 | Fisher exact p < 0.0001 | Supported |
| 2 | alert-0073 false closes fall below 2 of 5 | 2/5 | 0/5 | Fisher exact p = 0.44 | Supported in direction, not significant |
| 3 | Majority-vote accuracy is not lower | 88/100 full, 83/84 uncontested | 85/100 full, 81/84 uncontested | McNemar p = 0.375 and 0.500 | Not supported |

Prediction 3 is not supported because both point estimates moved down. A non-significant difference does not establish that accuracy was not lower.

## Supporting results

| | Raw minutes | hours-v1 |
|---|---|---|
| Per-repeat full, mean and range | 87.4 (85 to 89) | 82.8 (82 to 84) |
| Per-repeat uncontested, mean and range | 81.0 (79 to 83) | 79.0 (76 to 81) |
| Uncontested FPR per repeat | 1 to 2 of 18 | 3 to 6 of 17 or 18 |
| False closes | 2/500 | 0/500 |
| Length errors | 6/500 | 9/500 |
| Median latency per repeat | 39.8 to 45.0 s | 40.1 to 43.7 s |

The majority-vote loss on uncontested alerts is alert-0032 and alert-0033, the PowerShell maintenance alerts on DC-01. Each closed correctly in only 1 of 5 hours-v1 repeats.

## Trace evidence on alert-0032 and alert-0033
- Raw minutes closed alert-0032 correctly in 5 of 5 repeats. Only 2 of those traces mention "year". For alert-0033, raw closed it in 4 of 5 repeats, and 1 of those 4 traces mentions "year". The misreading was not the main reason these alerts closed.
- In the hours-v1 escalations, the stated reason is the window, not the individual gaps. Examples: "three similar alerts in 24 hours raise suspicion", "occurred within 24 hours, indicating possible repeated activity", "multiple alerts over 24 hours for same user and host".

## Interpretation (hypothesis, not established)
hours-v1 bundled two changes. The gap text removed the temporal misreading, which was the target. The window text, shown as "24 hours" instead of the opaque integer 1440, made recurrence among related alerts salient. Nemotron already treats recurrence as suspicious, as on these same alerts in the Day 2 pilot. Separating the two changes tests this.

## Limitations
- Corpus v1, one model configuration, 5 repeats per arm.
- The "year" proxy was validated by reading a 12-trace sample of raw runs. Other temporal misreadings, for example months or days, were not measured under hours-v1.
- The repeats score the same 100 alerts, so they are not independent samples. Majority vote is the per-alert summary used for comparison.

## Next
EXP-003, exploratory on corpus v1: readable gaps with the window left as raw minutes, to separate the misreading fix from the salience effect. Whichever rendering wins is confirmed on corpus v2, not on v1.
