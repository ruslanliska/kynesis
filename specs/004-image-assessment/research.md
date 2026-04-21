# Phase 0 Research: Image Assessment Endpoint

**Feature**: 004-image-assessment
**Date**: 2026-04-20
**Status**: Complete — no open NEEDS CLARIFICATION items

All scope-defining decisions are already pinned in the spec's Clarifications section (2026-04-20). This document records the technical rationale, alternatives considered, and integration patterns for the implementation.

---

## R1. Vision-reasoning-stage model

- **Decision**: Use **OpenAI `gpt-4o`** via the already-installed `langchain-openai` (`ChatOpenAI`).
- **Rationale**:
  - `gpt-4o` is vision-capable and is already used in the project for the existing OCR path (see `app/assessment/ocr.py`) and as the text-flow structuring escalation option. No new SDK, billing, or approval needed.
  - DeepSeek R1 (`deepseek-reasoner`), the text-flow reasoning model, does **not** accept image inputs. The whole architectural reason for reusing the two-stage pattern is that the stage-1 model needs to "see" the image; that forces a vision-capable model for stage 1.
  - `gpt-4o` supports multi-part chat content (`{"type": "image_url", ...}`) which LangChain's `ChatOpenAI` wraps natively — no custom transport code needed.
  - Cost profile is acceptable: per-request cost for a single image + moderately-sized scorecard is well below the audit-audio path's Whisper + text-assessment cost.
- **Alternatives considered**:
  - **Anthropic Claude 3 Opus/Sonnet vision** — high quality, but no existing `AnthropicConfig` / API key wired up. Deferred as a future v2 option.
  - **Gemini 1.5 Pro vision** — new provider, new SDK. Rejected for v1 on the same integration-cost basis.
  - **Multi-step: OCR-then-text-reason** — explicitly rejected in spec Clarification Q1 (vision-based direct assessment chosen).
  - **DeepSeek V3 vision** — not currently supported by `deepseek-reasoner` / `deepseek-chat`. Rejected.

## R2. Pipeline shape — fit the vision stage into the existing two-stage flow

- **Decision**: Keep the existing **two-stage** pipeline shape. Stage 1 is a new `vision_reasoning_stage()` that replaces `reasoning_stage()` for image requests; stage 2 (`structuring_stage`) and result composition (`_compose_result`) are reused **unchanged**.
- **Rationale**:
  - Preserves the response contract (including the `rationale` field on each `QuestionResult`, added in feature 003) — the frontend sees the same shape across modalities.
  - Keeps most of the hard-won complexity (retries, coverage validation, payload-size guard, `asyncio.wait_for` budget) in one place. The image path reuses it.
  - Minimises risk: stage 2 is the part that breaks in subtle ways (schema mismatch, option id mapping); leaving it untouched means we only have to re-qualify stage 1 and the orchestrator.
- **Alternatives considered**:
  - **Single-stage with `gpt-4o.with_structured_output(AIScoreOutput)` directly on the image** — simpler (one AI call), but loses the rationale-per-question artifact that feature 003 introduced. Would regress the response shape for image assessments relative to text ones. Rejected.
  - **Three-stage (describe → reason → structure)** — would reuse the DeepSeek reasoner, but the describe step throws away visual fidelity, which is the whole point of choosing vision over OCR. Rejected as redundant with the OCR flow.

## R3. Knowledge-base (RAG) retrieval for image inputs

- **Decision**: When `use_knowledge_base=true`, perform a **lightweight vision-based describe call first** (`gpt-4o-mini` by default, configurable) to produce a short text description of the image; use that description as the query against the existing Pinecone-backed `get_rag_context(scorecard_id, query)` helper; inject the retrieved context into the vision-reasoning prompt. When `use_knowledge_base=false`, skip the describe call entirely.
- **Rationale**:
  - The text-flow equivalent is `get_rag_context(scorecard.id, request.content[:1000])` — i.e., use the content as the query. Images cannot be directly used as a Pinecone query because the embedding space is text-only.
  - Using a cheaper vision model (`gpt-4o-mini`) for the describe step keeps the extra cost small relative to the primary reasoning call.
  - The describe call is gated by `use_knowledge_base`, so non-KB requests incur zero overhead from this step.
  - Matches the spec's Clarification deferral: the query-construction strategy is explicitly left to planning.
- **Alternatives considered**:
  - **Embed the image directly and query Pinecone** — requires a multimodal embedding model; not wired up in the current Pinecone index (index uses text embeddings from feature 002). Would require re-indexing. Rejected for v1.
  - **Skip KB for image requests in v1** — clean but removes parity with the document/audio flows. Rejected; the describe-then-retrieve approach is cheap enough.
  - **Inline the describe step into the main vision prompt (one call, two jobs)** — saves one AI call, but then you can't query Pinecone before the main reasoning call starts, so any retrieved context arrives too late. Rejected.

## R4. Timeout budget

- **Decision**: Reuse the existing `settings.assessment.request_timeout_seconds` (default 180s) and wrap `run_image_assessment()` in `asyncio.wait_for(..., timeout=timeout_seconds)` — identical to `run_reasoning_assessment()`. Exceeding the budget raises the existing `PipelineTimeoutError` (HTTP 504).
- **Rationale**: Matches spec Clarification Q5 exactly. Reuses the same error type the frontend already handles for the text pipeline — no image-specific error handling required on the client side.
- **Alternatives considered**:
  - Image-specific timeout (e.g., 60s because vision calls are slower per token but have smaller total payloads) — rejected in Q5.

## R5. Supported image formats and max size

- **Decision**: Support **PNG, JPG, JPEG, WebP, GIF** (FR-004) with a max size of **20 MB** per file (FR-006). These already exist as `SUPPORTED_IMAGE_EXTENSIONS` and `MAX_IMAGE_SIZE` in `app/assessment/ocr.py` (and `router.py`).
- **Rationale**:
  - These are the formats the existing OCR path already validates and the vision API accepts.
  - 20 MB is below GPT-4o's vision input ceiling with headroom for the encoded base64 overhead (~33% expansion). Uploads that would encode past the provider's limit are pre-rejected locally.
- **Implementation note**: Promote `SUPPORTED_IMAGE_EXTENSIONS` and `MAX_IMAGE_SIZE` to be importable from either `app/assessment/ocr.py` or the new `app/assessment/image.py`; do not duplicate. Prefer keeping the constants colocated with the new `image.py` module and have `ocr.py` import from there (since images are a more general concern than OCR).
- **Alternatives considered**:
  - Broader format set (HEIC, AVIF, BMP, TIFF) — requires client-side or server-side format conversion; not worth the complexity for v1.
  - Lower cap (10 MB) — matches the document cap, but cuts off legitimate photos from phone cameras that land in the 10–20 MB range. Rejected.

## R6. Preventing image bytes from leaking into Logfire AND LangSmith traces

- **Decision**: The spec Clarification Q3 ("exclude image bytes and base64 from logs and traces") is read literally — it covers **both** Logfire and LangSmith. The implementation must keep image payloads out of both surfaces.
  - **Logfire**: Build the `HumanMessage` content at the last moment inside `vision_reasoning_stage()`. Never pass the message, the bytes, or the base64 string as a span attribute or log argument. Spans for the image flow record only: `filename`, `size_bytes`, `mime`, `scorecard_id`, `use_knowledge_base`, `knowledge_base_hit`, `latency_ms`, `outcome`.
  - **LangSmith**: The two image-bearing LLM calls — `vision_reasoning_stage` and `image_describe_for_kb` — MUST suppress LangChain's auto-trace for that specific call by passing `config={"callbacks": []}` to `ainvoke(...)`. This disables both LangChain's baseline tracer and any `@traceable` wrapping for that invocation, so the image payload never reaches LangSmith. All other pipeline stages that receive **text only** (the structuring stage; any KB-side retrieval after the describe step) remain traceable to LangSmith normally.
  - Do **not** decorate `vision_reasoning_stage` or `image_describe_for_kb` with `@traceable` — that decorator wraps the function-level inputs, which include the image bytes. Decorate only `run_image_assessment` and `structuring_stage` at the chain level.
  - Add a regression test: assert that, across one end-to-end run of `run_image_assessment`, no Logfire span attribute and no LangSmith-visible run input contains the image bytes, the base64 string, or the `data:image/` prefix.
- **Rationale**:
  - Literal reading of the Clarification — "logs and traces" — captures both systems. LangSmith is a trace system even though it is access-controlled; interpreting "traces" to mean only Logfire would be a silent narrowing of the Clarification.
  - `config={"callbacks": []}` is the idiomatic LangChain mechanism for per-invocation trace opt-out. Global switches (`LANGCHAIN_HIDE_INPUTS`, disabling LangSmith project-wide) are too coarse and would starve the text-flow of observability.
  - Keeping the structuring stage traceable preserves the diagnostics value of LangSmith for 90%+ of the pipeline; only the image-bearing calls go dark.
- **Alternatives considered**:
  - Let LangSmith capture the image payload (the original v1 draft of this decision) — rejected on re-read of the Clarification; narrowing "traces" to Logfire only was an interpretation choice not backed by the spec text.
  - Generic Logfire redactor / processor scrubbing base64-looking payloads — more complex and risks over-scrubbing legitimate content. Rejected for v1.
  - Disable Logfire AND LangSmith tracing for the entire image pipeline — loses valuable observability on the structuring stage. Rejected.
  - Use `LANGCHAIN_HIDE_INPUTS=true` (process-wide) — rejected; would also hide text-flow inputs and break existing LangSmith diagnostics.

## R7. Request contract — multipart vs JSON

- **Decision**: Use **`multipart/form-data`** — fields: `file: UploadFile` (the image), `scorecard: str` (JSON-serialised scorecard), `use_knowledge_base: bool = False` (form field). Mirrors the existing `POST /api/v1/assessments/document` and `POST /api/v1/assessments/audio` endpoints exactly.
- **Rationale**:
  - Consistency with the existing file-bearing endpoints makes the frontend integration trivial (reuses its existing multipart upload helper).
  - Avoids forcing clients to base64-encode the image into a JSON body (larger payload, worse DX).
- **Alternatives considered**:
  - JSON body with base64-encoded image — inconsistent with the other file endpoints. Rejected.

## R8. Content-type taxonomy value

- **Decision**: Add **`ContentType.image = "image"`** to the existing `ContentType` enum in `app/assessment/schemas.py`.
- **Rationale**: Matches Clarification Q4. The `AssessmentResult.content_type` field on the response is a Pydantic-validated enum, so adding a new value is additive and non-breaking for existing clients (they never sent `image` and won't receive it unless they call the new endpoint).
- **Implementation note**: The prompts in `services.py` / `image.py` include the content-type in their framing so the reasoning model is told "this is an image being evaluated." Verify the string `"image"` renders correctly in the prompt templates (no special-casing needed).

## R9. Retry discipline for the vision stage

- **Decision**: Apply the same retry count as the text-reasoning stage — `settings.assessment.reasoning_retries` (default 1 → 2 total attempts). On exhaustion, apply `failure_policy`:
  - `fallback` (default) → surface an `AIProviderError` (HTTP 502) with a user-friendly message ("Image could not be evaluated reliably. Please retry or use a different image."). Image assessment does **not** have a legacy text-only fallback to run (no text was ever extracted in this flow by design); degrading to OCR-then-text would contradict the spec's vision-based scope.
  - `strict` → raise `ReasoningUnavailableError` (HTTP 502, unchanged). Note: the existing error class is declared in feature 003 context but is semantically modality-agnostic; its docstring should be amended on the implementation PR to note it also covers the image pipeline.
- **Rationale**: Matches the discipline of the text flow without inventing a new policy. The difference is that the image path cannot "fall back" to a non-vision path because doing so would silently downgrade to a different modality (contradicting Q1). A vision-stage failure after retries is an upstream provider problem (the model cannot produce a usable response), not a caller input error — so `AIProviderError` (502) is the semantically correct choice, not `ValidationError` (422).
- **Alternatives considered**:
  - `ValidationError` (422) on fallback — would suggest the caller's input was wrong, but the input passed validation; the failure is upstream. Rejected.
  - Fall back to OCR-then-text assessment when vision fails — silently swaps modalities; rejected per Q1.
  - Infinite / higher retry count — unbounded cost on genuinely bad images (safety rejections, corrupt files). Rejected.

## R10. Image-decoding / corruption validation

- **Decision**: Rely on the vision model's own ability to reject corrupt/truncated images. We do **not** add a local Pillow-based decode step purely for validation.
- **Rationale**:
  - Adds a dependency (Pillow) solely for up-front validation that the vision provider already handles.
  - Corrupt-image errors from the provider are surfaced as `AIProviderError` (502) with a clear message. The spec edge case "the image is corrupt" is satisfied as long as the error is actionable to the caller.
- **Alternatives considered**:
  - Pre-decode with Pillow to return 422 locally — cleaner UX (validation vs upstream error), but adds a dependency and local CPU cost for every request. Reject for v1; revisit if support requests accumulate.

---

## Summary — all decisions resolved

| # | Topic | Decision |
|---|---|---|
| R1 | Stage-1 model | `gpt-4o` via `langchain-openai` |
| R2 | Pipeline shape | Two-stage; reuse `structuring_stage` and `_compose_result` unchanged |
| R3 | KB retrieval | Describe-then-retrieve with `gpt-4o-mini`, gated by `use_knowledge_base` |
| R4 | Timeout | Reuse `request_timeout_seconds` (180s) + `PipelineTimeoutError` |
| R5 | Formats & size | {PNG, JPG, JPEG, WebP, GIF}; 20 MB max (consolidate constants into `image.py`) |
| R6 | Trace redaction | Keep image bytes out of BOTH Logfire AND LangSmith; suppress LangChain callbacks on image-bearing LLM calls via `config={"callbacks": []}` |
| R7 | Request shape | `multipart/form-data` — match document/audio endpoints |
| R8 | Content type | Add `ContentType.image` (additive) |
| R9 | Retry policy | Reuse `reasoning_retries`; no OCR fallback (modality-preserving) |
| R10 | Image validation | Trust the provider; no local Pillow decode |

No NEEDS CLARIFICATION remain. Proceed to Phase 1 design artifacts.
