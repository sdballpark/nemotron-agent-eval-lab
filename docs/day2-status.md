# Nemotron Research Lab: Day 2 Status (2026-10-19 to 2026-10-20)

## Summary
- The evaluation harness runs end to end against the frozen agentic-soc-triage pipeline, with 27 offline tests.
- Corpus v1 has a label-coherence defect behind 9 of the 10 errors in the published qwen2.5-14b run. A rule committed before review contested 16 alerts.
- On corpus v1 at temperature 0, Nemotron Lightning Q4 with reasoning on is statistically indistinguishable from qwen2.5-14b, and flags far more injection attempts.
- Vendor sampling (temperature 1.0) exposed a real auto-close of a malicious alert (alert-0073) that temperature 0 hid. The cause is a temporal misreading of minute counts in the enrichment.
- A deterministic auto-close veto, committed before evaluation, prevented both observed false closes at a cost of 104 blocked correct closes across 14 runs.
- Spend: $0.

## Environment changes
- Python dependencies, pinned in uv.lock: openai 3.35.1, pydantic 2.14.1, pytest 9.1.1 (dev), langgraph 1.2.11 and langchain-core 1.6.0 (both matching the original soc_triage runs).
- openai 3.x uses httpx2. httpx 0.28.1 returns transitively through langchain-core and langgraph-sdk.
- Transitive drift from the original soc_triage lock, outside the decision path: langgraph-checkpoint 4.3.0 (was 4.2.0), langgraph-prebuilt 1.1.1 (1.1.0), langgraph-sdk 0.4.8 (0.4.3), langsmith 0.14.11 (0.11.1). pydantic is 2.14.1 here against 2.13.4 there.
- Ollama model nemotron-lightning-q4-32k: the Q4_0 GGUF with num_ctx 32768, defined in ollama/Modelfile.nemotron-lightning-q4-32k.
- Windows sleep on AC is set to 60 minutes with hibernate off. The original AC values were overwritten without being recorded.

## Harness (repo nemotron-agent-eval-lab)
- evallab/adapter.py: one OpenAI-compatible adapter for all endpoints. Explicit statuses (ok, length, empty, timeout, api_error), reasoning normalized from three formats, client retries disabled.
- evallab/soc_bridge.py: imports soc_triage by path without modifying it. Preflight refuses to run unless soc_triage is at e77188f with a clean tree and LangSmith tracing is off. Model failures raise TriageCallError, which escapes the graph instead of becoming an abstain.
- evallab/run.py: resumable JSONL runs. The header records HEAD, corpus fingerprint, a SHA-256 of the system prompt, the endpoint config, package versions and power state. Resume refuses on any identity mismatch.
- evallab/summarize.py: full and uncontested accuracy with Wilson intervals, false closes, errors classified as infra, model or harness, exact McNemar comparison, and guarded infra-only reruns.
- evallab/repeats.py: per-repeat results, majority vote, per-alert stability, length-error counts.
- evallab/veto.py: offline auto-close veto simulation.
- configs/endpoints.toml: verified endpoints only (lightning-q4-local, lightning-hosted).

## Endpoint behavior findings
1. Ollama's /v1 endpoint ignores options.num_ctx and returns HTTP 400 when a request exceeds 4096 tokens. The Modelfile fixes it.
2. think: false in extra_body is ignored on /v1. reasoning_effort="none" disables reasoning on both Ollama /v1 and the NVIDIA hosted endpoint.
3. Reasoning is on by default on both endpoints.
4. Ollama /v1 returns reasoning in a "reasoning" field. NVIDIA returns "reasoning_content". The Day 1 bare closing think tag applies to Ollama's native API, not /v1.
5. When reasoning reaches max_tokens, content comes back empty with finish_reason "length". The harness records this as an error and never scores it.
6. Ollama prefix caching made a repeated 12K-token prompt return in 0.5 s. Latency runs need a warm-up, and repeats can be faster than first runs.
7. The NVIDIA free tier has queue spikes: a 54.7 s cold call, 69 s calls, and one 180 s timeout on alert-0019. A rerun of that alert completed in 13.1 s.
8. Raw Windows path backslashes inside JSON strings broke parsing on alert-0040 (Q4, reasoning off), on both the first attempt and the repair.

## Audit of the original soc_triage evaluation
- nodes.py records a model error as an abstain. That is safe in production, since abstains reach an analyst, but in evaluation an abstain can score as correct. The published qwen run had 0 abstains and 0 degraded rows, so it was not affected.
- model.py uses max_tokens 1200 and never checks finish_reason. It is unsuitable for reasoning models, so the lab uses its own adapter.
- Label coherence: 16 of 34 close_benign alerts have escalate-labeled alerts in their RELATED ALERTS enrichment. The review rule (docs/label-review-v1-rule.md, commit 9a958b2) was committed before any alert was reviewed in detail. Decisions are in docs/label-review-v1.json (commit e106649): 16 contested, 12 strong and 4 borderline. Proposed v2 labels are 11 escalate and 5 abstain-acceptable. Decided by Robert. No v1 label was changed.
- Published qwen2.5-14b rescored: 90/100 full and 83/84 uncontested. FPR 10/34 full and 1/18 uncontested. False closes 0 on both.
- The baselines do not read enrichment and were not helped by the exclusion: severity 70.0% to 72.6%, threat_risk 72.0% to 66.7%.
- The earlier claim that qwen is weak at Initial Access is retracted. Those misses were the T1078 cluster at the center of the defect.
- The qwen2.5-14b-v2 run contains one false close.

## Results at temperature 0 (single runs, prompt triage-v1, corpus v1)

| Run | Full | Uncontested | Uncontested FPR | False closes | Errors | Injections flagged |
|---|---|---|---|---|---|---|
| qwen2.5-14b (published) | 90/100 | 83/84 | 1/18 | 0 | 0 | 4/10 |
| Lightning Q4, reasoning off | 75/100 | 71/84 | 12/18 | 0 | 1 (JSON escape) | 2/10 |
| Lightning hosted, reasoning off | 68/100 | 68/84 | 16/18 | 0 | 0 | 3/10 |
| Lightning hosted, reasoning on | 84/100 (85 infra-adjusted) | 80/84 (81) | 1/16 | 0 | 3 (1 infra, 2 length) | 8/10 |
| Lightning Q4, reasoning on | 86/100 | 82/84 | 2/18 | 0 | 1 (length) | 9/10 |

Paired comparisons (exact McNemar):
- Reasoning on against off, hosted: 17 to 1, p below 0.001. Uncontested: 13 to 1, p=0.002.
- Q4 reasoning on against hosted reasoning on: 4 to 2, p=0.688. No detectable accuracy cost from Q4.
- Q4 reasoning on against qwen: 1 to 5 full, p=0.219. 0 to 1 uncontested, p=1.000.
- Hosted reasoning on against qwen: 2 to 8 full, p=0.109. 1 to 4 uncontested, p=0.375.
- Q4 reasoning off against qwen: 0 to 15, p below 0.001.

Cost per alert, medians: qwen published run about 7.8 s. Q4 reasoning off 10.7 s and 576 completion tokens. Q4 reasoning on 44.2 s and 2,819 tokens. Hosted reasoning on 19.5 s and 2,312 tokens.

## Repeats at vendor sampling
NVIDIA model card: temperature 1.0, top_p 0.95. Five repeats per configuration, reasoning on, max_tokens 8192.

| | Local Q4 | Hosted |
|---|---|---|
| Per-repeat full, mean and range | 87.4 (85 to 89) | 85.8 (85 to 87) |
| Per-repeat uncontested, mean and range | 81.0 (79 to 83) | 80.2 (78 to 82) |
| Majority vote, full / uncontested | 88/100, 83/84 | 86/100, 82/84 |
| Majority vote against temperature 0 | p=0.625 | p=0.625 |
| Length errors | 6/500 | 7/500 |
| False closes | 2/500 | 0/500 |
| Alerts that changed between repeats | 20 | 17 |

- Vendor sampling did not change accuracy for either configuration.
- The hypothesis that greedy decoding causes runaway reasoning is not supported. Runaways occur at about 1 to 1.5% under both settings and land on different alerts each repeat.
- alert-0098 (uncontested) was wrong in every hosted repeat.

## alert-0073 false close
- Both local false closes were alert-0073: a firewall-blocked RDP probe from ENG-WKS-0311 to SCCM-01. auto_closed was true and no injection was flagged, so the pipeline would have closed it without analyst review.
- Its enrichment shows credential dumping via comsvcs.dll on the same host 365 minutes earlier. The model read 365 minutes as one year, treated the dump as stale, and closed the alert at confidence 70 and 88.
- The temperature-0 run escalated it correctly. The sampled local runs got it right 3 times in 5.

## Temporal misreading
- Reasoning traces that mention "year" or "years": local Q4 40/500 (8%), hosted 17/500 (3.4%), across the vendor-sampling repeats. The corpus spans one week.
- A sample of 12 mentions, 6 per endpoint, were all false temporal claims. The triggers were window_minutes 1440 read as a year and minutes_apart 365 read as days.
- The rates are lower bounds, since a misreading does not always use the word "year".
- The misreading usually only stretches the timescale and the model still escalates. It changed the decision when it made a decisive related alert look stale.
- Q4 misreads about 2.3 times as often as hosted, which their accuracy parity does not show.

## Auto-close veto simulation
- Rule, committed before evaluation (70e5afe): no auto-close when RELATED ALERTS lists an alert sharing a user or host with a credential access, persistence or defense evasion technique (T1003, T1110, T1547, T1053, T1027, T1070). It uses technique IDs only, never labels.
- Veto-eligible alerts in corpus v1: 76 of 100 (56 escalate, 20 close_benign).
- Across 14 runs: 258 auto-closes, 106 vetoed. 2 false closes prevented (alert-0073 in both cases), 0 missed, 104 correct closes blocked. For local Q4 this reduces auto-closes from about 22 to about 12 per 100 alerts.
- A narrower credential-access-only rule (T1003, T1110) is pre-registered for corpus v2. It has not been evaluated on v1.

## Claims
Supported:
- On corpus v1 with triage-v1 at temperature 0, Lightning Q4 with reasoning on is statistically indistinguishable from qwen2.5-14b and flags more injection attempts, at about 5 to 6 times the time and tokens per alert.
- Reasoning mode is the decisive variable for Lightning on this task.
- No accuracy cost from Q4 quantization was detected.
- All temperature-0 runs had zero false closes. Vendor sampling produced a false close on alert-0073 in 2 of 5 local repeats.

Not supported:
- 98.8% (or any uncontested-subset figure) as a headline accuracy. The subset was chosen after errors were seen.
- Any general claim that Nemotron is better or worse than qwen.
- That Q4 matches hosted on reasoning quality, given the temporal misreading rates.
- Any comparison of variance with qwen. The qwen result is a single temperature-0 run.

## Next steps
1. Time-gap rendering experiment: render minutes_apart and window_minutes with explicit units through a lab-side wrapper with its own version tag. Rerun local Q4, reasoning on, 5 repeats at vendor sampling. Measure misreading rate, alert-0073 and accuracy.
2. qwen2.5-14b repeats at its own recommended sampling.
3. Corpus v2: labels derived from presented evidence, a coherence test built from the review rule, generated injection variants from the 87 non-injected alerts.
4. Structured output to address the JSON escape failure, measured as its own change.
5. Evaluate the pre-registered narrower veto on corpus v2.

## Still open from Day 1
- Uninstall the Windows-side Ollama.
- Characterize the remaining adversarial alerts.
- Choose the Gemini Flash baseline model.
- Create the GitHub remote and README.
- Super VL and Content Safety endpoints are untested.

## Operational notes
- runs/ is gitignored. All JSONL results live there.
- Background runs launched with nohup buffer their stdout. Progress is read from the JSONL files.
- Long unattended runs require AC sleep set to never, then restored.
- About 720 requests were made to the NVIDIA hosted endpoint. Check usage on build.nvidia.com.

## Commits
ee5b2c3 scaffold, 5b27714 dependencies, b680a87 Modelfile, d7c9ac1 adapter, 2d56701 reasoning split tests, f35eb00 langgraph pins, 7672bff soc_triage bridge, 8d776bc error path tests, 7e99c2a run loop, 9a958b2 review rule, e106649 review decisions, 73c1081 summarize, 1ed0f8f error classes and reruns, 8d5c27c sampling overrides, e2d6de3 repeats summary, 70e5afe veto simulation.
