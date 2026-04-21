# Implementation Plan: Image Assessment Endpoint

**Branch**: `004-image-assessment` | **Date**: 2026-04-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-image-assessment/spec.md`

## Summary

Add a new `POST /api/v1/assessments/image` endpoint that accepts a single image file + scorecard (multipart form) and returns an `AssessmentResult` with the same shape as the existing text, document, and audio endpoints.

The processing path reuses the feature-003 two-stage pattern but swaps the reasoning stage for a **vision-capable reasoning stage**:

1. **Vision reasoning stage** — GPT-4o (vision-capable) receives the image + scorecard and emits per-question rationale in the existing `### Q: <id>` format. Replaces `reasoning_stage()` only; produces the same `AggregatedReasoning` artifact the rest of the pipeline already consumes. DeepSeek R1 is not used here because it does not support image inputs.
2. **Structuring stage** — unchanged. The existing `structuring_stage()` serialises rationale → `AIScoreOutput` at low temperature.
3. **Result composition** — unchanged. `_compose_result()` merges the structured output with rationale into the existing `AssessmentResult`.

Knowledge-base retrieval for images is gated by `use_knowledge_base`: when set, a cheap vision-based image-description call runs first to produce a text query, that query hits Pinecone via the existing `get_rag_context`, and the retrieved context is injected into the vision-reasoning prompt. When off, no pre-describe call is made.

Image bytes are deliberately excluded from Logfire spans and LangSmith traces (per Clarification 3) — spans record only metadata (filename, mime, size, latency, outcome).

A new `ContentType.image` enum value is introduced so the downstream pipeline frames the content as a visual artifact (per Clarification 4).

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: FastAPI, LangChain (`langchain-openai` for vision via `ChatOpenAI`, `langchain-deepseek` unchanged), Pydantic v2, Logfire, LangSmith, Pinecone SDK, `python-multipart` for image upload (already installed)
**Storage**: N/A — stateless feature. Pinecone reused read-only for optional RAG context (feature 002).
**Testing**: pytest + pytest-asyncio + httpx.AsyncClient; mock both the vision `ChatOpenAI` and the structuring LLM; no DB fixtures required. Small fixture images (tiny PNG/JPEG bytes) for validation tests.
**Target Platform**: Linux server (FastAPI async backend)
**Project Type**: web-service (FastAPI, single-project layout per constitution)
**Performance Goals**: End-to-end ≤ 30s for images up to 20 MB with ≤ 5-criterion scorecard (SC-001); ≥ 10 concurrent requests without degradation (SC-006); same 180s hard per-request ceiling as other assessments (FR-014)
**Constraints**: Exactly one image per request (FR-012); supported formats {PNG, JPG, JPEG, WebP, GIF} (FR-004); 20 MB max (FR-006); vision model only (FR-002) — OCR-only flow remains in `/assessments/document`; logs exclude image bytes / base64 (FR-009); error taxonomy reuses `ValidationError / AIProviderError / AIRateLimitError / PipelineTimeoutError` (FR-008, FR-014)
**Scale/Scope**: One new route (`POST /api/v1/assessments/image`); one new module file (`app/assessment/image.py`); one enum value (`ContentType.image`); one new orchestrator (`run_image_assessment`); no schema-breaking changes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applies? | How this plan complies |
|---|---|---|
| I. Module-First Architecture | Yes | All changes land inside the existing `app/assessment/` module. Vision-specific code goes into a new `app/assessment/image.py` (mirroring the `ocr.py` / `transcription.py` pattern already used for other file modalities). `router.py` gains one route; `schemas.py` gains one enum value; `services.py` gains one orchestrator function that reuses `structuring_stage` and `_compose_result`. Cross-module imports stay within existing public interfaces (`app/core/ai_provider.py`, `app/core/config.py`, `app/knowledge_base/services.py`). No circular dependencies. |
| II. Code Quality | Yes | Full type hints and return types on all new functions; Pydantic models at API boundaries; async/await end-to-end (no sync I/O on the request path); router stays transport-only (parse form, validate file, delegate to service); no business logic in router; no raw SQL (stateless feature); dependencies injected via `Depends()` (reuse existing `verify_api_key`); no dead code. |
| III. Testing Standards | Yes | Unit tests under `tests/assessment/test_services.py`: vision-reasoning happy path, vision-reasoning retry, image orchestrator timeout path, image orchestrator fallback path (mirroring text-flow fallback). Integration tests under `tests/assessment/test_router.py`: happy path with mocked LangChain vision model; error paths for missing filename, unsupported extension, empty file, oversized file, invalid scorecard JSON, vision-provider rate limit, vision-provider unavailability. All tests async via `pytest-asyncio`; use the existing `TestClient`/httpx setup in `conftest.py`. |
| IV. API Consistency | Yes | New route follows existing URL convention (`/api/v1/assessments/image` — plural resource, modality suffix like `/document`, `/audio`). Response is the existing `AssessmentResult` Pydantic model — no new response shape. Error bodies use the existing `{"detail": "..."}` shape via the existing exception classes. Validation happens in Pydantic + a small file-validation helper reused from the document/audio endpoints; no manual checks in services. Authentication stays on the `APIRouter(dependencies=[Depends(verify_api_key)])` layer. |
| V. Performance Requirements | Yes | Async LangChain / OpenAI calls (`ainvoke`) throughout; no sync I/O on request path; pipeline is wall-clock bounded by the existing `asyncio.wait_for(timeout_seconds)` wrapper (FR-014). No DB access — no pagination or N+1 concerns. Pinecone retrieval call uses the existing async path from feature 002. No long-running blocking work in the handler — at most 2 AI calls for assessment + 1 optional describe call for KB retrieval. |

**Result**: PASS — no violations. `Complexity Tracking` table stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/004-image-assessment/
├── plan.md              # This file
├── research.md          # Phase 0 output — vision model choice, image-in-trace redaction, KB retrieval approach, format/size decisions
├── data-model.md        # Phase 1 output — image request/response shape; ContentType.image; internal artifact reuse
├── quickstart.md        # Phase 1 output — local run + smoke test
├── contracts/
│   └── assessments-image-post.md   # POST /api/v1/assessments/image multipart contract
├── checklists/
│   └── requirements.md  # Already produced by /speckit.specify
└── tasks.md             # Produced by /speckit.tasks
```

### Source Code (repository root)

```text
app/
├── assessment/
│   ├── __init__.py
│   ├── router.py            # EXTEND — add POST /api/v1/assessments/image; reuse _run_with_error_handling; share file-validation helper with document/audio endpoints where possible
│   ├── schemas.py           # EXTEND — add ContentType.image enum value; optionally add a tiny internal ImageAssessmentInput helper (in-module, not exported)
│   ├── services.py          # EXTEND — add run_image_assessment() orchestrator that swaps reasoning_stage for vision_reasoning_stage, reuses structuring_stage + _compose_result; reuse the 180s wait_for wrapper
│   ├── image.py             # NEW — vision_reasoning_stage(), image_describe_for_kb() helper, SUPPORTED_IMAGE_EXTENSIONS + MAX_IMAGE_SIZE (already defined in ocr.py — move or re-export)
│   ├── ocr.py               # UNCHANGED (OCR-only flow remains available via /assessments/document)
│   └── transcription.py     # UNCHANGED
├── core/
│   ├── ai_provider.py       # EXTEND — add get_vision_reasoning_llm() returning ChatOpenAI(model="gpt-4o") (vision-capable); optional settings-driven model name. Keep get_openai_client() unchanged (used by OCR/transcription).
│   ├── config.py            # EXTEND — add AssessmentConfig.vision_reasoning_model (default "gpt-4o") and AssessmentConfig.image_kb_describe_model (default "gpt-4o-mini") for the optional describe-then-retrieve step
│   └── errors.py            # UNCHANGED — existing error taxonomy is sufficient
└── main.py                  # UNCHANGED

tests/
└── assessment/
    ├── __init__.py
    ├── test_services.py     # EXTEND — vision_reasoning_stage unit tests; run_image_assessment happy/timeout/fallback tests with mocked LangChain vision model
    └── test_router.py       # EXTEND — POST /api/v1/assessments/image: happy path, missing filename, unsupported extension, empty file, oversized file, invalid scorecard JSON, AI rate-limit, AI unavailability
```

**Structure Decision**: Single-project layout (existing kynesis repo). No new modules. All feature work is additive within `app/assessment/` and `app/core/`. The new `image.py` file mirrors the per-modality file pattern already established by `ocr.py` and `transcription.py` (Constitution Principle I). The public router contract grows by exactly one new route; no existing routes or schemas change shape (only a new `ContentType` enum value is added, which is additive for the Pydantic model).

## Complexity Tracking

> No entries — Constitution Check passed without violations.
