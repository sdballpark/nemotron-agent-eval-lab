# Research Log

## 2026-10-22: Gemini usage omits thinking tokens

Through the OpenAI-compatible endpoint, Gemini 3.8 Flash reports `completion_tokens` without thinking; thinking appears only in `total_tokens` (check: 16 + 23 = 39, total 398). Cost and token comparisons must use total minus prompt as billed output. Affects EXP-005 token row and cost; correction pending a measured rerun.

Resolved the same day: a 100-alert rerun with `total_tokens` recorded measured 600 thinking tokens per triage. Gemini SOC triage costs $5.43 per 1,000 triages at 2026 rates ($10.85 at 2027 rates); EXP-005 cost about $2.73, not $1.60.
