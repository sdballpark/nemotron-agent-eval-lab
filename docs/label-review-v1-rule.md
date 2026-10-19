# Corpus v1 label review rule

Status: fixed before review. This file was committed before any alert in scope was examined in detail.

## Why

The 10-alert pilot found close_benign alerts whose RELATED ALERTS enrichment lists escalate-labeled alerts on the same entities. In those cases the label conflicts with evidence the pipeline itself presents to the model. An audit of all close_benign alerts found 16 of 34 with at least one escalate-labeled related alert.

## Corpus

agentic-soc-triage at e77188f, corpus fingerprint dcb80e7067ff.

## Scope

The 16 close_benign alerts whose rendered RELATED ALERTS section lists at least one escalate-labeled alert:

alert-0006, alert-0007, alert-0008, alert-0009, alert-0010, alert-0011, alert-0051, alert-0053, alert-0064, alert-0065, alert-0066, alert-0067, alert-0068, alert-0069, alert-0097, alert-0100

## Evidence allowed

Only the user prompt as rendered by the pipeline: the untrusted alert block plus the four enrichment results, captured with StubModel so no model is involved.

Model outputs from any run are not evidence.

Known exposure: qwen2.5-14b outcomes for these alerts were seen before this rule was written. Every decision must therefore quote specific text from the rendered prompt, so it can be checked without trusting the reviewer.

## Test

An alert is contested when both conditions hold.

1. Shared subject. At least one escalate-labeled related alert involves the same user account or the same host as the alert under review. A shared external IP address, network peer, or file name on its own does not satisfy this condition.
2. Bearing. That related activity could plausibly make the reviewed alert attacker-driven. Examples: credential theft, brute force, or credential dumping against an account, combined with a logon by that account; persistence, execution, or defense evasion on the host where the reviewed activity happens. Related activity counts whether it occurred before or after the reviewed alert, provided it appears in the rendered enrichment.

Malicious activity that shares an entity but cannot explain the reviewed event does not satisfy condition 2.

If either condition fails, the label stands.

## Effect on scoring

- No v1 label is changed.
- Contested alerts are listed with their decisions in docs/label-review-v1.json.
- Every run reports two results: the full corpus on original labels, and the uncontested subset on original labels.
- The published qwen2.5-14b run is rescored the same way.
- Each contested alert records a proposed v2 label, escalate or abstain-acceptable. That proposal feeds corpus v2 only and never rescores v1.

## Decision record

For every alert in scope: alert_id, decision (contested or stands), the shared subject, related alert IDs relied on, a short quote from the rendered prompt, a one-line rationale, and a proposed v2 label when contested.

Decisions are made by Robert. Drafts are proposals until confirmed.

## Forward use

This test becomes the coherence check in the corpus v2 test suite.
