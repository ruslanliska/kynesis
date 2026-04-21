# Feature Specification: Image Assessment Endpoint

**Feature Branch**: `004-image-assessment`
**Created**: 2026-04-20
**Status**: Draft
**Input**: User description: "i wanna create enpoint to process images and assess them"

## Clarifications

### Session 2026-04-20

- Q: Image assessment mode — should the endpoint use vision-based direct assessment, OCR-first text assessment, or a hybrid? → A: Vision-based direct assessment (the image is sent directly to a vision-capable model along with the scorecard; text and visual aspects are evaluated together). OCR-only image handling remains the responsibility of the existing `/assessments/document` endpoint.
- Q: How many images per request? → A: Exactly one image per request for v1 — matches the single-file pattern of the document and audio endpoints. Multi-image support is deferred to a potential future feature.
- Q: Privacy of image bytes in logs/traces? → A: Metadata only — log filename, size, mime type, latency, and outcome; image bytes and base64 payloads MUST be excluded from logs and traces by default, since images are likely to carry PII (faces, IDs, private chat screenshots).
- Q: How should image assessments be classified in the existing content-type taxonomy (document, audio_conversation, …)? → A: Introduce a new distinct classification `image` — images are a different modality from documents or audio, and the downstream reasoning prompt should frame the content as a visual artifact.
- Q: Request timeout behavior? → A: Reuse the existing pipeline timeout and return the existing `PipelineTimeoutError` when exceeded — same behavior as the other assessment endpoints, so the frontend does not need image-specific timeout handling.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Assess an Image Against a Scorecard (Priority: P1)

A QA manager has a screenshot of a customer interaction (e.g., a chat conversation, a support portal view, a field agent's photo, a published marketing post) and wants to evaluate it against a scorecard. They submit the image file and scorecard definition to the backend. The system analyzes both the textual content visible in the image AND its visual aspects (layout, tone cues, branding, completeness), evaluates the image against each criterion, and returns a structured assessment result with per-criterion scores, feedback, and an overall weighted score — the same output shape as the existing text, document, and audio assessment endpoints.

**Why this priority**: This is the core value of the feature. Without it, QA managers cannot use image-based evidence in their scorecards, which today forces them to manually transcribe or describe screenshots before running an assessment. It unlocks a new content modality and closes a visible gap alongside the existing document and audio endpoints.

**Independent Test**: Can be fully tested by submitting a sample screenshot plus a scorecard with 3+ criteria, and verifying the response contains a per-criterion score (within each criterion's valid range), per-criterion feedback that references what is actually visible in the image, and a correctly calculated weighted overall score.

**Acceptance Scenarios**:

1. **Given** a valid scorecard and a supported image file, **When** submitted to the image assessment endpoint, **Then** the system returns structured scores for each criterion, per-criterion feedback referencing the image content, and a weighted overall score in the same shape as other assessment endpoints.
2. **Given** an image containing visible text (e.g., a chat screenshot), **When** assessed, **Then** the per-criterion feedback is grounded in the actual text visible in the image and does not hallucinate absent content.
3. **Given** an image with primarily visual content and little or no text (e.g., a photo, a UI mockup), **When** assessed against criteria that concern visual aspects, **Then** feedback reflects the visual content of the image.
4. **Given** a scorecard flagged with `use_knowledge_base = true`, **When** the image is submitted, **Then** the system retrieves relevant knowledge base context using a representation of the image content and includes it in the evaluation prompt.
5. **Given** the AI provider is unavailable or rate-limited, **When** an image assessment is submitted, **Then** the system returns a clear error with an appropriate status code — consistent with other assessment endpoints — and does not expose internal details.
6. **Given** the scorecard is not active (e.g., draft or archived status), **When** submitted, **Then** the system rejects the request with a validation error.

---

### User Story 2 - Validate Image Inputs Before Processing (Priority: P1)

Before the system spends time calling the AI provider, it must reject clearly invalid image submissions — missing filenames, unsupported formats, empty files, or files that exceed size limits — and return a clear, actionable error. This prevents wasted compute, avoids vendor-side errors, and gives the frontend a predictable contract for surfacing validation failures to end users.

**Why this priority**: Input validation is co-priority with the core flow. Without it, malformed requests produce opaque errors that waste AI spend and confuse frontend users. Matches the validation approach already used by the document and audio endpoints, so behavior is predictable across modalities.

**Independent Test**: Can be tested by submitting each invalid input case (missing filename, unsupported extension, empty file, oversized file) and verifying each returns a validation error with a clear, human-readable message and the correct HTTP status, without any AI provider call being made.

**Acceptance Scenarios**:

1. **Given** a file with no filename, **When** submitted, **Then** the system returns a validation error stating a filename is required.
2. **Given** an image with an unsupported extension, **When** submitted, **Then** the system returns a validation error that lists the supported formats.
3. **Given** an empty file (0 bytes), **When** submitted, **Then** the system returns a validation error stating the file is empty.
4. **Given** a file that exceeds the maximum image size, **When** submitted, **Then** the system returns a validation error stating the size limit in MB.
5. **Given** a malformed scorecard payload in the request, **When** submitted, **Then** the system returns a validation error describing the scorecard parsing issue.

---

### Edge Cases

- What happens when the image is extremely small, blurry, or mostly blank (e.g., a solid-color screenshot, or a 50x50 pixel image)? The system MUST return the assessment with feedback explicitly noting that the image did not contain enough analyzable content for a confident evaluation, rather than fabricating scores.
- What happens when the AI provider returns malformed or incomplete output? The system MUST validate the response against the expected scorecard schema and return an error if the output cannot be parsed into valid scores — matching the behavior of other assessment endpoints.
- What happens if the image contains content flagged by the provider's safety policies? The system MUST catch the provider-side safety error and return a clear, user-facing validation error without exposing internal details.
- What happens if the knowledge base is unavailable during an image assessment with `use_knowledge_base = true`? The system MUST proceed with the assessment without RAG context and include a warning in the response that knowledge base context was unavailable — consistent with other assessment endpoints.
- How does the system handle concurrent image assessment requests? The system MUST process requests independently with no shared state between requests.
- What happens when the image format is technically supported but the file is corrupt (e.g., truncated JPEG)? The system MUST return a validation error indicating the image could not be decoded, rather than surfacing an internal exception.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose an image assessment endpoint that accepts an uploaded image file and a scorecard definition, and returns an assessment result in the same structured shape as the existing assessment endpoints (per-criterion scores, per-criterion feedback, weighted overall score, overall feedback).
- **FR-002**: System MUST evaluate the image directly using a vision-capable AI model — considering both any visible text and the visual content of the image — rather than first extracting text via OCR and then discarding the image. (OCR-only extraction remains available via the existing document endpoint.)
- **FR-003**: System MUST accept a scorecard definition in the same format as the existing document and audio endpoints, and MUST reject scorecards whose status is not "active".
- **FR-004**: System MUST support the common web image formats already supported by the project's image path: PNG, JPG, JPEG, WebP, and GIF.
- **FR-005**: System MUST validate uploaded images before invoking the AI model: filename present, supported extension, non-empty content, and size within the configured maximum. Each failure MUST return a clear validation error.
- **FR-006**: System MUST enforce a maximum image file size consistent with what the vision model accepts (the project currently uses a 20 MB limit for image inputs); uploads exceeding this limit MUST be rejected before any AI call is made.
- **FR-007**: System MUST support an optional knowledge-base flag on the request. When set, the system retrieves relevant context from the configured knowledge base and includes it in the evaluation prompt.
- **FR-008**: System MUST return consistent error responses with clear messages and appropriate HTTP status codes for all failure modes — validation errors, AI-provider unavailability, AI rate-limit exceeded, AI-provider malformed output, and provider safety rejections.
- **FR-009**: System MUST emit observability data (structured logs, traces, and relevant metrics) for each image assessment request, consistent with the observability approach already used for other assessments. Logs and traces MUST include only metadata (filename, size, mime type, latency, outcome) and MUST exclude the raw image bytes and any base64-encoded payloads by default, to avoid leaking PII that images frequently carry.
- **FR-010**: System MUST require the same authentication as the other assessment endpoints (API-key authentication).
- **FR-011**: System MUST be stateless — it MUST NOT persist the uploaded image or the assessment result. Storage is the frontend's responsibility, consistent with the other assessment endpoints.
- **FR-012**: System MUST accept exactly one image file per request. Requests that omit the image or include multiple image files MUST be rejected with a clear validation error. Multi-image assessment is out of scope for v1.
- **FR-013**: System MUST classify image-assessment requests under a distinct content-type value (`image`) — separate from the existing document and audio classifications — so the downstream reasoning layer can frame the prompt as analyzing a visual artifact and per-modality analytics remain possible.
- **FR-014**: System MUST apply the same request-level timeout used by the existing reasoning/assessment pipeline. When the timeout is exceeded, the system MUST return the existing pipeline-timeout error response used by the other assessment endpoints, so the frontend's error handling is uniform across modalities.

### Key Entities

- **Image Assessment Request** (received in request, not persisted by backend): An image file plus a scorecard definition and optional knowledge-base flag. Key attributes: image file (bytes + filename + extension), scorecard (same shape as other endpoints), `use_knowledge_base` boolean.
- **Assessment Result** (returned in response, stored by frontend): Same shape as the result produced by other assessment endpoints — per-criterion scores with feedback, overall weighted score, overall feedback, and any warnings (e.g., knowledge base unavailable).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Image assessment results are returned within 30 seconds for images up to 20 MB when evaluated against a scorecard of up to 5 criteria.
- **SC-002**: 100% of successful image-assessment responses conform to the same structured output schema as the other assessment endpoints — no malformed or missing fields.
- **SC-003**: 100% of invalid image submissions (missing filename, unsupported format, empty file, oversized file, invalid scorecard payload) are rejected with a clear validation error before any AI call is made.
- **SC-004**: For images containing readable text, assessment feedback references content actually visible in the image at least 90% of the time in a sample review, with no fabricated text content.
- **SC-005**: When the AI provider is unavailable or rate-limited, the endpoint surfaces the error through the same error-taxonomy the other assessment endpoints use, so the frontend does not need image-specific error handling.
- **SC-006**: The endpoint handles at least 10 concurrent image-assessment requests without degradation in latency or correctness.

## Assumptions

- The new endpoint is a first-class sibling of the existing document and audio assessment endpoints, living under the same assessments route group and reusing the same scorecard definition, authentication, error taxonomy, and response schema.
- Vision-based assessment (confirmed in Clarifications) is the mode for this endpoint. OCR-only extraction continues to be handled by the existing document endpoint, which already accepts image inputs and extracts their text. This feature adds a distinct capability: evaluating an image as a visual artifact.
- A vision-capable AI model configured on the server (the same one used today for OCR and other AI work) is used for image assessment. Model selection remains a server-side configuration decision, not a per-request input.
- Supported image formats are the five already supported by the project's image path: PNG, JPG, JPEG, WebP, GIF.
- Maximum image size is 20 MB per file (matching the current project setting for vision inputs). If the vision model's own limit tightens in the future, this is adjusted server-side without a spec change.
- The frontend is responsible for storing uploaded images and assessment results — the backend remains stateless.
- Knowledge-base retrieval for an image uses a textual representation of the image content (e.g., a short description or the model's own reading of the image) to query the vector store; the precise retrieval-query construction is an implementation detail left to planning.
- Authentication reuses the existing API-key dependency already used by other assessment endpoints.
- Observability is provided by the same Logfire-based stack already used project-wide.
