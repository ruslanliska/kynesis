# Feature Specification: Two-Stage Reasoning Assessment Pipeline

**Feature Branch**: `003-reasoning-aggregation`
**Created**: 2026-04-18
**Status**: Draft
**Input**: User description: "we need to add one more step for assessment, i wanna add reasoning for all questions, then gather all reasonings, all results what reasoning model was thinking, and give to model with structured output"

## Clarifications

### Session 2026-04-20

- Q: Is the per-question reasoning artifact returned in the assessment API response, or kept internal? → A: Return only the rationale text per question; the reasoning model's thinking trace stays internal (captured in observability only).
- Q: What is the per-request overall timeout after which the pipeline fails fast? → A: **180s hard ceiling**, AND the default failure policy is `fallback` (not `strict`) — on reasoning-stage timeout or irrecoverable error, the system runs the legacy single-shot flow as backup and labels the result accordingly. Rationale: reasoning models are slow/less stable, so a backup path must be active by default.
- Q: How many concurrent assessment requests must the new pipeline support without degradation? → A: **No fixed target.** The spec does NOT carry over feature 002's 10-concurrent commitment. It commits only to graceful degradation under load (clear errors or queuing, no crashes). A concrete number can be set later after measurement.
- Q: How are reasoning rationale + thinking trace handled in observability logs given possible PII? → A: **Log verbatim with access-gated viewing** (no automatic redaction). Rationale and full thinking trace MUST be visible in **LangSmith** for authorised reviewers investigating disputed assessments; access controls on the observability backend are the primary PII lever.
- Q: What is the retry budget for each stage on transient failures? → A: **Reasoning = 1 retry (2 attempts total) before invoking the FR-010 policy; structured-output = 3 retries (4 attempts total) reusing the same reasoning artifact.** Rationale: reasoning calls are expensive and slow, so fail fast to fallback; structured-output retries are cheap and typically resolve schema/validation issues.
- Constraint (user-raised): The structuring stage is a **formatter, not a second evaluator**. It MUST NOT re-evaluate, disagree with, or add new analysis beyond the reasoner's output — its only job is to serialise the reasoner's conclusions into the response schema. It MUST run at **low temperature** (≤ 0.2) so outputs are near-deterministic transcriptions of the reasoning.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deep Per-Question Reasoning Before Scoring (Priority: P1)

A QA manager submits a scorecard and content for assessment. Instead of a single-shot evaluation, the system first runs a dedicated **reasoning pass** across every question on the scorecard: for each question it thinks through the evidence, weighs ambiguous signals, and produces a verbose rationale (including the model's exposed "thinking"). All per-question rationales and the model's thinking traces are then **aggregated** and handed to a second model whose only job is to convert that aggregated analysis into the final structured assessment result (scores, evidence, comment, suggestions). The QA manager receives a result that is noticeably more defensible on borderline or critical questions because the score is grounded in deeper, explicit reasoning.

**Why this priority**: The purpose of the new step is to raise assessment quality and auditability on the same scorecard + content that today produces shallower results. It is the entire value of this feature — if it is not delivered, there is no feature.

**Independent Test**: Run the same scorecard + content through the new endpoint and confirm that (a) every question has a reasoning record generated before scoring, (b) the final structured result is produced by a separate model call that receives the reasoning as input, and (c) the final scores, evidence, and comments are traceable to specific statements in the reasoning output.

**Acceptance Scenarios**:

1. **Given** a valid scorecard with N questions and content to evaluate, **When** the request is submitted, **Then** the system produces a reasoning record for each of the N questions before any scoring decision is finalized.
2. **Given** reasoning records have been produced for all questions, **When** the structuring stage runs, **Then** it receives every per-question rationale plus the reasoning model's thinking trace as input, runs at low temperature, and returns a result that **transcribes** the reasoner's conclusions into the existing assessment result schema (per-question scores, evidence, comment, suggestions, section/overall scores, summary) without re-evaluating or overriding.
3. **Given** the reasoning step and the structuring stage both succeed, **When** the caller inspects the response, **Then** the response conforms to the same outward contract that callers already rely on for assessments — no breaking change to consumers who only want the final result.
4. **Given** a question is a HARD CRITICAL question, **When** reasoning is generated, **Then** the rationale for that question is non-empty (≥ 50 chars), references either the question id or the selected option / numeric value, and the structuring stage preserves the reasoner's conclusion (including a hard-critical zero, which MUST force `overall.score=0` and `hard_critical_failure=true` in the response).
5. **Given** the reasoning step returns content that the structuring stage cannot map to a valid answer for some question, **When** the structuring stage runs, **Then** the system retries up to **3 additional times (4 attempts total)** reusing the same reasoning artifact, and on final failure returns a clear error identifying which question(s) could not be scored.

---

### User Story 2 - Auditability of the Reasoning Trace (Priority: P2)

A QA reviewer investigating a disputed assessment wants to see **why** the system scored a specific question the way it did. The response includes, alongside the final structured result, the reasoning artifact for each question (the rationale and, where available, the reasoning model's exposed thinking trace). The reviewer can compare the structured score and comment against the underlying reasoning to validate consistency and spot hallucinations or gaps.

**Why this priority**: Auditability is the secondary benefit unlocked by the new pipeline. It is valuable but not required for the scoring improvement itself to land — the P1 story can ship without exposing the reasoning artifact to the caller.

**Independent Test**: Submit an assessment, retrieve the response, and verify that each question result carries a `rationale` field that is non-empty (≥ 20 chars), refers to the question being evaluated (by id or paraphrased content), and does not contradict the final `comment` or `suggestions` for that question.

**Acceptance Scenarios**:

1. **Given** an assessment has completed successfully, **When** the caller inspects the response, **Then** each question in the result has an associated **rationale text** (the reasoning model's thinking trace is NOT in the response; it is captured in observability only).
2. **Given** a rationale is attached to a question in the response, **When** it is compared to the final comment and suggestions for the same question, **Then** the comment and suggestions do not contradict the rationale.
3. **Given** a QA reviewer needs to inspect the raw thinking trace for a disputed assessment, **When** they open the request's trace in **LangSmith**, **Then** they can retrieve the reasoning model's full thinking trace and the per-question rationale, subject to their role-based access.

---

### User Story 3 - Graceful Degradation When Reasoning Fails (Priority: P3)

The reasoning model is slower and more expensive than a standard model and is more prone to timeouts or transient failures. When the reasoning step fails irrecoverably, the QA manager still wants a usable result rather than a hard failure. The system records that reasoning was unavailable and either (a) falls back to the existing single-shot assessment flow or (b) returns a clear error, according to a configured policy.

**Why this priority**: Resilience matters but is not required for the first usable version; the pipeline can initially return a hard error if reasoning fails, and fallback can be added later.

**Independent Test**: Force the reasoning step to fail (e.g., configure an invalid reasoning model), submit an assessment, and verify the configured policy is followed — either a labelled fallback result or a clear error.

**Acceptance Scenarios**:

1. **Given** the default `fallback` policy is in effect, **When** the reasoning step fails after all retries or breaches its share of the 180s budget, **Then** the system executes the legacy single-shot assessment and returns a result flagged as "reasoning unavailable".
2. **Given** the policy has been explicitly configured to `strict`, **When** the reasoning step fails after all retries, **Then** the system returns a clear error indicating the reasoning step failed and no partial result.
3. **Given** a result returned from the fallback path, **When** a caller or auditor inspects it, **Then** the result is clearly labelled (e.g., `reasoning_unavailable: true`) so it is distinguishable from a two-stage result.

---

### Edge Cases

- **Reasoning covers a subset of questions**: If the reasoning step returns rationale for fewer questions than the scorecard contains, the system MUST treat this as a failure of the reasoning step and retry before moving on; the structuring stage MUST NOT run on incomplete reasoning.
- **Reasoning contradicts evidence**: If the reasoning refers to evidence not present in the submitted content, the structuring stage's existing evidence validation (verbatim quotes present in content) MUST still apply — hallucinated evidence is rejected regardless of what the reasoning said.
- **Extremely long reasoning output**: When the aggregated reasoning exceeds the structuring model's input token budget, the system MUST reject the request with a clear error per FR-014 (no silent truncation). Best-effort per-question summarisation is explicitly out of scope for v1.
- **HARD CRITICAL auto-fail path**: Hard-critical auto-fail behaviour (overall score forced to 0) MUST be preserved end-to-end; neither the new reasoning step nor the structuring stage can mask a hard-critical zero.
- **Knowledge base context**: When a knowledge base is attached, the reasoning step MUST receive the same retrieved context the current flow uses, so the rationale is grounded in the same source material. The structuring stage MUST receive the same context so evidence-validation semantics remain unchanged.
- **Idempotency**: Two runs of the same request are not required to produce identical reasoning text, but MUST produce scores within the same tolerance the current pipeline commits to.
- **Retry semantics**: A failed structuring-stage call MUST be retried without re-running the (expensive) reasoning step — the reasoning artifact from a successful reasoning pass MUST be reusable across structuring-stage retries within the same request.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The assessment pipeline MUST be a two-stage flow: (1) a reasoning stage that produces per-question rationale for every question on the scorecard, followed by (2) a structuring stage that consumes those rationales and returns the final assessment result.
- **FR-002**: The reasoning stage MUST produce, for every question in the scorecard, at minimum a written rationale; where the reasoning model exposes a thinking/scratchpad trace, that trace MUST also be captured.
- **FR-003**: The reasoning stage MUST receive the same inputs the current assessment receives — scorecard definition (all sections and questions), the content under evaluation, and any knowledge-base context retrieved for the request.
- **FR-004**: The structuring stage MUST receive as input the full set of per-question rationales (plus any thinking traces) from the reasoning stage and MUST produce the existing assessment result contract (content analysis, per-question output with evidence/reasoning/selected answer/comment/suggestions, summary, section scores, overall score). The structuring stage is a **formatter only** — it MUST treat the reasoner's output as authoritative and MUST NOT re-evaluate, override scores, add new evidence, or introduce rationale absent from the reasoner. "Traceable" is defined concretely as: (a) every `evidence` quote MUST appear verbatim in either the reasoner's rationale for that question or in the source content (this is the existing verbatim-evidence rule, unchanged); (b) each `comment` MUST NOT assert facts that are absent from or directly contradicted by the rationale for its question; (c) each `selected_option_id` / `numeric_value` MUST match the answer indicated by the rationale for its question.
- **FR-005**: The system MUST validate the structuring-stage result against the scorecard exactly as it does today — every question answered, valid option IDs, numeric values within bounds, evidence present for non-tag-only questions — and MUST retry on validation failure **up to 3 times (4 attempts total)** without re-running the reasoning stage; the reasoning artifact from the successful reasoning pass MUST be reused across all structuring-stage retries.
- **FR-006**: The system MUST preserve all existing scoring behaviours: weighted scoring, pass threshold evaluation, hard-critical auto-fail, and section-level scoring. The reasoning stage does not compute scores; it only produces rationale.
- **FR-007**: The system MUST return a single response that conforms to the existing assessment result contract so current callers are not broken. The response MUST include the **per-question rationale text** as an additive field on each question result; the response MUST NOT include the reasoning model's thinking trace (that stays internal / observability-only).
- **FR-008**: The system MUST record observability signals for the new pipeline — at minimum a span/timing for the reasoning stage, a span/timing for the structuring stage, counts of retries per stage, success/failure status per stage, and the full per-question **rationale text** and reasoning model **thinking trace** as span attributes or inputs. Observability traces MUST be visible in **LangSmith** so QA reviewers can inspect the reasoning behind any request. Access to these traces MUST be gated by role/permission at the observability backend; no automatic content redaction is applied.
- **FR-009**: The system MUST support configuring the reasoning model and the structuring model independently (they are expected to be different models). The configuration lives server-side; callers do not pick models per request.
- **FR-010**: The system MUST retry the reasoning stage **once (2 attempts total)** on transient failure. If both attempts fail, it MUST handle the failure according to a configured policy (strict = surface error; fallback = run the legacy single-shot flow and label the result). Default policy MUST be `fallback` so transient reasoning-model failures do not block QA managers from receiving an assessment. The fallback result MUST be clearly labelled (e.g., `reasoning_unavailable: true`) so consumers and auditors can distinguish two-stage results from fallback results.
- **FR-011**: Input validation (content length limits, scorecard structure, knowledge-base-id validity) MUST occur once at the start of the request, before either stage runs — it MUST NOT be duplicated across stages.
- **FR-012**: The system MUST enforce an overall per-request wall-clock ceiling of **180 seconds**. When the reasoning stage breaches its share of that budget, the system MUST treat it as a reasoning-stage failure and apply the FR-010 policy (default: run the legacy fallback flow). When the structuring stage breaches the remaining budget, the system MUST return a clear timeout error rather than partially completing.
- **FR-013**: The structuring stage MUST run at **low temperature (≤ 0.2)** so its output is a near-deterministic transcription of the reasoner's conclusions, not a creative re-interpretation. The reasoning stage's temperature is NOT constrained by this requirement (it follows the reasoning model's recommended defaults).
- **FR-014**: When the aggregated reasoning payload would exceed the structuring model's input token budget, the system MUST reject the request with a clear, caller-facing error rather than silently truncating, summarising, or discarding any part of the reasoner's analysis. The error MUST name the cause ("reasoning payload too large for structuring model") and suggest reducing scorecard or content size. Per-question automatic summarisation is explicitly out of scope for v1.

### Key Entities

- **Reasoning Record (per question)**: The reasoning stage's output for a single scorecard question. Attributes: question_id, rationale_text, thinking_trace (optional, present when the reasoning model exposes it), reasoning_status (ok / degraded / missing). Not persisted by the backend; produced in-memory during the request.
- **Aggregated Reasoning Bundle**: The complete set of Reasoning Records for a request, passed as input to the structuring stage. Attributes: scorecard_id, content summary context, list of Reasoning Records, coverage flag (all questions covered y/n).
- **Pipeline Stage Outcome**: Observability-facing record of what happened in each stage. Attributes: stage (`reasoning` | `structuring` | `fallback`), status, retry_count, duration_ms, error (if any). Emitted as structured log / span; not returned in the caller response.
- **Assessment Result** (extended contract, existing entity): The final output returned to the caller. See feature 002 for the full schema. This feature adds one additive field per question result — the **rationale text** produced by the reasoning stage. The reasoning model's thinking trace is NOT part of the response contract; it is available only via observability.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the same scorecard + content, the new two-stage pipeline produces a reasoning record for 100% of questions before any scoring decision is finalised — no question is scored without a corresponding rationale.
- **SC-002**: On a benchmark set of borderline / disputed assessments, agreement between the new pipeline's scores and an expert-rater reference scoreset improves by at least 15% over the legacy single-shot flow (measured as per-question exact-match rate).
- **SC-003**: End-to-end assessment latency for content up to 10,000 characters and a 5-question scorecard completes within 90 seconds at the 95th percentile (acknowledging the reasoning stage is slower than a single-shot call).
- **SC-004**: 100% of successful responses conform to the existing assessment result contract so no frontend changes are required to consume the new flow.
- **SC-005**: When reasoning is successful but structuring fails, the system recovers via structuring-stage retry (without re-running reasoning) for at least 90% of transient structuring failures in internal testing.
- **SC-006**: For every request, the observability backend shows two distinct stage spans (reasoning, structuring) with timings and outcomes — operators can diagnose which stage is slow or failing without reading code.
- **SC-007**: Under concurrent load, the system degrades gracefully — it MUST either complete requests successfully, return a clear error (e.g., rate-limited, backpressure), or queue the request; it MUST NOT crash, corrupt in-flight state, or return malformed responses. No specific concurrent-request number is committed by this feature; concurrency targets will be set after measurement.

## Assumptions

- The two-stage flow replaces the legacy single-shot flow as the default assessment implementation. The legacy flow is retained only as the `fallback` policy target for FR-010, not as a parallel user-selectable mode.
- The reasoning model and the structuring model are configured server-side (following the existing AI provider configuration approach from feature 002). Callers do not specify models per request.
- The reasoning stage processes all scorecard questions in a single reasoning call (one prompt covering the whole scorecard) rather than one call per question, to keep costs and rate-limit exposure predictable. Per-question parallel reasoning is out of scope for v1 and can be reconsidered after measurement.
- The reasoning model may or may not expose its thinking trace; the system captures it when available and proceeds normally when it is not.
- Reasoning content is passed to the structuring stage verbatim (or near-verbatim, minus truncation handling for extreme lengths). The structuring stage is explicitly prompted as a **formatter/transcriber** — its sole job is to map the reasoner's conclusions into the response schema. It does not re-evaluate, does not override the reasoner, and runs at low temperature (≤ 0.2) for near-deterministic output.
- The new pipeline extends the assessment result contract with one additive field per question result — the rationale text. Consumers that ignore the new field are unaffected. The reasoning model's thinking trace is never part of the response.
- HARD CRITICAL auto-fail semantics, pass threshold semantics, weighted scoring, and evidence-validation semantics are all unchanged and continue to be enforced in the structuring stage exactly as today.
- Knowledge-base retrieval happens once per request (before the reasoning stage) and the retrieved context is shared by both stages; the stages do not each perform their own retrieval.
- Observability uses the same observability stack already adopted by feature 002 **plus LangSmith** for LLM-call tracing and reasoning-trace inspection. Access to reasoning traces in LangSmith is role-gated; automatic PII redaction is not applied.
- Authentication, rate limiting, and request-level input validation are unchanged from feature 002.
- Concurrent-assessment capacity is **not** carried over from feature 002. The new pipeline doubles per-request model calls, so the prior 10-concurrent target is treated as an implementation-phase measurement question rather than a spec commitment.
- **Post-ship measurement items**: SC-002 (15% benchmark improvement), SC-003 (p95 ≤ 90s), and SC-007 (graceful degradation under concurrent load) are success criteria that require post-ship measurement infrastructure (an expert-rater benchmark dataset, a sustained-load harness, a concurrency stress harness) not built as part of this feature. They remain MUST-meet targets but are validated outside this feature's task list. The shipped tasks cover functional correctness and per-request behaviour; performance and benchmark validation follow in a separate work item.
