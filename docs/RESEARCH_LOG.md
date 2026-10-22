# Research Log

## 2026-10-22: Gemini usage omits thinking tokens

Through the OpenAI-compatible endpoint, Gemini 3.8 Flash reports `completion_tokens` without thinking; thinking appears only in `total_tokens` (check: 16 + 23 = 39, total 398). Cost and token comparisons must use total minus prompt as billed output. Affects EXP-005 token row and cost; correction pending a measured rerun.
