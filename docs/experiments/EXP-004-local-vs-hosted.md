# EXP-004: Local Q4_0 vs hosted Lightning on gaps-v1

## Question
Does the hosted build.nvidia.com Lightning endpoint triage the v1 corpus differently from the local Q4_0 GGUF under the frozen gaps-v1 rendering (D-001)?

This experiment is descriptive. No predictions were committed before the hosted runs.

## What is being compared
The Day 1 plan described this as a direct measure of the accuracy cost of 4-bit quantization. That framing is withdrawn. NVIDIA's API reference for nvidia-nemotron-3-5-lightning-30b-a3b documents the NVFP4 checkpoint (Four Over Six NVFP4, W4A16 on routed and shared experts, FP8 per-tensor dynamic scales on Mamba in_proj/out_proj and KV cache) and lists build.nvidia.com as a release channel. The page does not state the served precision outright, but the evidence points to NVFP4.

If so, both arms are 4-bit:
- Local: community Q4_0 GGUF (ggml-org), uniform 4-bit weights, served by Ollama.
- Hosted: NVIDIA's calibrated NVFP4 with FP8 on sensitive projections, served by NVIDIA's stack.

The comparison therefore covers quantization recipe and serving stack together. It says nothing about 4-bit vs BF16. NVIDIA's own BF16 vs NVFP4 benchmark figures are vendor-reported and must be cited from the official model card, not presented as a finding of this lab.

## Configuration
- Corpus v1 (dcb80e7067ff), soc_triage e77188f, prompt triage-v1, related-render gaps-v1.
- Reasoning on, temperature 1.0, top_p 0.95, max_tokens 8192, 5 repeats per arm.
- Local: nemotron-lightning-q4-32k, runs/v1-lightning-q4-on-t1-gaps-r1 to r5.
- Hosted: nvidia/nemotron-3.5-lightning-30b-a3b, runs/v1-lightning-hosted-on-t1-gaps-r1 to r5, power "hosted".
- Smoke test before the full run: runs/smoke-hosted-gaps (5 alerts). Hosted reasoning arrives in a separate field (reasoning_source "field"), finish_reason stop, no rate limiting.

## Results

| Measure | Local Q4_0 | Hosted |
|---|---|---|
| Per-repeat full, mean (range) | 83.0 (81-84) | 83.4 (80-86) |
| Per-repeat uncontested, mean (range) | 79.6 (78-81) | 79.2 (77-82) |
| False closes | 0/500 | 0/500 |
| False escalations, uncontested benign | 15/89 | 15/89 |
| Majority vote full | 81/100 | 86/100 |
| Majority vote uncontested | 79/84 | 81/84 |
| Model errors | 8 (7 length) | 3 (2 length, 1 invalid JSON) |
| Infra errors | 1 | 6 (all HTTP 502, r4 and r5) |
| Median latency per repeat | 37.8-44.7 s | 16.2-21.7 s |
| Median completion tokens per repeat | 2354-2857 | 2214-2412 |

Paired majority vote, exact McNemar:
- Full: hosted-only correct alert-0053, alert-0057, alert-0064, alert-0067, alert-0099. Local-only correct none. p=0.062.
- Uncontested: hosted-only alert-0057, alert-0099. Local-only none. p=0.50.

Alerts where per-alert correct counts differ by 2 or more:

| Alert | Local | Hosted | Note |
|---|---|---|---|
| alert-0047 | 5/5 | 3/5 | both hosted misses are length errors |
| alert-0048 | 5/5 | 3/5 | one hosted miss is a 502 |
| alert-0053 | 1/5 | 4/5 | contested |
| alert-0057 | 2/5 | 5/5 | |
| alert-0062 | 5/5 | 3/5 | both hosted misses are 502s |
| alert-0065 | 0/5 | 2/5 | contested |
| alert-0096 | 3/5 | 5/5 | |
| alert-0099 | 2/5 | 4/5 | |

## Interpretation
1. No detectable accuracy difference. All discordant majority-vote alerts favor hosted, but 3 of 5 are contested labels, and the uncontested difference is 2 alerts (p=0.50).
2. Safety behavior is identical: zero false closes and the same false escalation count.
3. Hosted scores are depressed by infrastructure. Infra errors are scored as incorrect, and they account for several local-better alerts (alert-0062, alert-0048).
4. alert-0032 and alert-0033 remain mostly wrong on hosted (2/5 and 1/5), so their gaps-v1 false escalations are not a Q4_0 artifact.
5. alert-0098 is wrong in all 5 hosted repeats, making it wrong in every run under every rendering and both endpoints. Label review is the next suspect.
6. Hosted single-request latency is roughly half of local. This is a deployment property and belongs in the inference economics analysis, not the model comparison.

## Harness findings
- The adapter does not retry HTTP 5xx. Provider outages are currently scored as model failures. Add retry with backoff, and report accuracy both with infra errors counted as wrong and excluded.
- New model error class observed: invalid JSON escape that the repair step cannot fix (r5 alert-0042). Track it separately from length errors.

## Limitations
- Descriptive, not confirmatory.
- Served precision of the hosted endpoint is inferred from documentation, not confirmed by the API.
- 100 alerts and 5 repeats per arm cannot detect differences of a few alerts.
