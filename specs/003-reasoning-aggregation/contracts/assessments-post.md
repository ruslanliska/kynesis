# Contract: Assessment Endpoints (two-stage pipeline)

**Feature**: 003-reasoning-aggregation
**Scope**: Additive changes only. Existing request and error contracts are unchanged.

Three endpoints produce `AssessmentResult`. All three route through the same orchestrator, so they share the contract delta below.

| Endpoint | Method | Content-Type |
|---|---|---|
| `/api/v1/assessments` | POST | `application/json` |
| `/api/v1/assessments/document` | POST | `multipart/form-data` |
| `/api/v1/assessments/audio` | POST | `multipart/form-data` |

---

## Request (unchanged)

No changes. The existing `AssessmentRequest` schema (and the multipart variants for document/audio) remain the request contract. The callers do not pick a reasoning model or temperature per request; all stage configuration is server-side via `AssessmentConfig`.

## Response — `AssessmentResult` (extended, additive only)

Delta against feature 002's schema:

```jsonc
{
  "scorecardId": "…",
  "scorecardVersion": 1,
  "contentType": "call_transcript",
  "assessedAt": "2026-04-20T12:00:00Z",

  "overall": {
    "score": 87.5,
    "maxScore": 100,
    "passed": true,
    "hardCriticalFailure": false,
    "summary": "…",
    "reasoningUnavailable": false   // NEW — true only when fallback path was used
  },

  "sections": [ /* unchanged */ ],

  "questions": [
    {
      "questionId": "q1",
      "sectionId": "s1",
      "score": 2.0,
      "maxPoints": 2,
      "passed": true,
      "critical": "none",
      "comment": "…",               // unchanged — structurer's user-facing assessment
      "suggestions": null,          // unchanged
      "rationale": "…"              // NEW — reasoner's per-question analysis. "" in fallback path.
    }
  ]
}
```

### Field semantics

| Field | Happy path (two-stage) | Fallback path |
|---|---|---|
| `overall.reasoningUnavailable` | `false` | `true` |
| `questions[*].rationale` | non-empty analytical narrative from the reasoning model | `""` (empty string) |
| All other fields | same meaning as feature 002 | same meaning as feature 002 |

### Consumer guidance

- Clients that ignore unknown fields are unaffected; no breaking change.
- Clients wanting to surface reasoning to reviewers SHOULD render `rationale` only when `reasoningUnavailable === false` OR `rationale.length > 0`.
- Clients SHOULD visually flag results with `reasoningUnavailable === true` (e.g., an "assessed without reasoning" badge).

---

## Error responses (unchanged shape, one new semantic case)

Error envelope remains `{"detail": "<message>"}` with appropriate HTTP status codes. No change to error shape.

| Scenario | Status | `detail` example | Change vs feature 002 |
|---|---|---|---|
| Validation failure (scorecard, content length, unsupported format, etc.) | 400 | `"Scorecard must have at least one question..."` | unchanged |
| AI provider rate-limited | 429 | `"AI provider rate limit exceeded"` | unchanged |
| AI provider unavailable (connection error, transient 5xx) | 502 | `"AI provider unavailable."` | unchanged |
| AI model LangChain error (both stages) | 502 | `"AI model error."` | unchanged |
| Reasoning stage retry exhausted, policy=`strict` | 502 | `"Reasoning stage failed after retries."` | **NEW semantic case — same status code** |
| Reasoning stage retry exhausted, policy=`fallback` | 200 | (no error; returns fallback result) | **NEW behaviour** |
| Structuring stage retry exhausted (after successful reasoning) | 502 | `"Assessment could not be scored. Questions: [q1, q4]."` | Replaces feature 002's generic `"Assessment failed after retries"` |
| Pipeline timeout (180s ceiling exceeded) | 504 | `"Assessment pipeline timed out after 180s."` | **NEW** |
| Oversize reasoning payload (exceeds structuring-model input budget) | 413 | `"Reasoning payload too large for the structuring model. Reduce scorecard question count or content length and retry."` | **NEW — FR-014** |

The `PipelineTimeoutError`, `ReasoningUnavailableError`, and `ReasoningPayloadTooLargeError` classes are defined in `app/core/errors.py`. `ReasoningUnavailableError` is caught inside the orchestrator and only bubbles up when `failure_policy="strict"`. `ReasoningPayloadTooLargeError` is raised pre-emptively by the structuring stage before any LLM call, so it always reaches the caller regardless of policy.

---

## Headers & auth (unchanged)

- `X-API-Key` header required (existing `verify_api_key` dependency).
- No new headers, no new auth flows.
- CORS behaviour unchanged.

## Idempotency (unchanged)

Requests are not idempotent; retrying a request produces a new assessment with possibly different reasoning text but scores within the same tolerance band (per spec edge cases).

## Contract-test checklist

Each endpoint MUST have contract tests covering:

- [ ] Happy path (two-stage): assert response structure, `reasoningUnavailable=false`, `rationale` non-empty per question.
- [ ] Fallback path: force reasoning-stage failure, assert response structure, `reasoningUnavailable=true`, `rationale=""` per question, HTTP 200.
- [ ] Strict-policy reasoning failure: set `failure_policy=strict`, force reasoning failure, assert HTTP 502 + correct detail.
- [ ] Structuring-stage retry exhaustion: force persistent schema validation failure, assert HTTP 502 + detail identifies failing question ids.
- [ ] Pipeline timeout: inject a slow reasoning mock that exceeds 180s, assert HTTP 504 + correct detail.
- [ ] Oversize reasoning payload: force a token-count estimate that exceeds the structuring-model budget, assert HTTP 413 + detail mentions "too large".
- [ ] Multipart document endpoint happy path (Constitution III): POST a small document fixture, assert HTTP 200 and valid `AssessmentResult`.
- [ ] Multipart audio endpoint happy path (Constitution III): POST a small audio fixture with mocked transcription, assert HTTP 200 and valid `AssessmentResult`.
- [ ] Backwards-compat: validate that a client schema WITHOUT the new fields (`rationale`, `reasoningUnavailable`) still parses the response via `AssessmentResult.model_validate(existing_response)` with `ignore_extra=True` semantics (Pydantic's default).
