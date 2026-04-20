# Phase 1 Data Model: Two-Stage Reasoning Assessment Pipeline

**Feature**: 003-reasoning-aggregation
**Date**: 2026-04-20

Two groups of entities:

- **Internal / in-memory** (produced during a single request, never persisted, never in the response): `ReasoningQuestionRecord`, `AggregatedReasoning`, `StageOutcome`.
- **Public / response schema** (additive extensions to existing feature-002 models): `QuestionResult.rationale`, `OverallResult.reasoning_unavailable`.

All schemas are Pydantic v2 `BaseModel` with `CamelModel` aliasing where they flow to/from the API boundary.

---

## Internal models (new — `app/assessment/schemas.py`)

### ReasoningQuestionRecord

The reasoning stage's output for a single scorecard question.

| Field | Type | Required | Notes |
|---|---|---|---|
| `question_id` | `str` | yes | Must match a scorecard question id exactly. |
| `rationale` | `str` | yes | The reasoner's analytical narrative for this question. Minimum length: 1 char. Becomes the value of `QuestionResult.rationale` in the response. |
| `thinking_trace` | `str \| None` | no | Raw `reasoning_content` from DeepSeek R1's AIMessage. Captured when available; attached to LangSmith span; **NOT** included in API response. |
| `status` | `Literal["ok", "degraded", "missing"]` | yes, default `"ok"` | `degraded` = rationale produced but thinking trace absent; `missing` = no rationale (triggers reasoning-stage retry before the artifact is used). |

**Validation rules**:
- `rationale` must be non-empty for `status == "ok"` or `"degraded"`; for `"missing"`, `rationale == ""` is allowed.
- `question_id` must correspond to one question in the scorecard (validated in `AggregatedReasoning`).

### AggregatedReasoning

The complete bundle of reasoning records for one request. Passed as input to the structuring stage.

| Field | Type | Required | Notes |
|---|---|---|---|
| `scorecard_id` | `str` | yes | |
| `content_type` | `ContentType` | yes | Same enum as `AssessmentRequest.content_type`. |
| `content_preview` | `str` | yes | First ~500 chars of content for structuring-stage context (full content is re-sent to the structurer, but this is the prompt-context hint). |
| `records` | `list[ReasoningQuestionRecord]` | yes | One per scorecard question. |
| `full_trace_available` | `bool` | yes | True iff every record has `status == "ok"`. |

**Validation rules** (enforced at construction time):
- `{r.question_id for r in records}` must equal the scorecard's question-id set exactly (no missing, no extra).
- `records` must be non-empty.

**Lifecycle**:
1. Built by `reasoning_stage()` after the reasoning model call returns.
2. Passed to `structuring_stage()` as input.
3. Attached to the LangSmith parent span as structured metadata.
4. Discarded after the request completes.

### StageOutcome

Observability-facing record of what happened in a single stage. Not returned to the caller. Emitted as a Logfire span attribute.

| Field | Type | Required | Notes |
|---|---|---|---|
| `stage` | `Literal["reasoning", "structuring", "fallback"]` | yes | `fallback` is emitted only when the legacy flow ran. |
| `status` | `Literal["ok", "retry_exhausted", "timeout", "validation_failed"]` | yes | |
| `attempts` | `int` | yes | Number of attempts made (1 = first try only). |
| `duration_ms` | `int` | yes | Wall-clock duration of the stage. |
| `error` | `str \| None` | no | First-line of the final exception message on failure. |

---

## Public response schema (extend — `app/assessment/schemas.py`)

### QuestionResult (existing — extended)

Add one field. Existing fields unchanged.

| Field | Type | Required | Change |
|---|---|---|---|
| `question_id` | `str` | yes | unchanged |
| `section_id` | `str` | yes | unchanged |
| `score` | `float` (≥ 0) | yes | unchanged |
| `max_points` | `int` (≥ 0) | yes | unchanged |
| `passed` | `bool` | yes | unchanged |
| `critical` | `CriticalType` | yes | unchanged |
| `comment` | `str` | yes | unchanged — structurer's user-facing assessment |
| `suggestions` | `str \| None` | no | unchanged |
| **`rationale`** | `str` | yes (default `""`) | **NEW** — the reasoner's per-question rationale. `""` in fallback path. Camel alias: `rationale`. |

### OverallResult (existing — extended)

Add one field. Existing fields unchanged.

| Field | Type | Required | Change |
|---|---|---|---|
| `score` | `float` (0–100) | yes | unchanged |
| `max_score` | `int` | yes, default 100 | unchanged |
| `passed` | `bool \| None` | no | unchanged |
| `hard_critical_failure` | `bool` | yes, default `False` | unchanged |
| `summary` | `str` | yes | unchanged |
| **`reasoning_unavailable`** | `bool` | yes, default `False` | **NEW** — `True` when the result came from the legacy fallback path (reasoning stage failed). Camel alias: `reasoningUnavailable`. |

### AssessmentResult (existing)

Unchanged at the top level. Inherits the new fields via the extended `QuestionResult` and `OverallResult`.

---

## Relationships

```
AssessmentRequest           (unchanged input)
    │
    ▼
reasoning_stage() ──────► AggregatedReasoning
                              │
                              ├─ ReasoningQuestionRecord (× N questions)
                              │
                              ▼
                      structuring_stage()
                              │
                              ▼
                      AIScoreOutput (existing internal model, unchanged)
                              │
                              ▼
                      AssessmentResult (extended with rationale + reasoning_unavailable)

       ▲
       │
       │ on reasoning-stage retry exhaustion + failure_policy="fallback"
       │
run_legacy_assessment() ──► AssessmentResult (rationale="", reasoning_unavailable=True)
```

## State transitions

Per request, the pipeline walks one of three terminal states:

| Terminal state | Trigger | Response characteristics |
|---|---|---|
| `two_stage_success` | Both stages complete successfully. | `reasoning_unavailable=False`; `rationale` populated per question. |
| `fallback_success` | Reasoning stage exhausts retries AND `failure_policy="fallback"`. | `reasoning_unavailable=True`; `rationale=""` per question. |
| `error` | (a) Reasoning exhausts retries AND `failure_policy="strict"`, or (b) structuring exhausts retries, or (c) pipeline timeout. | HTTP error response, not an `AssessmentResult`. Handled by existing `_run_with_error_handling` error mappers. |

## Validation rules summary

- `AggregatedReasoning.records` coverage check MUST match the scorecard question-id set exactly before structuring_stage is invoked (else counts as reasoning failure).
- `AIScoreOutput` validation rules from feature 002 (`_validate_output`) are unchanged and continue to run inside the structuring stage's retry loop.
- `QuestionResult.rationale` length is not bounded by the schema; Pydantic default string validation applies.
- `OverallResult.reasoning_unavailable` defaults to `False` so existing code paths that construct `OverallResult(...)` without the new field keep working.
