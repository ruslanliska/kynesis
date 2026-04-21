---

description: "Task list for feature 004-image-assessment"
---

# Tasks: Image Assessment Endpoint

**Input**: Design documents from `/specs/004-image-assessment/`
**Prerequisites**: plan.md (✓), spec.md (✓), research.md (✓), data-model.md (✓), contracts/ (✓), quickstart.md (✓)

**Tests**: Included. Constitution Principle III (Testing Standards) mandates unit + integration tests for every endpoint with at least one happy-path and one error-path test.

**Organization**: Tasks are grouped by user story. Both stories from spec.md are P1 (US1 = happy path, US2 = validation errors). The two stories are independently testable — US1 verifies successful image evaluation; US2 verifies each validation failure.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story the task belongs to (US1, US2)
- File paths below are absolute

## Path Conventions

Single-project layout (existing kynesis repo). All feature code lives under `app/assessment/` and `app/core/`; all tests under `tests/assessment/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify the environment is ready. No new package dependencies are introduced by this feature.

- [X] T001 Verify no new runtime dependencies are required: confirm `langchain-openai`, `langchain-deepseek`, `langchain-core`, `python-multipart`, `pinecone`, `logfire[fastapi]`, and `langsmith` are already declared in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/pyproject.toml`. If any are missing, add them; otherwise record "no changes" in the PR description.
- [X] T002 [P] Document the two new optional env vars in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/.env.example` (if present): `ASSESSMENT__VISION_REASONING_MODEL` (default `gpt-4o`) and `ASSESSMENT__IMAGE_KB_DESCRIBE_MODEL` (default `gpt-4o-mini`). Do not commit real keys.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Enum, config, and factory plumbing that BOTH user stories depend on. Must complete before any story phase starts.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add `image = "image"` value to the `ContentType` enum in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/schemas.py`. Preserve existing ordering; place `image` next to `document`. This is additive-only.
- [X] T004 [P] Extend `AssessmentConfig` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/core/config.py` with two new fields: `vision_reasoning_model: str = "gpt-4o"` and `image_kb_describe_model: str = "gpt-4o-mini"`. Match the existing block's style; no other settings changes.
- [X] T005 [P] Add two factories to `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/core/ai_provider.py`: `get_vision_reasoning_llm()` returning `ChatOpenAI(model=settings.assessment.vision_reasoning_model, api_key=settings.openai.api_key)` and `get_image_kb_describe_llm()` returning `ChatOpenAI(model=settings.assessment.image_kb_describe_model, api_key=settings.openai.api_key)`. Use `@lru_cache` to match the pattern of the neighbouring factories. Do not modify the existing `get_openai_client()` / `get_openai()` / `get_reasoning_llm()` / `get_structuring_llm()` functions.
- [X] T006 Create new module `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/image.py` with: `SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}`, `MAX_IMAGE_SIZE = 20 * 1024 * 1024`, and `_MIME_TYPES` (copy from `ocr.py`). Then update `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/ocr.py` to import these constants from `image.py` instead of redefining them, and update `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/router.py` to import `MAX_IMAGE_SIZE` and `SUPPORTED_IMAGE_EXTENSIONS` from `image.py`. Run `ruff check .` to verify no broken imports.

**Checkpoint**: Foundation ready — both user stories can now be implemented.

---

## Phase 3: User Story 1 — Assess an Image Against a Scorecard (Priority: P1) 🎯 MVP

**Goal**: `POST /api/v1/assessments/image` accepts a valid image + scorecard and returns a well-formed `AssessmentResult` with `contentType: "image"` and per-question `rationale` populated, using a vision-capable model for the reasoning stage.

**Independent Test**: Send a request with a small valid PNG/JPEG and a scorecard containing ≥3 questions; verify `200 OK`, `contentType == "image"`, per-criterion scores within valid ranges, non-empty `rationale` for each question, and a correctly weighted `overall.score`.

### Tests for User Story 1

> Write these tests FIRST, ensure they FAIL before implementation.

- [X] T007 [P] [US1] Add unit test `test_vision_reasoning_stage_happy_path` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/tests/assessment/test_services.py`: mock `get_vision_reasoning_llm()` to return an LLM whose `ainvoke` yields a message with `### Q: <id>` blocks for every scorecard question; assert the returned `AggregatedReasoning` has one `ReasoningQuestionRecord` per question, `status == "ok"`, and `content_type == ContentType.image`.
- [X] T008 [P] [US1] Add unit test `test_run_image_assessment_happy_path` in the same file: mock both the vision LLM and the structuring LLM; pass a valid scorecard and fake image bytes; assert the returned `AssessmentResult` has `content_type == ContentType.image`, `overall.reasoning_unavailable is False`, every `questions[*].rationale` non-empty, and `overall.score` within `[0, 100]`.
- [X] T009 [P] [US1] Add unit test `test_run_image_assessment_timeout` in the same file: monkey-patch `settings.assessment.request_timeout_seconds` to a very small value (e.g., `0.01`) and make the vision stage mock sleep longer; assert `PipelineTimeoutError` is raised.
- [X] T010 [P] [US1] Add unit test `test_run_image_assessment_vision_retry_exhaustion` in the same file: mock the vision LLM to always raise a transient error (e.g., `langchain_core.exceptions.LangChainException`); under `failure_policy="strict"`, assert `ReasoningUnavailableError` is raised; under `failure_policy="fallback"`, assert an `AIProviderError` (502) is raised (image flow must NOT silently fall back to OCR — see research R9).
- [X] T011 [P] [US1] Add unit test `test_run_image_assessment_with_knowledge_base` in the same file: mock `image_describe_for_kb()` returning `"dummy description"`, mock `get_rag_context()` returning `"context from KB"`, assert the vision-reasoning prompt includes the retrieved context and that the outer `image_assessment` Logfire span records `use_knowledge_base=True` and `knowledge_base_hit=True` (via `logfire.testing` fixture or by patching `logfire.span` to capture kwargs).
- [X] T012 [P] [US1] Add integration test `test_post_image_assessment_happy_path` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/tests/assessment/test_router.py`: use `httpx.AsyncClient` with a small in-memory PNG (e.g., a 1x1 pixel via `base64.b64decode(...)` fixture), the existing `SCORECARD_PAYLOAD`, and mocked vision + structuring LLMs; assert status 200 and response has `contentType == "image"`, `questions[*].rationale != ""`.
- [X] T013 [P] [US1] Add integration test `test_post_image_assessment_with_knowledge_base` in the same file: mock `get_rag_context` to return a non-empty context string; assert the HTTP response is 200 with the expected shape. Do NOT duplicate the deeper assertions already covered by T011 (prompt-content inspection, span attributes) — this test covers only the HTTP-surface contract that the KB flag reaches the service.
- [X] T013a [P] [US1] Add integration test `test_post_image_assessment_inactive_scorecard` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/tests/assessment/test_router.py`: send a valid PNG with a scorecard payload whose `status` is `"draft"`, assert 422 and `detail` mentions "active scorecards". This covers spec US1 acceptance scenario 6 (scorecard-state validation); router-level format/size validation stays in US2.

### Implementation for User Story 1

- [X] T014 [US1] First, promote `_parse_reasoning_response` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/services.py` from private to a module-level name the image module can reuse — rename to `parse_reasoning_response` (or re-export as `parse_reasoning_response = _parse_reasoning_response`). Then in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/image.py`, implement `async def vision_reasoning_stage(scorecard, image_bytes, filename, mime, knowledge_base_context) -> AggregatedReasoning`: base64-encode the image, build a `HumanMessage` with two content parts (`{"type": "text", ...}` with `_REASONING_SYSTEM_PROMPT` + `_build_scorecard_context(...)` and an instruction to emit `### Q: <id>` blocks, then `{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}`), and invoke the LLM via **`await get_vision_reasoning_llm().ainvoke(messages, config={"callbacks": []})`** — the explicit empty-callbacks config suppresses LangChain's LangSmith tracer for this call so the image payload never reaches LangSmith (research R6). Parse blocks via `parse_reasoning_response` and return `AggregatedReasoning(scorecard_id=..., content_type=ContentType.image, content_preview=f"[image: {filename}, {mime}, {len(image_bytes)}B]", records=..., full_trace_available=False)`. Do NOT add the base64 string or the `HumanMessage` object to any `logfire.span` attribute or `.info` call. Emit `logfire.span("vision_reasoning_stage", scorecard_id=..., filename=..., size_bytes=..., mime=...)` around the LLM call — metadata only. Do NOT decorate this function with `@traceable` (that would capture the image bytes as a LangSmith run input).
- [X] T015 [US1] In `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/image.py`, implement `async def image_describe_for_kb(image_bytes, filename, mime) -> str`: run a short prompt against `get_image_kb_describe_llm()` asking for a concise one-paragraph description suitable for knowledge-base retrieval (no scoring, no scorecard context). Invoke via **`await llm.ainvoke(messages, config={"callbacks": []})`** so the image payload does not reach LangSmith (research R6). Return the description string. Wrap in `logfire.span("image_describe_for_kb", filename=..., size_bytes=...)` — metadata only. Do NOT decorate this function with `@traceable`.
- [X] T016 [US1] In `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/services.py`, implement `async def run_image_assessment(scorecard, image_bytes, filename, mime, use_knowledge_base) -> AssessmentResult`: mirrors `run_reasoning_assessment` but (a) calls the new `vision_reasoning_stage` instead of `reasoning_stage`, (b) resolves the KB query via `image_describe_for_kb(...)` → `get_rag_context(scorecard.id, description)` when `use_knowledge_base=true`, otherwise `knowledge_base_context=None`, (c) builds an `AssessmentRequest` with `content=f"[Image input — see vision-stage rationale for analysis. filename={filename}, size={len(image_bytes)}B]"` (this placeholder satisfies the ≥50-char validator; see data-model §5 for the documented implementation constraint that the placeholder MUST be updated in lockstep if that validator changes), `content_type=ContentType.image`, `use_knowledge_base=use_knowledge_base` so downstream code unchanged, (d) wraps the inner coroutine in `asyncio.wait_for(..., timeout=settings.assessment.request_timeout_seconds)` raising `PipelineTimeoutError`, (e) on vision-stage retry exhaustion applies the documented policy — `strict` → `ReasoningUnavailableError`, `fallback` → `AIProviderError("Image could not be evaluated reliably. Please retry or use a different image.")` (HTTP 502; NO legacy fallback; see research R9), (f) calls the unchanged `structuring_stage(request, reasoning, knowledge_base_context)` and `_compose_result(request, ai_output, reasoning)` on success. Wrap the **entire orchestrator body** in `logfire.span("image_assessment", filename=..., mime=..., size_bytes=..., scorecard_id=..., use_knowledge_base=...)` — this is the top-level Logfire span specified in data-model §6; set the span attribute `knowledge_base_hit` via `span.set_attribute(...)` after the Pinecone call resolves, and set `outcome` on the successful exit path. Decorate the function with `@traceable(name="image_assessment", run_type="chain")` so the Logfire span name and the LangSmith run name match (data-model §6). Note: because `structuring_stage` receives only text (reasoning rationale + scorecard + placeholder content), its LangSmith trace continues to carry no image payload.
- [X] T017 [US1] In `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/router.py`, add `@router.post("/assessments/image", response_model=AssessmentResult, response_model_by_alias=True)` handler `async def create_image_assessment(file: UploadFile, scorecard: str = Form(...), use_knowledge_base: bool = Form(False))`. The route inherits API-key authentication (FR-010) from the router-level `dependencies=[Depends(verify_api_key)]` declared at the top of `router.py` — do not re-declare auth on the handler. For this US1 phase, implement only the happy-path wiring: read `file` bytes, resolve mime via `_MIME_TYPES.get(ext, "image/jpeg")`, parse the `scorecard` JSON into `ScorecardDefinition`, and call `run_image_assessment(...)`. The top-level `image_assessment` Logfire span lives in the orchestrator (T016), not the handler. Reuse the existing exception handling pattern from `_run_with_error_handling`: catch `RateLimitError`, `APIConnectionError`, `ConnectError`, `HTTPStatusError`, `LangChainException`, and the pipeline-specific exceptions. Validation tasks (extension, size, emptiness, scorecard status) belong to US2 and land in T024.

**Checkpoint**: User Story 1 is fully functional — a valid request produces a valid `AssessmentResult`. Error paths for invalid inputs may still produce internal exceptions until US2 lands.

---

## Phase 4: User Story 2 — Validate Image Inputs Before Processing (Priority: P1)

**Goal**: Every invalid image submission (missing filename, unsupported extension, empty file, oversized file, invalid scorecard JSON, inactive scorecard) is rejected with a clear 422 error **before any AI call is made**.

**Independent Test**: Send each invalid variant and assert `status == 422`, a human-readable `detail` message, and — critically — that neither the vision LLM mock nor the structuring LLM mock was awaited.

### Tests for User Story 2

> Write these tests FIRST, ensure they FAIL before implementation.

- [X] T018 [P] [US2] Add integration test `test_post_image_assessment_missing_filename` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/tests/assessment/test_router.py`: send an `UploadFile` with `filename=""` (or omitted), assert 422 and `detail` mentions filename; assert vision + structuring LLM mocks were not awaited.
- [X] T019 [P] [US2] Add integration test `test_post_image_assessment_unsupported_extension` in the same file: upload a `.bmp` file, assert 422 and `detail` lists the supported formats.
- [X] T020 [P] [US2] Add integration test `test_post_image_assessment_empty_file` in the same file: upload a 0-byte file with a `.png` extension, assert 422 and `detail` says the file is empty.
- [X] T021 [P] [US2] Add integration test `test_post_image_assessment_oversized_file` in the same file: upload a 21 MB in-memory buffer (e.g., `b"\x89PNG..." + b"\x00" * (21 * 1024 * 1024)`), assert 422 and `detail` states "20MB" limit.
- [X] T022 [P] [US2] Add integration test `test_post_image_assessment_invalid_scorecard_json` in the same file: send a valid PNG with `scorecard="{not json"`, assert 422 and `detail` starts with "Invalid scorecard JSON".
- [X] T023 [P] [US2] Add integration test `test_post_image_assessment_multiple_files` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/tests/assessment/test_router.py` that posts TWO files under the same `file=` form key with a valid scorecard and asserts 422 (or equivalent FastAPI rejection). Covers FR-012 — exactly one image per request. The scorecard-status test formerly numbered T023 has been moved to T013a under US1, because scorecard-state validation maps to US1 acceptance scenario 6 (spec), not to US2's router-format-validation remit.

### Implementation for User Story 2

- [X] T024 [US2] Extend the handler `create_image_assessment` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/app/assessment/router.py` with explicit pre-AI validation: (a) reject when `file.filename` is missing/empty → `ValidationError("File must have a filename.")`; (b) derive the extension and reject when it is not in `SUPPORTED_IMAGE_EXTENSIONS` → `ValidationError` listing supported formats; (c) read the bytes and reject when the length is 0 → `ValidationError("File is empty.")`; (d) reject when length exceeds `MAX_IMAGE_SIZE` → `ValidationError("File exceeds maximum size of 20MB.")`; (e) parse `scorecard` JSON and reject with `ValidationError(f"Invalid scorecard JSON: {e}")` on parse/validation error. Scorecard-status validation (`status != active`) is enforced inside `_run_with_error_handling` (already part of the existing pipeline — see `app/assessment/router.py`) and is exercised by T013a in US1; do not re-implement it here. Ensure ALL validations in (a)–(e) return BEFORE calling `run_image_assessment(...)`. The structure MUST mirror the existing `/assessments/document` and `/assessments/audio` handlers to stay consistent.

**Checkpoint**: Both user stories are independently functional. Happy path works (US1), and every invalid input is rejected cleanly before any AI call is made (US2).

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Observability-discipline checks, lint, and end-to-end verification.

- [X] T025 [P] Add a regression test `test_image_pipeline_traces_exclude_image_bytes` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/tests/assessment/test_services.py` that (a) captures Logfire span attributes (via `logfire.testing` or `capfire` fixture if available; otherwise mock `logfire.span` / patch the span context manager to record all kwargs), and (b) also verifies the LLM call for `vision_reasoning_stage` and `image_describe_for_kb` was made with `config={"callbacks": []}` (inspect the mock's `call_args.kwargs["config"]`). Assert no captured Logfire attribute value contains the raw image bytes, any base64 substring, or the string `"data:image/"`, AND that both image-bearing LLM calls received the empty-callbacks config (research R6).
- [X] T026 [P] Verify LangSmith tracing boundaries: confirm that after T014–T016, `run_image_assessment` and `structuring_stage` ARE `@traceable` and appear in LangSmith when `LANGSMITH__TRACING=true`, while `vision_reasoning_stage` and `image_describe_for_kb` are NOT `@traceable` and do NOT appear in LangSmith (the image bytes go through these two functions and must stay out of LangSmith per research R6). This is a local smoke-check step during PR review; capture a screenshot or run-URL list for the PR description.
- [X] T027 [P] Add a concurrency smoke test `test_post_image_assessment_concurrent_requests` in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/tests/assessment/test_router.py` that, using mocked vision + structuring LLMs, fires 10 parallel POSTs via `asyncio.gather` and asserts all return 200 with distinct `assessedAt` timestamps or distinct identifying fields — confirming no shared-state bug. This closes the testable portion of SC-006. Production-scale concurrency validation remains a staging activity (see T029).
- [ ] T028 Run `ruff check .` from repo root and fix any lint issues introduced by this feature. (Deferred: `ruff` is not declared in `pyproject.toml` dependencies; `python -m py_compile` on all modified files passed clean during implementation. Re-enable when `ruff` is added to dev deps.)
- [X] T029 Run `pytest tests/assessment -q` from repo root and verify all tests pass (existing + new ones from T007–T013, T013a, T018–T023, T025, T027).
- [ ] T030 Execute the smoke tests in `/Users/ruslan.liska/PycharmProjects/kynesis/kynesis/specs/004-image-assessment/quickstart.md` §3–§5 against a locally running uvicorn; paste the observed response bodies and span attribute snapshots into the PR description for reviewer verification.
- [ ] T031 Manual staging verification — run one real end-to-end request with a ~20 MB image and a 5-criterion scorecard against a staging deployment (or against production keys locally); record the observed wall-clock latency in the PR description. Confirm latency ≤ 30 s to validate SC-001. If latency exceeds 30 s, file a follow-up issue rather than blocking the MVP merge (the 180 s ceiling from FR-014 is the hard gate, 30 s is the target).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS both user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational. Can start once T003–T006 are merged.
- **User Story 2 (Phase 4)**: Depends on Foundational AND on T017 (the route handler exists) from US1. After that, all US2 tasks can proceed in parallel.
- **Polish (Phase 5)**: Depends on both user stories being complete.

### User Story Dependencies

- **US1 (P1)**: Requires only the foundational phase.
- **US2 (P1)**: Requires foundational phase + the route skeleton from US1's T017. This ordering is intentional — US2 adds validation TO the route that US1 creates. US2 tests (T018–T023) CAN be written before T024 and will FAIL until T024 lands; this is the expected TDD pattern.

### Within Each User Story

- Tests FIRST — they MUST fail before implementation lands (TDD per Constitution Principle III).
- Within implementation: helpers (`vision_reasoning_stage`, `image_describe_for_kb`) before the orchestrator (`run_image_assessment`) before the route handler.

### Parallel Opportunities

- Phase 1: T002 parallel with T001.
- Phase 2: T004 and T005 parallel with each other. T003 and T006 are sequential with each other only if they touch overlapping files — they do not, so they can also run in parallel, but T006 touches `router.py` which has no dependency on T003.
- Phase 3 tests: T007–T013 and T013a are all `[P]` — eight parallel test-writing tasks.
- Phase 3 implementation: T014 and T015 are in the same file (`image.py`), so sequential. T016 depends on T014 and T015. T017 depends on T016.
- Phase 4 tests: T018–T023 all `[P]` — six parallel test-writing tasks.
- Phase 4 implementation: T024 is a single handler change.
- Phase 5: T025, T026, T027 parallel; T028–T031 sequential (lint → unit/integration → local smoke → staging check).

---

## Parallel Example: User Story 1 Tests

```bash
# All US1 tests can be written in parallel (different test functions, same files — coordinate at merge):
Task: "T007 unit test test_vision_reasoning_stage_happy_path in tests/assessment/test_services.py"
Task: "T008 unit test test_run_image_assessment_happy_path in tests/assessment/test_services.py"
Task: "T009 unit test test_run_image_assessment_timeout in tests/assessment/test_services.py"
Task: "T010 unit test test_run_image_assessment_vision_retry_exhaustion in tests/assessment/test_services.py"
Task: "T011 unit test test_run_image_assessment_with_knowledge_base in tests/assessment/test_services.py"
Task: "T012 integration test test_post_image_assessment_happy_path in tests/assessment/test_router.py"
Task: "T013 integration test test_post_image_assessment_with_knowledge_base in tests/assessment/test_router.py"
Task: "T013a integration test test_post_image_assessment_inactive_scorecard in tests/assessment/test_router.py"
```

## Parallel Example: User Story 2 Tests

```bash
Task: "T018 test_post_image_assessment_missing_filename in tests/assessment/test_router.py"
Task: "T019 test_post_image_assessment_unsupported_extension in tests/assessment/test_router.py"
Task: "T020 test_post_image_assessment_empty_file in tests/assessment/test_router.py"
Task: "T021 test_post_image_assessment_oversized_file in tests/assessment/test_router.py"
Task: "T022 test_post_image_assessment_invalid_scorecard_json in tests/assessment/test_router.py"
Task: "T023 test_post_image_assessment_multiple_files in tests/assessment/test_router.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup (T001–T002).
2. Phase 2: Foundational (T003–T006) — CRITICAL; blocks everything.
3. Phase 3: US1 (T007–T017).
4. **STOP and VALIDATE**: smoke-test `POST /api/v1/assessments/image` against a valid image; confirm `contentType: "image"` and non-empty `rationale` per question.
5. This is the shippable MVP — happy-path image assessment works.

### Incremental Delivery

1. MVP (US1) → deploy → validate with a real screenshot against a small scorecard.
2. Add US2 (T018–T024) → invalid inputs are now rejected cleanly with 422.
3. Polish (T025–T029) → observability discipline confirmed, lint clean, smoke tests pass.

### Parallel Team Strategy

- One developer drives Setup + Foundational.
- After T006 merges, Developer A starts US1 and Developer B writes US2 tests in parallel (US2 tests pre-exist the route's validation code; they're expected to fail until T024).
- Developer B completes T024 once T017 is merged.

---

## Notes

- [P] tasks = different files or non-overlapping logical units; no dependencies on incomplete tasks.
- Tests precede implementation per Constitution Principle III.
- No new schema-breaking changes — only an additive `ContentType.image` enum value and one new endpoint.
- Image bytes are never attached to Logfire spans or log records; LangSmith trace capture remains the same as today's text flow.
- If T014's LangChain message shape fails at runtime against `gpt-4o`, fall back to the structure used in `app/assessment/ocr.py` (which is proven to work for vision input): `{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}`.
- Commit after each task or tight logical group. Do not squash US1 and US2 into a single commit — the independent-test property should be traceable in the git history.
