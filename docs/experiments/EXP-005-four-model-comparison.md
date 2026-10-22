# EXP-005: Four-model comparison on gaps-v1

## Question
How do the two Lightning endpoints compare with the incumbent local model (qwen2.5:14b) and a current commercial Flash model (gemini-3.8-flash) on corpus v1 under the frozen rendering (D-001)?

Descriptive. No predictions were committed before these runs.

## Configurations
All runs: corpus v1 (dcb80e7067ff), soc_triage e77188f, prompt triage-v1, related-render gaps-v1, 5 repeats.

| Label prefix | Model | Reasoning | Temperature / top_p | max_tokens | Concurrency |
|---|---|---|---|---|---|
| v1-lightning-q4-on-t1-gaps | Lightning Q4_0 GGUF, local | on | 1.0 / 0.95 | 8192 | 1 |
| v1-lightning-hosted-on-t1-gaps | Lightning on build.nvidia.com (NVFP4 per EXP-004) | on | 1.0 / 0.95 | 8192 | 1 |
| v1-qwen14b-off-t07-gaps | qwen2.5:14b-instruct, local | off | 0.7 / 0.8 | 1200 | 1 |
| v1-gemini38flash-on-t1-gaps | gemini-3.8-flash, paid tier | on (provider default) | 1.0 / 0.95 | 8192 | 4 |

Each model ran at its vendor's published sampling. qwen2.5 has no reasoning mode.

## Results

| Measure | Gemini 3.8 Flash | qwen2.5:14b | Lightning hosted | Lightning local Q4 |
|---|---|---|---|---|
| Per-repeat full, mean (range) | 86.0 (86-86) | 90.2 (89-91) | 83.4 (80-86) | 83.0 (81-84) |
| Per-repeat uncontested, mean (range) | 84.0 (84-84) | 82.8 (82-83) | 79.2 (77-82) | 79.6 (78-81) |
| Majority vote full | 86/100 | 90/100 | 86/100 | 81/100 |
| Majority vote uncontested | 84/84 | 83/84 | 81/84 | 79/84 |
| False escalations, uncontested benign | 0/90 | 5/90 | 15/89 | 15/89 |
| False closes | 0/500 | 0/500 | 0/500 | 0/500 |
| Alerts changing between repeats | 0 | 2 | 16 | 15 |
| Errors | 1 (length) | 0 | 3 model, 6 infra | 8 model, 1 infra |
| Median latency per repeat | 8.3-8.7 s | 6.9-7.5 s | 16.2-21.7 s | 37.8-44.7 s |
| Median completion tokens per repeat | 443-460 (excludes thinking) | 248-258 | 2214-2412 | 2354-2857 |

## Paired majority vote, exact McNemar

| Pair | Full: only-left / only-right, p | Uncontested: only-left / only-right, p |
|---|---|---|
| Gemini vs qwen | 1 / 5, p=0.219 | 1 / 0, p=1.000 |
| Gemini vs Lightning hosted | 3 / 3, p=1.000 | 3 / 0, p=0.250 |
| Gemini vs Lightning local | 5 / 0, p=0.062 | 5 / 0, p=0.062 |
| qwen vs Lightning hosted | 5 / 1, p=0.219 | 2 / 0, p=0.500 |
| qwen vs Lightning local | 9 / 0, p=0.004 | 4 / 0, p=0.125 |

On uncontested alerts no pair differs at p < 0.05. The only significant result (qwen over Lightning local on the full set) rests largely on contested labels.

## Where the differences sit
Uncontested alerts that separate the models:
- alert-0032 and alert-0033: Lightning wrong in most repeats on both endpoints; Gemini and qwen correct.
- alert-0098: wrong in every repeat for Lightning (both endpoints) and qwen; Gemini correct in all 5.
- alert-0057 and alert-0099: Lightning local wrong on majority; everyone else correct.

alert-0032, alert-0033 and alert-0098 all sit in one entity cluster: host HELPDESK-0012 and user k.iverson. That cluster holds 15 of the corpus's 34 close_benign alerts, all labeled close_benign. Its alerts present the model with a dense history of routine enumeration and PowerShell activity. Lightning traces cite that history as an attack pattern (EXP-004, alert-0098). Gemini closes the uncontested cluster alerts and escalates the contested ones.

## Contested alerts
Gemini escalated 14 of the 16 contested alerts in all 5 repeats, the direction proposed for their v2 labels in the label review. qwen escalated 9 of 16 on majority. Model agreement is supporting evidence for the review, not validation: the review's test uses only the rendered prompt, and model outputs were excluded as evidence by rule.

## Home-field condition for qwen
soc_triage was developed and published with qwen2.5:14b-instruct (README, scripts/run_eval.py). The triage prompt has a single commit (b24884a), written before the first model evaluation (7aad5eb). One alternative prompt was tested on qwen and rejected for a false-close regression (f9008c3). The prompt was therefore not iterated against qwen's outputs, but it did survive one selection step measured on qwen. qwen's 90.2 here is consistent with the published 90% from 7aad5eb, which used raw rendering, so it is not a strict reproduction.

## Cost
- Lightning local and qwen: $0 marginal, on-premises GPU.
- Lightning hosted: $0 on build.nvidia.com free access.
- Gemini: GEMINI_COST_TBD for 500 triages, from the AI Studio Spend page once it settles. Paid Tier 1, $15 prepaid, $15 monthly cap. Thinking tokens are billed as output but are not reported in completion_tokens through the OpenAI-compatible endpoint, so per-triage cost must come from billing, not from run logs.

A first Gemini attempt on the free tier exhausted its daily quota after 9 alerts and wrote 91 error rows. It is kept in runs/failed/ and excluded. The runner now stops on exhausted quota (ac14630).

## Interpretation
1. On uncontested alerts, the four setups cannot be separated statistically on this corpus. Gemini was perfect and fully stable; qwen was one alert behind at zero marginal cost; both Lightning setups trailed by 4 to 5 alerts, mostly inside one entity cluster.
2. All four pass the hard gate: zero false auto-close of true positives across 2,000 triages.
3. Lightning spends roughly ten times qwen's completion tokens with reasoning on and does not convert that into accuracy here. Reasoning-off Lightning has not been run under gaps-v1.
4. Stability differs sharply. Gemini and qwen give the same answer on almost every alert across repeats. Lightning changes its answer on 15 to 16 alerts.

## Limitations
- Descriptive comparison with no committed predictions.
- 84 uncontested alerts. Errors within the HELPDESK-0012 cluster are correlated, so the Wilson intervals overstate precision.
- Model generations differ: a September 2026 commercial Flash model, a 2026 open 30B MoE, and a 2024 open 14B dense model.
- Sampling and reasoning settings follow each vendor and differ between models.
- Gemini traces carry the model's JSON reasoning field only; its thinking text is not returned.
- One synthetic corpus. Results say nothing about production alert volumes or distributions.

## Correction (2026-10-22): Gemini token counts and cost exclude thinking

Gemini's OpenAI-compatible endpoint reports `completion_tokens` as visible output only. Thinking tokens are billed at the output rate but appear only in `total_tokens`, and `completion_tokens_details` is empty. A direct check: prompt 16 + completion 23 = 39, total 398, so 359 thinking tokens were unreported. The adapter stored prompt and completion and dropped the total, so this experiment never recorded Gemini's thinking.

Consequences until corrected by a measured rerun:
- The Gemini median completion tokens (443-460) count visible output only. Lightning's counts include its reasoning text, so the token row is not comparable across models and should not be read as Gemini using fewer tokens.
- A list-price cost computed from stored tokens ($1.60 for 499 triages at $0.75 / $3.75 per 1M) understates the true cost by the unrecorded thinking.

Accuracy, false-close and stability results are unaffected.
