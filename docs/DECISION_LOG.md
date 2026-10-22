# Decision Log

## D-001: Freeze gaps-v1 as the baseline related-alert rendering (2026-10-21)

### Decision
All model comparisons on corpus v1 use `--related-render gaps-v1`. No further rendering variants are planned for corpus v1.

### Evidence
Local Q4 (nemotron-lightning-q4-32k), reasoning on, temperature 1.0, top_p 0.95, max_tokens 8192, 5 repeats per rendering, 500 triages each.

| Measure | raw | hours-v1 | gaps-v1 |
|---|---|---|---|
| alert-0073 false closes | 2/5 | 0/5 | 0/5 |
| False closes, all triages | nonzero (alert-0073) | 0/500 | 0/500 |
| Per-repeat full, mean | | 82.8 | 83.0 |
| Per-repeat uncontested, mean | | 79.0 | 79.6 |
| False escalations, uncontested benign | | 18/88 | 15/89 |
| Alerts changing between repeats | | 18 | 15 |
| Length errors | | 9 | 7 |
| Majority vote full | 88/100 | 85/100 | 81/100 |
| Majority vote uncontested | 83/84 | 81/84 | 79/84 |

### Rationale
1. Hard gate: zero false auto-close of true positives. raw fails it on alert-0073. hours-v1 and gaps-v1 both pass.
2. hours-v1 and gaps-v1 are not separable on this data. Per-repeat accuracy is within one alert. hours-v1 leads only on majority vote, which is sensitive to alerts near the 3 of 5 threshold. Production makes one call per alert, so per-repeat figures are the closer proxy.
3. gaps-v1 changes one field (minutes_apart to time_apart) and leaves window_minutes as soc_triage renders it. hours-v1 changes two. The smaller deviation from the source pipeline is preferred when performance is tied.

### Costs accepted
- Benign accuracy is lower than raw: majority vote full 81 vs 88 (McNemar p=0.016), uncontested 79 vs 83 (p=0.125). alert-0032 and alert-0033 are correct in 2 of 5.
- The choice is exploratory. Both hours-v1 and gaps-v1 were designed after seeing earlier results. Any published comparison must state this.

### Open
- alert-0098 is wrong in every repeat under all three renderings and on both endpoints (EXP-004). Trace and label review pending.
- Hosted endpoint precision: NVIDIA's API reference for the hosted model documents the NVFP4 checkpoint. Q4 vs hosted is a comparison of two 4-bit recipes plus serving stack, not a quantization-cost measurement. This supersedes Day 1 finding 4. See EXP-004.
