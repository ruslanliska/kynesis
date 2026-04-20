# Quickstart: Two-Stage Reasoning Assessment Pipeline

**Feature**: 003-reasoning-aggregation
**Date**: 2026-04-20

This quickstart assumes you already have the kynesis backend working locally (feature 002 is functional). Only the new-step additions are covered here.

---

## 1. Environment

Add to `.env` (or `.env.dev`):

```env
# DeepSeek (already present for feature 002)
DEEPSEEK__API_KEY=sk-…

# Optional — structuring-stage model escalation
OPENAI__API_KEY=sk-…

# LangSmith (enable tracing so reasoning traces are visible)
LANGSMITH__API_KEY=ls-…
LANGSMITH__TRACING=true
LANGSMITH__PROJECT=kynesis
```

If `LANGSMITH__TRACING` is false, the pipeline still works but the thinking trace is only visible in Logfire (not LangSmith), which breaks US2 Acceptance Scenario 3 — keep it true in all non-local environments.

## 2. Assessment config (new)

A new `AssessmentConfig` block is added to `app/core/config.py`. Defaults (server-side only, not client-overridable):

```python
class AssessmentConfig(BaseModel):
    reasoning_model: str = "deepseek-reasoner"
    structuring_model: str = "deepseek-chat"
    structuring_temperature: float = 0.1
    reasoning_retries: int = 1              # 2 attempts total
    structuring_retries: int = 3            # 4 attempts total
    request_timeout_seconds: int = 180
    structuring_reserved_seconds: int = 15
    failure_policy: Literal["strict", "fallback"] = "fallback"
```

All values are overridable via env (`ASSESSMENT__REASONING_MODEL=...`, etc.). No `.env` changes are required to run with defaults.

## 3. Run locally

```bash
# install / sync
uv sync

# start the API
uv run uvicorn app.main:app --reload --port 8000
```

## 4. Smoke test

Happy-path (two-stage) request:

```bash
curl -X POST http://localhost:8000/api/v1/assessments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d @tests/fixtures/sample_assessment_request.json | jq
```

Check the response shape:

- `overall.reasoningUnavailable === false`
- Every item in `questions[]` has a non-empty `rationale`
- Scores are present as before (no regression from feature 002)

## 5. Verify LangSmith trace

1. Open https://smith.langchain.com → `kynesis` project.
2. Find the most recent run named `assessment_pipeline` (or the auto-named root run).
3. Expand its children. You should see exactly two child runs: `reasoning_stage` (ChatDeepSeek / `deepseek-reasoner`) and `structuring_stage` (ChatDeepSeek / `deepseek-chat`).
4. Open the reasoning-stage run. The `additional_kwargs.reasoning_content` field on the output AIMessage contains the raw thinking trace.

If you cannot see `reasoning_content`, check that `LANGSMITH__TRACING=true` is set AND that the reasoning model is actually `deepseek-reasoner` (not `deepseek-chat`).

### LangSmith access policy (PII / role-gating — FR-008)

Reasoning traces and thinking traces captured in LangSmith can contain verbatim excerpts of the content under evaluation, which may include PII (customer names, phone numbers, account identifiers from call transcripts or chat logs). No automatic content redaction is applied before traces are sent.

**Access controls**:
- The `kynesis` LangSmith project MUST be scoped to the LangSmith organisation's production-data access group (not the general dev workspace).
- Only members of the QA Review role should be added to the project. Onboarding requires manager approval and is logged.
- To request access: open a ticket in the internal access-management system with the reason (e.g., "investigating disputed assessment <id>"); an admin adds your LangSmith email to the project membership.
- To revoke: remove the user from the LangSmith project; revocation is effective immediately for future trace views but does not scrub already-cached page views.

**Reminder for reviewers**:
- Treat trace content as confidential. Do not screenshot, export, or share trace content outside the review workflow.
- If you believe a trace contains highly sensitive data that should not have been stored (e.g., payment card numbers, SSNs), file a data-handling incident — do NOT link to or share the trace in plain text.

## 6. Force the fallback path

Point the reasoning model at an invalid identifier to simulate a 100% reasoning-stage failure:

```bash
ASSESSMENT__REASONING_MODEL=deepseek-not-a-real-model \
  uv run uvicorn app.main:app --reload --port 8000
```

Re-run the happy-path curl. Expected:

- HTTP 200
- `overall.reasoningUnavailable === true`
- Every `questions[*].rationale === ""`
- LangSmith trace shows the reasoning-stage run failing twice, then a `fallback` run succeeding.

## 7. Force the strict-policy error path

```bash
ASSESSMENT__REASONING_MODEL=deepseek-not-a-real-model \
ASSESSMENT__FAILURE_POLICY=strict \
  uv run uvicorn app.main:app --reload --port 8000
```

Expected:

- HTTP 502
- `{"detail": "Reasoning stage failed after retries."}`

## 8. Force the timeout path

Set an intentionally tight ceiling:

```bash
ASSESSMENT__REQUEST_TIMEOUT_SECONDS=1 \
  uv run uvicorn app.main:app --reload --port 8000
```

Any real request will now exceed the ceiling. Expected:

- HTTP 504
- `{"detail": "Assessment pipeline timed out after 1s."}`

## 9. Run the test suite

```bash
uv run pytest tests/assessment -v
```

Required test groups (added in this feature):

- `test_services.py::test_reasoning_stage_produces_record_per_question`
- `test_services.py::test_structuring_stage_does_not_re_evaluate`
- `test_services.py::test_orchestrator_happy_path_two_stages`
- `test_services.py::test_orchestrator_fallback_on_reasoning_failure`
- `test_services.py::test_orchestrator_strict_policy_surfaces_error`
- `test_services.py::test_orchestrator_timeout_returns_pipeline_timeout`
- `test_services.py::test_structuring_retries_reuse_reasoning_artifact`
- `test_router.py::test_assessments_endpoint_two_stage_success`
- `test_router.py::test_assessments_endpoint_fallback_labelled`
- `test_router.py::test_assessments_endpoint_timeout_504`

All must pass before merge.
