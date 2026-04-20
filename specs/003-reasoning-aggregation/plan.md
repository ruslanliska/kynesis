# Implementation Plan: Two-Stage Reasoning Assessment Pipeline

**Branch**: `003-reasoning-aggregation` | **Date**: 2026-04-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-reasoning-aggregation/spec.md`

## Summary

Replace the current single-model assessment flow with a two-stage pipeline inside `app/assessment/services.py`:

1. **Reasoning stage** — a dedicated reasoning model (DeepSeek R1 / `deepseek-reasoner`) analyses the scorecard + content and produces per-question rationale plus the model's full thinking trace. Runs with the model's recommended defaults; 1 retry on transient failure; exposes `reasoning_content` to LangSmith spans.
2. **Structuring stage** — a standard chat model (DeepSeek-V3 / `deepseek-chat` default; `gpt-4o` as escalation option) with `temperature ≤ 0.2` and `with_structured_output` serialises the reasoner's conclusions into the existing `AssessmentResult` schema. 3 retries with validation feedback, reusing the same reasoning artifact. Does not re-evaluate.

The response contract extends `QuestionResult` with a `rationale: str` field and `OverallResult` with `reasoning_unavailable: bool`. Thinking trace stays internal (LangSmith). On reasoning-stage final failure, the system falls back to the legacy single-shot flow by default (FR-010 `fallback` policy) and labels the result. Overall per-request ceiling is 180s.

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: FastAPI, LangChain (`langchain-deepseek`, `langchain-openai`, `langchain-core`), Pydantic v2, LangSmith (already in `pyproject.toml`; enabled via `LANGSMITH__TRACING=true` in `.env`), Logfire, Pinecone SDK
**Storage**: N/A (stateless feature; reuses feature-002 Pinecone for optional RAG context)
**Testing**: pytest + pytest-asyncio + httpx.AsyncClient; mock LangChain model responses for reasoning/structuring stages; no DB fixtures required
**Target Platform**: Linux server (FastAPI async backend)
**Project Type**: web-service (FastAPI, single-project layout per constitution)
**Performance Goals**: p95 end-to-end ≤ 90s (SC-003); hard ceiling 180s (FR-012); graceful degradation under concurrent load (SC-007; no fixed target)
**Constraints**: 180s hard per-request wall-clock; structuring stage `temperature ≤ 0.2` (FR-013); reasoning retries = 1 then fallback (FR-010); structuring retries = 3 reusing reasoning artifact (FR-005); response MUST remain backwards-compatible (new fields additive only) (FR-007); oversize reasoning payloads MUST be rejected with a clear error, never silently truncated (FR-014)
**Scale/Scope**: Single FastAPI worker fleet, no fixed concurrency target for v1; content up to 100k chars (unchanged); scorecards of arbitrary size within the 180s budget

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applies? | How this plan complies |
|---|---|---|
| I. Module-First Architecture | Yes | All changes live under the existing `app/assessment/` module — `services.py` gains two stage functions plus an orchestrator; `schemas.py` gains additive response fields and an internal reasoning-artifact model; `router.py` is unchanged except it continues to call the orchestrator. Cross-module imports (into `app/core/ai_provider.py` and `app/core/config.py`) go through existing public interfaces. No circular deps introduced. |
| II. Code Quality | Yes | All new functions have type hints and return types; Pydantic models for artifacts; async/await throughout; no router logic in services; no business logic in router; no raw SQL (feature is stateless); injected config via `get_settings()`. |
| III. Testing Standards | Yes | Unit tests for `reasoning_stage`, `structuring_stage`, orchestrator happy path, orchestrator fallback path, orchestrator timeout path (all under `tests/assessment/test_services.py`); integration test covering `POST /api/v1/assessments` end-to-end with mocked LangChain models (under `tests/assessment/test_router.py`). Each endpoint retains happy-path and error-path tests. Tests are async. |
| IV. API Consistency | Yes | No new endpoints added. Response remains `AssessmentResult` (Pydantic) returned from the existing routes; `{"detail": ...}` error shape unchanged; URL prefix `/api/v1/` unchanged; validation stays in Pydantic schemas. New `rationale` and `reasoning_unavailable` fields flow through Pydantic `CamelModel` (preserves camelCase aliases). |
| V. Performance Requirements | Yes | Async LangChain calls (`ainvoke`) throughout; no sync I/O on request path; no new DB work (stateless); the long-running reasoning call is bounded by `asyncio.wait_for` against the 180s budget, keeping worker event-loop behaviour predictable. No pagination concerns (single-result endpoint). |

**Result**: PASS — no violations. `Complexity Tracking` table stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-reasoning-aggregation/
├── plan.md              # This file
├── research.md          # Phase 0 output — model choice, temperature, timeout split, LangSmith, retry discipline
├── data-model.md        # Phase 1 output — reasoning artifact, aggregated bundle, extended result
├── quickstart.md        # Phase 1 output — how to run locally + smoke test
├── contracts/
│   └── assessments-post.md   # POST /api/v1/assessments contract (additive changes only)
├── checklists/
│   └── requirements.md  # Already produced by /speckit.specify
└── tasks.md             # Produced by /speckit.tasks
```

### Source Code (repository root)

```text
app/
├── assessment/
│   ├── __init__.py
│   ├── router.py            # EXTEND _run_with_error_handling — swap inner call to run_reasoning_assessment; add PipelineTimeoutError→504 and ReasoningUnavailableError→502 mappings. Public routes unchanged.
│   ├── schemas.py           # EXTEND — add ReasoningQuestionRecord, AggregatedReasoning, StageOutcome (internal); add rationale: str to QuestionResult; add reasoning_unavailable: bool to OverallResult
│   ├── services.py          # REFACTOR — rename current run_assessment → run_legacy_assessment (fallback); add reasoning_stage(), structuring_stage(), run_reasoning_assessment() orchestrator
│   ├── ocr.py               # UNCHANGED
│   └── transcription.py     # UNCHANGED
├── core/
│   ├── ai_provider.py       # EXTEND — add get_reasoning_llm() returning ChatDeepSeek(model="deepseek-reasoner"); add get_structuring_llm() returning ChatDeepSeek(model="deepseek-chat", temperature=0.1) with gpt-4o fallback option
│   ├── config.py            # EXTEND — add AssessmentConfig block: reasoning_model, structuring_model, structuring_temperature, reasoning_retries, structuring_retries, request_timeout_seconds, failure_policy
│   └── errors.py            # EXTEND — add ReasoningUnavailableError (caught internally, not raised to clients); add PipelineTimeoutError
└── main.py                  # UNCHANGED — LangSmith initialisation already wired via env

tests/
└── assessment/
    ├── __init__.py
    ├── test_services.py     # EXTEND — reasoning_stage unit, structuring_stage unit, orchestrator happy/fallback/timeout/retry-exhaustion
    └── test_router.py       # EXTEND — integration test for two-stage happy path + fallback labelling + timeout response
```

**Structure Decision**: Single-project layout (existing kynesis repo). No new modules — all feature work is additive within `app/assessment/` and `app/core/`. This matches Constitution Principle I (module-first) and keeps the public router contract unchanged.

## Complexity Tracking

> No entries — Constitution Check passed without violations.
