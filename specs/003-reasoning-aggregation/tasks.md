---

description: "Tasks for 003-reasoning-aggregation — two-stage reasoning assessment pipeline"
---

# Tasks: Two-Stage Reasoning Assessment Pipeline

**Input**: Design documents from `/specs/003-reasoning-aggregation/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/assessments-post.md

**Tests**: INCLUDED — Constitution Principle III mandates unit + integration tests per module and per endpoint; this feature therefore ships tests as first-class tasks.

**Organization**: Tasks are grouped by user story (US1 → US2 → US3) to enable independent implementation, testing, and incremental delivery.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 mapping to spec.md user stories
- Exact file paths included per task

## Path Conventions

Single-project layout per plan.md. All paths are absolute under the repo root.

- Source: `app/assessment/`, `app/core/`
- Tests: `tests/assessment/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm existing dependencies and environment are sufficient. No new packages are added — `langchain-deepseek`, `langchain-openai`, `langsmith`, `logfire` are already in `pyproject.toml` (verified in research.md R1, R2, R6).

- [X] T001 Verify `pyproject.toml` contains `langchain-deepseek`, `langchain-openai`, `langchain-core`, `langsmith`, `logfire`, `pydantic`, `pydantic-settings` at current pinned versions; no edits expected unless a version is missing
- [X] T002 [P] Confirm `.env.example` / deployment config documents `LANGSMITH__API_KEY`, `LANGSMITH__TRACING=true`, `LANGSMITH__PROJECT=kynesis`, `DEEPSEEK__API_KEY`, `OPENAI__API_KEY` per quickstart.md §1; add any missing keys to `.env.example`
- [X] T003 [P] Run `uv run ruff check app/ tests/` to confirm baseline is clean before feature work starts

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared config, factories, error types, and internal schemas that all three user stories depend on.

**⚠️ CRITICAL**: No user-story phase may start until this phase is complete.

- [X] T004 Add `AssessmentConfig` Pydantic block to `app/core/config.py` with fields: `reasoning_model: str = "deepseek-reasoner"`, `structuring_model: str = "deepseek-chat"`, `structuring_temperature: float = 0.1`, `reasoning_retries: int = 1`, `structuring_retries: int = 3`, `request_timeout_seconds: int = 180`, `structuring_reserved_seconds: int = 15`, `failure_policy: Literal["strict", "fallback"] = "fallback"`; attach to `Settings` as `assessment: AssessmentConfig = AssessmentConfig()`; update `env_nested_delimiter="__"` env overrides already apply
- [X] T005 [P] Add new error classes to `app/core/errors.py`: `PipelineTimeoutError` (HTTP 504, detail `"Assessment pipeline timed out after {seconds}s."`), `ReasoningUnavailableError` (HTTP 502, detail `"Reasoning stage failed after retries."`, used only when `failure_policy=="strict"`), `ReasoningPayloadTooLargeError` (HTTP 413, detail `"Reasoning payload too large for the structuring model. Reduce scorecard question count or content length and retry."`, per FR-014), and `ReasoningCoverageError` (internal — caught by the orchestrator as a retryable reasoning-stage failure, never reaches the client); mirror the existing `AIProviderError` pattern
- [X] T006 [P] Add `get_reasoning_llm()` and `get_structuring_llm()` factory functions to `app/core/ai_provider.py`: `get_reasoning_llm()` returns `ChatDeepSeek(model=settings.assessment.reasoning_model, api_key=settings.deepseek.api_key)`; `get_structuring_llm()` returns `ChatDeepSeek(model=settings.assessment.structuring_model, api_key=settings.deepseek.api_key, temperature=settings.assessment.structuring_temperature)` (or `ChatOpenAI` branch when `structuring_model` starts with `gpt-`); both memoised with `@lru_cache`
- [X] T007 [P] Add internal Pydantic schemas to `app/assessment/schemas.py`: `ReasoningQuestionRecord`, `AggregatedReasoning`, `StageOutcome` per data-model.md; include the `AggregatedReasoning` coverage validator that enforces `records` cover the scorecard's question-id set exactly
- [X] T008 Rename the existing `run_assessment(...)` function in `app/assessment/services.py` to `run_legacy_assessment(...)` (mechanical rename; no behaviour change); update the single caller reference in `app/assessment/router.py::_run_with_error_handling` to the new name (temporary — it will be swapped to `run_reasoning_assessment` in T017); run `uv run pytest tests/assessment -x` to confirm nothing broke from the rename

**Checkpoint**: Foundation ready — US1, US2, and US3 phases can begin.

---

## Phase 3: User Story 1 — Deep Per-Question Reasoning Before Scoring (Priority: P1) 🎯 MVP

**Goal**: Two-stage pipeline: reasoning model produces per-question rationale, then a low-temperature structuring model serialises the reasoning into the existing `AssessmentResult` schema. Delivers US1's scoring-quality improvement.

**Independent Test**: Submit a scorecard + content to `POST /api/v1/assessments` and verify:
1. The LangSmith trace shows exactly two child LLM runs (reasoning, structuring) for the request.
2. The response is a valid `AssessmentResult` with scores, section totals, and overall score consistent with the scorecard weights.
3. The structuring-stage's output does not contradict the reasoning-stage's conclusions (verified via a spy that records both outputs and asserts score/selected-option consistency).

### Tests for User Story 1 (Constitution III — required)

> **Write tests FIRST, ensure they FAIL before implementation.**

- [X] T009 [P] [US1] Unit test `test_reasoning_stage_produces_record_per_question` in `tests/assessment/test_services.py` — mocks `get_reasoning_llm` with a stub returning a deterministic rationale per question id; asserts `AggregatedReasoning` built by `reasoning_stage()` covers every scorecard question and preserves `thinking_trace` when `reasoning_content` is on the AIMessage
- [X] T010 [P] [US1] Unit test `test_structuring_stage_does_not_re_evaluate` in `tests/assessment/test_services.py` — passes a canned `AggregatedReasoning` with specific selected-answer hints; mocks `get_structuring_llm().with_structured_output` to record the prompt and return a valid `AIScoreOutput`; asserts the prompt explicitly labels the reasoning as authoritative and that `temperature` on the underlying client is ≤ 0.2
- [X] T011 [P] [US1] Unit test `test_orchestrator_happy_path_two_stages` in `tests/assessment/test_services.py` — end-to-end through `run_reasoning_assessment()` with both stages mocked; asserts reasoning_stage is called exactly once, structuring_stage is called exactly once, and returns an `AssessmentResult` with the existing shape intact
- [X] T012 [P] [US1] Unit test `test_structuring_retries_reuse_reasoning_artifact` in `tests/assessment/test_services.py` — reasoning_stage mocked to succeed once; structuring_stage mocked to raise validation error twice then succeed; assert reasoning_stage was called exactly once while structuring_stage was called three times, and the same `AggregatedReasoning` instance was passed on every attempt
- [X] T013 [P] [US1] Integration test `test_assessments_endpoint_two_stage_success` in `tests/assessment/test_router.py` — patches `get_reasoning_llm` and `get_structuring_llm`; POSTs a valid assessment request to `/api/v1/assessments`; asserts HTTP 200 and body matches `AssessmentResult` schema with all existing fields present and correctly typed

### Implementation for User Story 1

- [X] T014 [US1] Implement `reasoning_stage(request: AssessmentRequest, knowledge_base_context: str | None) -> AggregatedReasoning` in `app/assessment/services.py` — builds the reasoning prompt (reuse `_build_scorecard_context`, which includes knowledge-base context when provided), calls `get_reasoning_llm().ainvoke(messages)`, parses per-question rationale from the response, captures `response.additional_kwargs.get("reasoning_content")` as the thinking trace, and constructs `AggregatedReasoning` with coverage validation (raises if any question has no rationale). **Reasoning-prompt output contract** (prompt MUST instruct the model to emit): for each question, a labelled block beginning with a line `### Q: <question_id>` (exact id, no paraphrasing) followed by 1–N paragraphs of analytical rationale; the parser splits on `### Q:` headers, trims, and maps each block to its question_id. If any scorecard question_id is missing from the response, coverage validation raises `ReasoningCoverageError` → caught by the orchestrator as a retryable reasoning-stage failure.
- [X] T015 [US1] Implement `structuring_stage(request: AssessmentRequest, reasoning: AggregatedReasoning, knowledge_base_context: str | None) -> AIScoreOutput` in `app/assessment/services.py` — calls `get_structuring_llm().with_structured_output(AIScoreOutput).ainvoke(messages)`, runs the existing `_validate_output(...)` check, retries up to `settings.assessment.structuring_retries` times on validation failure (append the validation error as a `HumanMessage` on each retry, reusing the same `reasoning` argument), and returns the validated `AIScoreOutput`. **Before any call**, estimate prompt token count; if it exceeds the structuring model's input budget (conservatively the provider's documented limit minus 2048 reserved for output), raise `ReasoningPayloadTooLargeError` (per FR-014, not retried). **Structuring-stage system-prompt MUST contain** these clauses verbatim or in equivalent wording: (a) "The reasoning below is authoritative prior analysis — transcribe its conclusions; do not re-evaluate, override scores, or introduce new evidence." (b) "Every `evidence` quote MUST appear verbatim in either the rationale or the source content; do not invent evidence." (c) "Selected option ids, numeric values, comments, and suggestions MUST be consistent with the rationale for their question." (d) "Temperature is low by design; prefer the reasoner's wording over paraphrase when possible." Knowledge-base context (when provided) MUST be included in the structuring prompt for evidence-validation grounding, matching the reasoning prompt.
- [X] T016 [US1] Implement `run_reasoning_assessment(request: AssessmentRequest, knowledge_base_context: str | None) -> AssessmentResult` orchestrator in `app/assessment/services.py` — runs `reasoning_stage` with up to `settings.assessment.reasoning_retries + 1` attempts, then `structuring_stage` with the reasoning artifact, then `calculate_scores(...)` (unchanged from feature 002) and returns the composed `AssessmentResult`; emits two `logfire.span` blocks (`reasoning_stage` and `structuring_stage`) plus a parent `assessment_pipeline` span; **MVP scope — no fallback, no timeout wrapping yet; both are added in US3**; reasoning-stage retry exhaustion at this phase raises a plain exception caught by the existing router error handlers
- [X] T017 [US1] Update `app/assessment/router.py::_run_with_error_handling` to call `run_reasoning_assessment(...)` instead of `run_legacy_assessment(...)`; keep the existing exception → HTTP mapping unchanged
- [X] T018 [US1] Run `uv run pytest tests/assessment -v` and confirm all Phase-3 tests pass

### Additional US1 tests — Constitution & Edge-Case Coverage (remediation)

- [X] T043 [P] [US1] Integration test `test_assessments_document_endpoint_two_stage_success` in `tests/assessment/test_router.py` — **satisfies Constitution III requirement** that each endpoint have a happy-path test; patches `get_reasoning_llm` and `get_structuring_llm`; POSTs a multipart document (small pdf/txt fixture) to `/api/v1/assessments/document`; asserts HTTP 200 and body is a valid `AssessmentResult`
- [X] T044 [P] [US1] Integration test `test_assessments_audio_endpoint_two_stage_success` in `tests/assessment/test_router.py` — **satisfies Constitution III** for the audio endpoint; patches `transcribe_audio`, `get_reasoning_llm`, `get_structuring_llm`; POSTs a small audio fixture; asserts HTTP 200 and body is a valid `AssessmentResult`
- [X] T045 [P] [US1] Integration test `test_assessments_document_endpoint_validation_error_returns_400` in `tests/assessment/test_router.py` — **error-path coverage for Constitution III**; POSTs a document with an unsupported extension; asserts HTTP 400 with `detail` mentioning supported formats
- [X] T046 [P] [US1] Integration test `test_assessments_audio_endpoint_oversize_returns_400` in `tests/assessment/test_router.py` — **error-path coverage for Constitution III**; POSTs an audio file exceeding the size limit; asserts HTTP 400
- [X] T047 [P] [US1] Unit test `test_orchestrator_preserves_hard_critical_auto_fail` in `tests/assessment/test_services.py` — mocks reasoning + structuring so a HARD CRITICAL question receives score 0; asserts returned `AssessmentResult.overall.hard_critical_failure == True`, `overall.score == 0.0`, and `overall.passed == False` (covers US1 AS4 + FR-006 + the HARD CRITICAL edge case)
- [X] T048 [P] [US1] Unit test `test_incomplete_reasoning_coverage_triggers_reasoning_retry` in `tests/assessment/test_services.py` — mocks `get_reasoning_llm` to return a response missing rationale for one question on the first attempt and a complete response on the second; asserts reasoning was invoked twice, structuring was invoked once with complete coverage (covers the "Reasoning covers a subset of questions" edge case)
- [X] T049 [P] [US1] Unit test `test_knowledge_base_context_reaches_both_stages` in `tests/assessment/test_services.py` — provides a non-empty `knowledge_base_context`; captures the prompt messages passed to each stage's mock; asserts the context appears in BOTH the reasoning prompt and the structuring prompt (covers the KB edge case)
- [X] T050 [P] [US1] Unit test `test_hallucinated_evidence_rejected_through_new_flow` in `tests/assessment/test_services.py` — structuring stage mocked to return `AIScoreOutput` whose `evidence` for one question references a quote absent from the content; asserts `_validate_output` raises, orchestrator retries structuring (reasoning NOT re-run), and on persistent failure returns a clear error naming the failing question (covers the "Reasoning contradicts evidence" edge case)
- [X] T051 [P] [US1] Unit test `test_reasoning_response_parser_extracts_one_record_per_question` in `tests/assessment/test_services.py` — feeds the parser a sample reasoning response formatted per T014's output contract (`### Q: <id>` headers); asserts exactly one `ReasoningQuestionRecord` per header, rationale text is preserved, and unknown/misformatted headers produce a parser error (covers the prompt-parsing contract pinned in T014)
- [X] T052 [P] [US1] Unit test `test_oversize_reasoning_payload_rejected` in `tests/assessment/test_services.py` — monkeypatches the token-count estimate to exceed the structuring model's budget; asserts `structuring_stage` raises `ReasoningPayloadTooLargeError` immediately (no LLM call made); asserts the error surfaces as HTTP 413 in an accompanying integration test, OR is mapped to a specific detail string (covers FR-014)

**Checkpoint**: User Story 1 is functional — the happy-path two-stage flow works end-to-end. LangSmith trace shows two child runs. Response schema is unchanged at this point. All three endpoints (`/assessments`, `/assessments/document`, `/assessments/audio`) are covered with happy- and error-path tests.

---

## Phase 4: User Story 2 — Auditability of the Reasoning Trace (Priority: P2)

**Goal**: Per-question rationale text is returned in the API response; the reasoning model's full thinking trace is visible in LangSmith for authorised reviewers.

**Independent Test**: Submit an assessment, confirm every item in `questions[]` has a non-empty `rationale` field. Open the request's trace in LangSmith, confirm `reasoning_stage` child run exposes `reasoning_content` on its output AIMessage.

### Tests for User Story 2

- [X] T019 [P] [US2] Unit test `test_rationale_populated_per_question` in `tests/assessment/test_services.py` — mocks both stages; asserts every `QuestionResult` in the returned `AssessmentResult` has a non-empty `rationale` field matching the rationale from the corresponding `ReasoningQuestionRecord`
- [X] T020 [P] [US2] Unit test `test_thinking_trace_attached_to_langsmith_span` in `tests/assessment/test_services.py` — patches the LangSmith tracer (or inspects `AggregatedReasoning.records[*].thinking_trace`), asserts the reasoner's thinking trace is preserved and flows into LangSmith span attributes via the `@traceable` wrapper
- [X] T021 [P] [US2] Integration test `test_assessments_response_includes_rationale` in `tests/assessment/test_router.py` — POSTs an assessment, asserts response JSON contains `rationale` string on every question and does NOT contain `thinkingTrace`/`thinking_trace` anywhere in the response body

### Implementation for User Story 2

- [X] T022 [P] [US2] Add `rationale: str = Field(default="")` to `QuestionResult` in `app/assessment/schemas.py`; ensure `CamelModel` alias resolves to `rationale` (camel form identical); add nothing to request schemas
- [X] T023 [US2] In `app/assessment/services.py::run_reasoning_assessment`, thread each `ReasoningQuestionRecord.rationale` into the corresponding `QuestionResult` during the final assembly loop (the loop that builds `question_results` from `ai_map` and `scorecard` sections); depends on T016 and T022
- [X] T024 [US2] Unconditionally wrap `run_reasoning_assessment` (and the stage helpers `reasoning_stage`, `structuring_stage`) with LangSmith's `@traceable` decorator from `langsmith` so the two stage calls appear as child runs of a single parent named `assessment_pipeline`; do not rely on conditional auto-instrumentation. Confirm (in `app/main.py` startup) that `os.environ["LANGSMITH_TRACING"] = "true"` is set when `settings.langsmith.tracing` is true; confirm `LANGSMITH_PROJECT` is set from `settings.langsmith.project`. Add a comment referencing FR-008 + US2 Acceptance Scenario 3.
- [X] T025 [US2] Run `uv run pytest tests/assessment -v` and confirm Phase-4 tests pass; additionally run the feature manually per quickstart.md §5 to confirm LangSmith visibility

**Checkpoint**: User Story 2 is functional — reviewers can read rationale in the response and full thinking traces in LangSmith.

---

## Phase 5: User Story 3 — Graceful Degradation When Reasoning Fails (Priority: P3)

**Goal**: Reasoning-stage failures fall back to the legacy single-shot flow (default) or surface a clear error (strict policy). Pipeline timeouts return HTTP 504 with a specific error message.

**Independent Test**: Force reasoning failure by setting `ASSESSMENT__REASONING_MODEL=deepseek-not-a-real-model`. With `failure_policy=fallback` (default) assert HTTP 200 + `reasoningUnavailable=true` + empty `rationale` on every question. With `failure_policy=strict` assert HTTP 502 + `detail="Reasoning stage failed after retries."`. With `ASSESSMENT__REQUEST_TIMEOUT_SECONDS=1` assert HTTP 504 + `detail` mentioning timeout.

### Tests for User Story 3

- [X] T026 [P] [US3] Unit test `test_orchestrator_fallback_on_reasoning_failure` in `tests/assessment/test_services.py` — mocks `reasoning_stage` to raise `RuntimeError` on all attempts; mocks `run_legacy_assessment` to return a canned result; asserts orchestrator returns the legacy result with `OverallResult.reasoning_unavailable=True` and every `QuestionResult.rationale==""`
- [X] T027 [P] [US3] Unit test `test_orchestrator_strict_policy_surfaces_error` in `tests/assessment/test_services.py` — same setup as T026 but `failure_policy="strict"` via config override; asserts `ReasoningUnavailableError` is raised; `run_legacy_assessment` is NOT called
- [X] T028 [P] [US3] Unit test `test_orchestrator_pipeline_timeout` in `tests/assessment/test_services.py` — mocks `reasoning_stage` to sleep longer than `request_timeout_seconds`; asserts `PipelineTimeoutError` is raised with a clear message including the configured ceiling
- [X] T029 [P] [US3] Integration test `test_assessments_endpoint_fallback_labelled` in `tests/assessment/test_router.py` — patches `get_reasoning_llm` to always fail; POSTs an assessment; asserts HTTP 200 and `overall.reasoningUnavailable === true` and every `questions[*].rationale === ""`
- [X] T030 [P] [US3] Integration test `test_assessments_endpoint_strict_returns_502` in `tests/assessment/test_router.py` — patches config to `failure_policy=strict` and forces reasoning failure; asserts HTTP 502 and `detail=="Reasoning stage failed after retries."`
- [X] T031 [P] [US3] Integration test `test_assessments_endpoint_timeout_returns_504` in `tests/assessment/test_router.py` — patches config to `request_timeout_seconds=1` and injects a slow reasoning mock; asserts HTTP 504 and `detail` contains `"timed out"`

### Implementation for User Story 3

- [X] T032 [P] [US3] Add `reasoning_unavailable: bool = Field(default=False)` to `OverallResult` in `app/assessment/schemas.py`; camel alias `reasoningUnavailable` (auto from `CamelModel`)
- [X] T033 [US3] Wrap the body of `run_reasoning_assessment` in `asyncio.wait_for(..., timeout=settings.assessment.request_timeout_seconds)`; on `asyncio.TimeoutError` raise `PipelineTimeoutError(settings.assessment.request_timeout_seconds)` in `app/assessment/services.py`; also reserve `settings.assessment.structuring_reserved_seconds` for the structuring stage — if elapsed time before structuring leaves less than 10s of the overall budget, raise `PipelineTimeoutError` preemptively
- [X] T034 [US3] Add reasoning-failure branching in `run_reasoning_assessment`: catch the reasoning-stage retry-exhaustion exception; if `settings.assessment.failure_policy == "fallback"`, call `run_legacy_assessment(request, knowledge_base_context)`, set `result.overall.reasoning_unavailable = True` (reconstruct `OverallResult` with this flag), return; else raise `ReasoningUnavailableError()`; emit a `StageOutcome(stage="fallback", ...)` span attribute when the fallback fires
- [X] T035 [US3] Extend `app/assessment/router.py::_run_with_error_handling` to map `PipelineTimeoutError` → HTTP 504, `ReasoningUnavailableError` → HTTP 502, and `ReasoningPayloadTooLargeError` → HTTP 413 with their respective detail messages; import all three from `app.core.errors`
- [X] T036 [US3] Run `uv run pytest tests/assessment -v` and confirm ALL Phase-5 tests pass alongside previously-added tests from Phase 3 and 4

**Checkpoint**: All three user stories are functional and independently testable.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, documentation alignment, and cleanup.

- [X] T037 [P] Run `uv run ruff check app/ tests/` and fix any new violations introduced by this feature
- [X] T038 [P] Run the full test suite `uv run pytest -v` and confirm 100% green
- [X] T039 [P] Execute the smoke tests in `specs/003-reasoning-aggregation/quickstart.md` sections 4, 6, 7, 8 against a running local server; document any deviations in quickstart.md
- [X] T040 Verify LangSmith UI shows the expected trace shape per quickstart.md §5 with `reasoning_content` visible on the reasoning child run
- [X] T041 [P] Contract-test backwards compatibility: instantiate a client-side Pydantic model that mirrors the **feature-002** `AssessmentResult` schema (without `rationale` or `reasoning_unavailable`) and confirm it can parse a real two-stage response without errors — add this as an assertion inside `tests/assessment/test_router.py::test_response_is_backwards_compatible`
- [X] T042 Review `app/assessment/services.py` for any dead code, unused imports, or stale comments introduced during the refactor; ensure `_SYSTEM_PROMPT` used by the legacy flow remains intact for fallback reliability
- [X] T053 [P] Document the LangSmith access-control policy in `specs/003-reasoning-aggregation/quickstart.md` §5 (satisfies FR-008 role-gated requirement): who has access to the `kynesis` project, how to request access, and a reminder that reasoning traces may contain PII and role-gating is the primary control
- [X] T054 [P] Integration test `test_assessments_document_endpoint_oversize_reasoning_returns_413` in `tests/assessment/test_router.py` — force a large scorecard/content combination that causes `ReasoningPayloadTooLargeError`; assert HTTP 413 and `detail` contains "too large" (satisfies FR-014 end-to-end coverage)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately. Short and mostly verification-only.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user-story phases.
- **US1 (Phase 3)**: Depends on Foundational. Delivers the MVP.
- **US2 (Phase 4)**: Depends on US1 (needs the orchestrator + stages to exist). Adds rationale to response + LangSmith parent-trace wrapping.
- **US3 (Phase 5)**: Depends on US1 (needs the orchestrator to wrap with timeout/fallback). Adds resilience. Independent of US2.
- **Polish (Phase 6)**: Depends on US1, US2, and US3.

### User Story Dependencies

- **US1 (P1 / MVP)**: Depends only on Phase 2 foundations. Must complete first.
- **US2 (P2)**: Depends on US1's orchestrator existing. **US2 and US3 can be worked in parallel by two developers** after US1 is merged, since they touch different concerns and only overlap trivially (both extend response schema, but in different fields).
- **US3 (P3)**: Depends on US1's orchestrator existing. See note above.

### Within Each User Story

- Tests for each story (T009–T013 and T043–T052 for US1, T019–T021 for US2, T026–T031 for US3) are written FIRST and MUST FAIL before the matching implementation tasks run.
- Schemas / models before services before router wiring.
- T014 (reasoning_stage) and T015 (structuring_stage) can run in either order but both must complete before T016 (orchestrator).
- T016 (orchestrator) must complete before T017 (router wiring).

### Parallel Opportunities

**Phase 1**: T002, T003 parallel with T001.

**Phase 2**: T005, T006, T007 can run in parallel (different files). T004 should complete first since config types are imported by T006. T008 depends on nothing in Phase 2 and can also run in parallel.

**Phase 3 (US1)**:
- Original MVP tests T009–T013 parallel.
- Remediation tests T043–T052 parallel — all target different test functions with no inter-dependencies. Can run alongside T009–T013.
- Implementation tasks T014 and T015 parallel — different functions in the same file can be edited together only with care; if sequential editing is preferred, run T014 first.
- T043, T044, T045, T046 (multipart endpoint tests) can begin immediately after T017 wires the router; they do not require T022 (rationale field) and pass even before US2 lands.

**Phase 4 (US2)**: Tests T019–T021 parallel. T022 parallel with all US2 tests. T023 sequential after T022. T024 parallel with T023 (different concern — tracing wrapper).

**Phase 5 (US3)**: All tests T026–T031 parallel. T032 parallel with tests. T033, T034 should be sequential (both edit the orchestrator). T035 parallel with T033/T034 (different file).

**Phase 6 (Polish)**: T037, T038, T039, T041, T053, T054 parallel. T040 and T042 sequential for review quality.

---

## Parallel Example: User Story 1 (MVP)

Once Phase 2 is complete, launch the US1 test suite together:

```bash
# Tests — all parallel (different test functions):
Task: "Unit test test_reasoning_stage_produces_record_per_question in tests/assessment/test_services.py"
Task: "Unit test test_structuring_stage_does_not_re_evaluate in tests/assessment/test_services.py"
Task: "Unit test test_orchestrator_happy_path_two_stages in tests/assessment/test_services.py"
Task: "Unit test test_structuring_retries_reuse_reasoning_artifact in tests/assessment/test_services.py"
Task: "Integration test test_assessments_endpoint_two_stage_success in tests/assessment/test_router.py"

# Implementation — T014 and T015 can be drafted in parallel by two devs,
# then merged before T016 (orchestrator) which depends on both.
Task: "Implement reasoning_stage() in app/assessment/services.py"
Task: "Implement structuring_stage() in app/assessment/services.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (verification only, should be fast).
2. Complete Phase 2: Foundational (config, factories, error types, schemas, rename).
3. Complete Phase 3: User Story 1 — two-stage happy-path pipeline.
4. **STOP and VALIDATE**: Manually smoke-test `POST /api/v1/assessments`; confirm LangSmith shows two child runs; confirm scores flow through. At this point the feature is demo-able and delivers the core scoring-quality win.
5. Deploy to staging if acceptable.

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → merge → demo: two-stage pipeline works, response contract unchanged
3. US2 → merge → demo: rationale visible in API, thinking trace visible in LangSmith
4. US3 → merge → demo: fallback + strict + timeout resilience
5. Polish → merge → feature complete

### Parallel Team Strategy

With two or three developers:

1. Whole team completes Phase 1 + Phase 2 together (1 dev leads T004, others handle T005–T008 in parallel).
2. One dev takes US1 (Phase 3) — MVP critical path.
3. After US1 merges, two devs split US2 and US3 (Phases 4 and 5) — independent concerns.
4. Whole team reviews Phase 6.

---

## Notes

- [P] tasks are on different files (or different test functions) and have no dependency on an unfinished task.
- [Story] label maps each implementation and test to its user story for traceability.
- Constitution III requires tests — this feature ships them as first-class tasks, not optional add-ons.
- Verify tests FAIL before implementing (TDD discipline within each story).
- Commit after each task or logical group.
- At every checkpoint you can stop and validate the story independently.
- Avoid: vague tasks, cross-story hidden dependencies, same-file conflicts between [P] tasks that edit overlapping regions.
