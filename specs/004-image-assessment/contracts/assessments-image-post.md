# Contract: `POST /api/v1/assessments/image`

**Feature**: 004-image-assessment
**Status**: Draft — v1

Assess a single uploaded image against a scorecard using a vision-capable model. Returns the same `AssessmentResult` shape as the existing text, document, and audio assessment endpoints.

## Authentication

Header: `X-API-Key: <key>`
Failure: `401 Unauthorized` with `{"detail": "..."}` (existing `verify_api_key` dependency).

## Request

- **Method**: `POST`
- **Path**: `/api/v1/assessments/image`
- **Content-Type**: `multipart/form-data`

### Form fields

| Field | Type | Required | Constraint |
|---|---|:-:|---|
| `file` | binary (image) | Yes | Exactly one. Extension ∈ {`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`} (case-insensitive). Size > 0 and ≤ 20 MB. |
| `scorecard` | string | Yes | JSON-encoded `ScorecardDefinition` (same shape as other assessment endpoints). `status` MUST equal `"active"`; MUST include at least one question. |
| `use_knowledge_base` | boolean | No | Default `false`. When `true`, server performs a describe-then-retrieve against the Pinecone knowledge base associated with the scorecard. |

### Example (curl)

```bash
curl -X POST https://api.example.com/api/v1/assessments/image \
  -H "X-API-Key: $KYNESIS_API_KEY" \
  -F "file=@./screenshot.png" \
  -F 'scorecard={"id":"sc-1","name":"Chat QA","status":"active",...}' \
  -F "use_knowledge_base=false"
```

## Response — success

- **Status**: `200 OK`
- **Content-Type**: `application/json`
- **Body**: `AssessmentResult` (existing Pydantic model; keys serialised in camelCase via `CamelModel`).

```jsonc
{
  "scorecardId": "sc-1",
  "scorecardVersion": 1,
  "contentType": "image",
  "assessedAt": "2026-04-20T14:03:22.118Z",
  "overall": {
    "score": 72.5,
    "maxScore": 100,
    "passed": true,
    "hardCriticalFailure": false,
    "summary": "…",
    "reasoningUnavailable": false
  },
  "sections": [
    { "sectionId": "sec-1", "sectionName": "Greeting", "score": 85.0, "weight": 40 },
    { "sectionId": "sec-2", "sectionName": "Resolution", "score": 65.0, "weight": 60 }
  ],
  "questions": [
    {
      "questionId": "q1",
      "sectionId": "sec-1",
      "score": 10.0,
      "maxPoints": 10,
      "passed": true,
      "critical": "none",
      "comment": "…",
      "suggestions": null,
      "rationale": "Per-question rationale produced by the vision-reasoning stage; grounds each score in visible evidence."
    }
  ]
}
```

Notes:
- `contentType` is always `"image"` for responses from this endpoint.
- `rationale` is populated by the vision stage; may still be non-empty when the describe-then-retrieve RAG path is disabled.
- `overall.reasoningUnavailable` is `false` on the happy path. It will be `true` only in the narrow case where a future change introduces a non-vision fallback; in v1 the image flow does not silently fall back to OCR (see research R9).

## Response — errors

All error bodies are `{"detail": "<human-readable message>"}`.

| Situation | Status | `detail` (example) |
|---|---|---|
| Missing `file.filename` | 422 | "File must have a filename." |
| Unsupported file extension | 422 | "Unsupported file format '.bmp'. Supported: .gif, .jpeg, .jpg, .png, .webp." |
| Empty file (0 bytes) | 422 | "File is empty." |
| File exceeds 20 MB | 422 | "File exceeds maximum size of 20MB." |
| Invalid `scorecard` JSON | 422 | "Invalid scorecard JSON: …" |
| Scorecard status is not `active` | 422 | "Only active scorecards can be used for assessments. Current status: 'draft'." |
| Scorecard has no questions | 422 | "Scorecard must have at least one question to run an assessment." |
| AI provider returned safety rejection on image | 422 | "Image could not be evaluated due to content policy. Please use a different image." |
| AI provider rate limit | 429 | "AI usage limit exceeded. Try again later." |
| AI provider unavailable / connection error | 502 | "AI provider unavailable." |
| AI provider returned malformed / unparseable output after retries | 502 | "AI provider returned invalid output. Please retry." |
| Reasoning exhausted under `failure_policy="strict"` | 502 | "Reasoning stage failed after retries." |
| Per-request timeout exceeded (default 180 s) | 504 | "Assessment pipeline timed out after 180s." |

No new error classes. No new status codes.

## Observability

Logfire span `image_assessment` is emitted for every request with the attributes in data-model.md §6. Image bytes and base64 payloads are **never** attached to Logfire spans or logs. LangChain's automatic LangSmith tracing does receive the LLM call and its image payload — LangSmith is treated as a separate, access-controlled analytics backend.

## Out of scope for v1

- Multiple images per request (FR-012).
- OCR-only assessment of an image (use `POST /api/v1/assessments/document` instead).
- PDF-as-image assessment (use the document endpoint; the sparse-PDF path already falls back to OCR).
- Non-listed image formats (HEIC, AVIF, BMP, TIFF).
- Per-request model override. The vision model is server-configured (`AssessmentConfig.vision_reasoning_model`).

## Compatibility notes

- The new route is additive. Existing `/api/v1/assessments`, `/api/v1/assessments/document`, `/api/v1/assessments/audio` routes are unchanged.
- The `ContentType` enum gains the value `"image"`. Clients that strictly validate enum values against a closed list should add `"image"` to their known set, but the API continues to return `"image"` only from this new endpoint.
