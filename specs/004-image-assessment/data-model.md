# Phase 1 Data Model: Image Assessment Endpoint

**Feature**: 004-image-assessment
**Date**: 2026-04-20
**Status**: Complete

This feature is **stateless** — nothing is persisted by the backend. The data model therefore consists of:

1. The request shape accepted by the new endpoint.
2. The response shape returned to the client (reuses the existing `AssessmentResult`).
3. The internal, in-memory artifacts produced during a request (all reused from feature 003).

---

## 1. Request

### `POST /api/v1/assessments/image` — multipart/form-data

| Field | Type | Required | Notes |
|---|---|:-:|---|
| `file` | file (binary) | Yes | The image to evaluate. One file per request. Content-Type inferred from extension. |
| `scorecard` | string (JSON) | Yes | JSON-encoded `ScorecardDefinition` — identical shape to the `/assessments/document` and `/assessments/audio` endpoints. |
| `use_knowledge_base` | boolean | No (default `false`) | When `true`, retrieve Pinecone context (see R3 in research.md for the describe-then-retrieve flow). |

No JSON body variant. Auth is header-based via `X-API-Key` (unchanged from other routes).

### Validation rules (enforced before any AI call)

- `file.filename` MUST be present and non-empty — else `ValidationError` (422).
- `file` extension (case-insensitive) MUST be in `{".png", ".jpg", ".jpeg", ".webp", ".gif"}` — else `ValidationError` (422) listing supported formats.
- `file` size MUST be > 0 bytes — else `ValidationError` (422) "File is empty."
- `file` size MUST be ≤ 20 MB (`MAX_IMAGE_SIZE`) — else `ValidationError` (422) stating the limit in MB.
- `scorecard` MUST be valid JSON decoding to a `ScorecardDefinition` — else `ValidationError` (422) with the parsing message.
- `scorecard.status` MUST equal `"active"` — else `ValidationError` (422) consistent with the other endpoints.
- Scorecard MUST have at least one question (enforced by the existing `AssessmentRequest._validate_has_questions`).

Exactly one `file` per request. The FastAPI signature is `file: UploadFile` (not `list[UploadFile]`), which means additional files sent under the same field are ignored by FastAPI and additional fields raise 422 — the contract is enforced by the route signature itself.

---

## 2. Response

### `AssessmentResult` (reused unchanged)

Returned shape is identical to the existing `AssessmentResult` already produced by `/api/v1/assessments`, `/api/v1/assessments/document`, and `/api/v1/assessments/audio`. See `app/assessment/schemas.py`:

- `scorecard_id: str`
- `scorecard_version: int`
- `content_type: ContentType` — value is the new `"image"` (see §4 below)
- `assessed_at: datetime`
- `overall: OverallResult`
- `sections: list[SectionResult]`
- `questions: list[QuestionResult]` — each with the feature-003 `rationale: str` populated by the vision-reasoning stage

No new fields are introduced on the response. Serialisation uses the existing `CamelModel` alias generator, so JSON keys stay camelCase.

### Error responses

All errors use the existing shape `{"detail": "<message>"}` and the existing status codes from `app/core/errors.py`:

| Situation | Status | Error class |
|---|---|---|
| Missing / invalid image, invalid scorecard JSON, inactive scorecard, missing questions | 422 | `ValidationError` |
| AI rate limit exceeded (OpenAI 429) | 429 | `AIRateLimitError` |
| AI provider unavailable / connection error / malformed output | 502 | `AIProviderError` |
| Reasoning stage exhausted retries under `failure_policy="strict"` | 502 | `ReasoningUnavailableError` |
| Per-request budget exceeded | 504 | `PipelineTimeoutError` |

No new error classes. No new status codes.

---

## 3. Internal artifacts (not returned, not persisted)

All internal artifacts are reused from feature 003 (`app/assessment/schemas.py`):

- **`AggregatedReasoning`** — produced by the new `vision_reasoning_stage()`. Fields (`scorecard_id`, `content_type`, `content_preview`, `records`, `full_trace_available`) are the same; `content_preview` is set to a short text marker for the image (e.g., `"[image: <filename>, <mime>, <size_bytes>B]"`) rather than the image itself, consistent with the "no image bytes in traces" policy.
- **`ReasoningQuestionRecord`** — one per scorecard question, with `rationale` produced by the vision model. `thinking_trace` is typically `None` because GPT-4o does not expose a thinking trace; this is expected and acceptable (the `rationale` field is what feeds into the response).
- **`StageOutcome`** — reused for the vision stage's observability span (with `stage="reasoning"` — the vision stage semantically fills the reasoning slot).

No new internal schemas. The vision stage produces the same artifact as the text reasoning stage, so the rest of the pipeline is oblivious to which stage-1 model ran.

---

## 4. Enum extension

Add a single new value to the existing `ContentType` enum in `app/assessment/schemas.py`:

```python
class ContentType(str, Enum):
    call_transcript = "call_transcript"
    chat_conversation = "chat_conversation"
    audio_conversation = "audio_conversation"
    code_review = "code_review"
    document = "document"
    email = "email"
    image = "image"   # NEW — feature 004
    other = "other"
```

Notes:
- This is **additive and non-breaking**. Existing clients never sent or received `"image"`, and the enum is declared `str, Enum` so round-trips through JSON are stable.
- The `AssessmentRequest.content_type` field continues to default to `ContentType.other`. The new image endpoint constructs the request server-side with `content_type=ContentType.image` — callers cannot override this.

---

## 5. Relationships and invariants

- `AssessmentRequest.content` (text) is **not** semantically meaningful for image requests. The orchestrator constructs the request with a **synthetic placeholder string** of the form `"[Image input — see vision-stage rationale for analysis. filename=<name>, size=<N>B]"`. The placeholder exists solely to satisfy the existing `min_length=50` Pydantic validator on `AssessmentRequest.content`; it is never sent to the vision model (the vision model receives the image bytes + scorecard context only), and it is not used by `_compose_result` to produce any user-visible field.
  - **Implementation constraint**: if `AssessmentRequest.content` validation ever changes (e.g., stricter min length, pattern check), the placeholder construction in `run_image_assessment` MUST be updated in lockstep. A cleaner long-term fix is to make `content` optional when `content_type == ContentType.image`; deferred for v1 to keep the change surface minimal.
- Invariant: every `AssessmentResult.questions[*].question_id` MUST appear in exactly one `scorecard.sections[*].questions[*].id`. This is enforced by the existing `_validate_output()` in `services.py` and remains unchanged.
- Invariant: `AssessmentResult.content_type == ContentType.image` for all responses from this endpoint.
- Invariant: no AI call is made if any validation in §1 fails.

---

## 6. Observability schema

Logfire span attributes (NEW span `image_assessment`):

| Attribute | Type | Present? | Notes |
|---|---|:-:|---|
| `filename` | str | Yes | — |
| `mime` | str | Yes | e.g. `image/png` |
| `size_bytes` | int | Yes | — |
| `scorecard_id` | str | Yes | For correlation with other assessment spans. |
| `use_knowledge_base` | bool | Yes | — |
| `knowledge_base_hit` | bool | When KB used | True if Pinecone returned context. |
| `outcome` | str | Yes | `"ok" \| "validation_error" \| "rate_limited" \| "provider_error" \| "timeout"` |
| `latency_ms` | int | Yes | Emitted via span end. |
| `image_base64` | — | **Never** | Explicitly excluded (per Clarification Q3). |
| `image_bytes` | — | **Never** | Explicitly excluded. |
| `message_content` | — | **Never** | The composed `HumanMessage` carrying the image is not captured as a span attribute. |

This schema is enforced by not passing the image/message into any span attribute or log message; the vision model call itself is instrumented by LangChain (which logs to LangSmith, a separate, access-controlled backend that is acceptable per R6).
