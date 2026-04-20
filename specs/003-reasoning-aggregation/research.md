# Phase 0 Research: Two-Stage Reasoning Assessment Pipeline

**Feature**: 003-reasoning-aggregation
**Date**: 2026-04-20
**Status**: Complete — no open NEEDS CLARIFICATION items

All major decisions are pinned by the spec's Clarifications section (2026-04-20 session). This document records the technical rationale, alternatives considered, and integration patterns chosen.

---

## R1. Reasoning-stage model

- **Decision**: Use **DeepSeek R1** (`model="deepseek-reasoner"`) via the already-installed `langchain-deepseek` (`ChatDeepSeek`).
- **Rationale**:
  - Already an authorised provider — `DeepSeekConfig` exists in `app/core/config.py`; `ChatDeepSeek` imports already wired in `app/core/ai_provider.py`. No new SDK / billing / approval needed.
  - Exposes the full raw thinking trace via the `reasoning_content` attribute on AIMessage, which is what Q4's LangSmith-visibility requirement needs. (OpenAI o-series only expose summaries.)
  - ~10–20× cheaper per token than OpenAI o1/o3/o4-mini, which matters because the spec commits to a 180s ceiling that realistically permits a slow reasoning call.
  - R1 does not support `with_structured_output` well — which is the exact architectural motivation for splitting reasoning from structuring.
- **Alternatives considered**:
  - **OpenAI o1 / o3-mini / o4-mini** — strong reasoning but hides the raw thinking trace (Q4 requires it in LangSmith) and materially more expensive per request. Rejected.
  - **DeepSeek-V3 (`deepseek-chat`)** — the current single-shot default; not a reasoning model. Rejected on purpose — eliminating this is the whole point of the feature.
  - **Anthropic Claude extended thinking** — excellent reasoning quality, exposes thinking traces, but introduces a new provider (no existing `AnthropicConfig`, no API key wired up). Deferred as a future v2 option, not v1.

## R2. Structuring-stage model and temperature

- **Decision**: Default to **`deepseek-chat`** at `temperature=0.1` (satisfies FR-013 `≤0.2`). Provide an escalation switch to `gpt-4o` via `AssessmentConfig.structuring_model`.
- **Rationale**:
  - The spec's Q5 constraint makes this stage a **formatter** only — its job is serialising the reasoner's conclusions into the Pydantic schema. This is a well-understood, near-deterministic transcription task that a standard chat model handles fine.
  - `deepseek-chat` is already the current default and is proven against the existing `AIScoreOutput` schema under the current flow's `MAX_RETRIES=3` loop, so we have real confidence in its structured-output behaviour.
  - `gpt-4o` retained as an escalation option — if field-level schema adherence becomes a tail-latency source (structured-output retries firing more than ~5–10% of the time), flip one config value.
  - Low temperature chosen because the stage is not doing creative reasoning; determinism reduces retry variance and makes LangSmith traces easier to compare across runs.
- **Alternatives considered**:
  - `temperature=0.0` — slightly more deterministic but some providers have edge-case issues with fully greedy sampling (e.g., repetition, degenerate outputs). `0.1` is the conventional "as deterministic as safely achievable" setting.
  - `gpt-4o-mini` as default for cost — untested against our scorecard schema; reject for v1 to minimise risk. Can be measured later.

## R3. Timeout budget split (180s hard ceiling)

- **Decision**: Enforce a single outer ceiling of **180s** via `asyncio.wait_for` around the entire `run_reasoning_assessment()` orchestrator. Inside the orchestrator, reserve **15s** of headroom for the structuring stage; any remaining time goes to the reasoning stage (reasoning call is the long-tail risk).
  - Reasoning stage soft budget = `min(165s, per_call_client_timeout)`.
  - Structuring stage soft budget = `remaining_budget` (expected 15–60s).
  - If the structuring stage would start with < 10s remaining, abort with `PipelineTimeoutError` rather than starting a doomed call.
- **Rationale**:
  - Single outer deadline matches FastAPI / uvicorn behaviour and is a clean abstraction for the caller.
  - The reasoner is the slow, unpredictable component — giving it the majority of the budget matches its real-world tail behaviour; the structuring call is fast enough (< 15s typical) that 15s reserved is sufficient.
  - The 10s abort threshold avoids "fail after doing work" scenarios where the structuring call starts with seconds left, returns an error, and we have no budget for retry.
- **Alternatives considered**:
  - Per-stage hard timeouts (e.g., reasoning=120s, structuring=60s) — cleaner in isolation but wastes budget when reasoning finishes fast. Rejected.
  - No inner budget, just the outer `wait_for` — works but produces worse error messages (cancellation vs a semantic `PipelineTimeoutError`). Rejected.

## R4. Retry discipline

- **Decision**:
  - Reasoning stage: `reasoning_retries=1` (2 attempts total). After exhaustion, run FR-010 policy (default `fallback`).
  - Structuring stage: `structuring_retries=3` (4 attempts total). On each retry, append the validation error as a `HumanMessage` (same pattern as the existing `run_assessment`). **The reasoning artifact is passed in unchanged across all structuring retries.**
- **Rationale**:
  - Matches the spec's Q5 answer literally.
  - Reuses the proven retry pattern from `app/assessment/services.py` (MAX_RETRIES=3 with validation-error feedback) — minimal new behaviour to test.
  - Caching the reasoning artifact across structuring retries is critical: re-running the reasoner on a schema-validation failure would double costs and mostly not fix the issue (the reasoner's output was fine; the structurer just needs another pass).
- **Alternatives considered**:
  - Exponential backoff between retries — unnecessary at the per-request scale; provider SDKs already implement SDK-level retries for rate-limit / connection errors. Rejected as over-engineering.
  - Retry on timeout specifically — no, timeout means we've exceeded the budget; retrying only burns more budget. Timeout → immediately surface `PipelineTimeoutError` or fallback per FR-010.

## R5. Fallback path wiring

- **Decision**: Rename the existing `run_assessment()` function to `run_legacy_assessment()` (same signature, same behaviour), and call it from the orchestrator when:
  - Both reasoning attempts fail, AND
  - `AssessmentConfig.failure_policy == "fallback"` (default).
  The legacy result is wrapped so `OverallResult.reasoning_unavailable = True` before being returned.
- **Rationale**:
  - Zero behaviour change for the legacy flow — it's the same code, reached via a renamed symbol.
  - Single clearly-named function that maps directly to US3 Acceptance Scenario 1.
  - The flag on the response is the auditability hook the spec requires (US3 Acceptance Scenario 3).
- **Alternatives considered**:
  - Remove the legacy flow entirely — rejected. Q2's clarification explicitly requires an active backup. The legacy flow IS the backup.
  - Keep legacy as the default and make the two-stage flow opt-in via flag — rejected. Spec assumptions state the two-stage flow replaces the default.

## R6. LangSmith integration

- **Decision**: Enable LangSmith via environment (existing `LangSmithConfig` in `app/core/config.py`). Confirm both stages appear as distinct runs by:
  - Calling each stage via `ChatDeepSeek.ainvoke(...)` / `.with_structured_output(...).ainvoke(...)` without manual span wrapping (LangChain auto-instruments both).
  - Wrapping the orchestrator in a `logfire.span("assessment_pipeline", scorecard_id=...)` AND a LangChain `@traceable`-decorated wrapper (or `tracing_v2_enabled` context manager) so the two model calls appear as child runs of one parent trace.
  - Setting `LANGSMITH__TRACING=true` and `LANGSMITH__PROJECT=kynesis` in the deployment env; documenting this in quickstart.
- **Rationale**:
  - LangChain's auto-instrumentation already captures `reasoning_content` as a span attribute when present on AIMessage — no manual serialisation needed.
  - `@traceable` keeps the parent/child relationship visible in LangSmith, which is what US2 Acceptance Scenario 3 requires ("open the request's trace in LangSmith ... retrieve the thinking trace").
  - Access gating is a LangSmith-side concern (project membership / RBAC) — out of code scope; documented as an assumption in the spec.
- **Alternatives considered**:
  - Manual span creation with OpenTelemetry — rejected. LangChain + LangSmith already handle this; re-doing it adds code that can drift.
  - Logging reasoning content only to Logfire — rejected. Q4 explicitly names LangSmith as the required backend for reasoning-trace inspection.

## R7. Response-schema backwards compatibility

- **Decision**:
  - Add `rationale: str` (non-optional in the two-stage flow; empty string `""` in the fallback legacy flow) to `QuestionResult`.
  - Add `reasoning_unavailable: bool = False` to `OverallResult`.
  - Both fields carry `CamelModel` aliases (`rationale` → `rationale`, `reasoning_unavailable` → `reasoningUnavailable`) consistent with feature 002's schema style.
- **Rationale**:
  - Adding fields is non-breaking for consumers that deserialise into permissive structures (TypeScript `any`, generated Zod schemas with `.passthrough()`, etc.).
  - `rationale: str` rather than `str | None` because every question has a rationale in the happy path and `""` is a reasonable sentinel for the fallback path — avoids leaking `None` / `null` handling across the frontend.
  - The existing `feedback` / `comment` field is preserved unchanged; `rationale` is the reasoner's explanation, `comment` remains the structurer's user-facing assessment. Two distinct fields with distinct purposes, not a rename.
- **Alternatives considered**:
  - Optional `rationale: str | None` — rejected. Frontends end up with `null`-handling noise that the response actually doesn't need. `""` is cleaner.
  - A single nested `reasoning: {rationale, status}` object — rejected as over-engineering for one-field-per-question. A sibling field is simpler.

## R8. Input validation reuse

- **Decision**: All input validation (scorecard structure, content length 50–100_000, scorecard-status check, file-size checks for document/audio routes) remains in the existing `router.py` / `_run_with_error_handling` guard and Pydantic schemas. The new orchestrator assumes inputs are valid when called.
- **Rationale**: FR-011 explicitly says validation happens once, before either stage. No duplication.

## Resolution of spec NEEDS CLARIFICATION items

None outstanding. All five clarification questions and the user-raised constraint on structuring-stage temperature are integrated into the spec as of 2026-04-20.
