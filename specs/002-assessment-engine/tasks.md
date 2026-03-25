# Tasks: Assessment Processing Engine

**Input**: Design documents from `/specs/002-assessment-engine/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Not explicitly requested in spec. Test tasks omitted. Tests can be added later.

**Organization**: Tasks grouped by user story. US1 and US2 are both P1 but US1 (assessment) is the core MVP. US2 (knowledge base) enables RAG-enhanced assessments. US3 (insights) is P2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1, US2, US3)
- Exact file paths included

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Update project dependencies and configuration for new feature

- [x] T001 Update pyproject.toml with new dependencies: pydantic-ai, pinecone, logfire[fastapi], pymupdf, python-docx, langchain-text-splitters, python-multipart
- [x] T002 Update app/core/config.py with new settings: AI_MODEL, OPENAI_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_CLOUD, PINECONE_REGION, LOGFIRE_TOKEN, LOGFIRE_SEND_TO_LOGFIRE
- [x] T003 [P] Create app/core/errors.py with consistent error response helpers and exception handlers
- [x] T004 [P] Create app/core/ai_provider.py with Pydantic AI agent factory and Pinecone client initialization

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Update app/main.py: add Logfire instrumentation (instrument_fastapi, instrument_pydantic_ai), register new routers, update CORS allow_methods to include POST/DELETE
- [x] T006 Create .env.example with all required environment variables documented
- [x] T007 Update tests/conftest.py with mock AI provider fixtures, mock Pinecone client fixtures, and new test settings

**Checkpoint**: Foundation ready — user story implementation can begin

---

## Phase 3: User Story 1 — Run Scorecard Assessment (Priority: P1) MVP

**Goal**: Accept scorecard + content, run AI evaluation, return structured scores per criterion with weighted total

**Independent Test**: Send scorecard with 3+ criteria and sample transcript, verify response contains per-criterion scores, feedback, and correctly calculated weighted total score

### Implementation

- [x] T008 [P] [US1] Create app/assessment/__init__.py
- [x] T009 [P] [US1] Create app/assessment/schemas.py with ScorecardCriterion, Scorecard, AssessmentRequest, CriterionScore, AssessmentResult per data-model.md
- [x] T010 [US1] Create app/assessment/services.py with assessment evaluation agent (Pydantic AI Agent with result_type, system prompt, result_validator for score consistency), weighted score calculation function
- [x] T011 [US1] Create app/assessment/router.py with POST /api/v1/assessments endpoint: validate request, call service, handle AI errors (UnexpectedModelBehavior → 502, UsageLimitExceeded → 429), return AssessmentResult

**Checkpoint**: Assessment endpoint works without knowledge base. Can evaluate content against scorecard criteria and return structured scores.

---

## Phase 4: User Story 2 — Upload and Process Knowledge Base (Priority: P1)

**Goal**: Upload documents, chunk, embed, store in Pinecone. Retrieve relevant chunks during assessment via RAG.

**Independent Test**: Upload a document, query the KB, verify relevant chunks returned. Then run assessment with KB ID and verify AI references uploaded content.

### Implementation

- [x] T012 [P] [US2] Create app/knowledge_base/__init__.py
- [x] T013 [P] [US2] Create app/knowledge_base/schemas.py with KnowledgeBaseUploadResponse, KBQueryRequest, KBQueryResponse, KBQueryResult, KBDeleteResponse per data-model.md
- [x] T014 [P] [US2] Create app/knowledge_base/parsers.py with document text extraction functions: parse_pdf (pymupdf), parse_docx (python-docx), parse_txt, parse_markdown, and format dispatcher by file extension
- [x] T015 [US2] Create app/knowledge_base/services.py with: chunk_text (RecursiveCharacterTextSplitter), generate_embeddings (OpenAI text-embedding-3-small), upsert_to_pinecone (batch upsert with metadata), query_pinecone (similarity search), delete_document (metadata filter delete), delete_knowledge_base (namespace delete), process_document (orchestrates parse→chunk→embed→upsert pipeline)
- [x] T016 [US2] Create app/knowledge_base/router.py with: POST /api/v1/knowledge-bases/upload (multipart file upload, validate format/size, call process_document), POST /api/v1/knowledge-bases/{kb_id}/query (query endpoint), DELETE /api/v1/knowledge-bases/{kb_id} (delete KB)
- [x] T017 [US2] Integrate KB retrieval into assessment: update app/assessment/services.py to accept knowledge_base_id, retrieve relevant chunks from Pinecone, include as context in AI prompt, set knowledge_base_used/knowledge_base_warning in response

**Checkpoint**: Documents can be uploaded, chunked, embedded, and stored. Assessments with KB ID retrieve relevant context via RAG.

---

## Phase 5: User Story 3 — Generate Cross-Assessment Insights (Priority: P2)

**Goal**: Analyze multiple assessment results using AI, return structured insights (issues, patterns, recommendations, strengths, weaknesses)

**Independent Test**: Submit 5+ assessment results with varied scores, verify response contains patterns, top issues, recommendations, strength/weak areas, and summary

### Implementation

- [x] T018 [P] [US3] Create app/insights/__init__.py
- [x] T019 [P] [US3] Create app/insights/schemas.py with InsightIssue, InsightPattern, InsightRecommendation, InsightArea, InsightRequest, InsightReport per data-model.md
- [x] T020 [US3] Create app/insights/services.py with insights analysis agent (Pydantic AI Agent with result_type=InsightReport, system prompt for cross-assessment analysis, structured output)
- [x] T021 [US3] Create app/insights/router.py with POST /api/v1/insights endpoint: validate min 3 assessments, call service, handle AI errors, return InsightReport

**Checkpoint**: Insights endpoint accepts assessment results and returns structured cross-assessment analysis

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final integration, validation, and cleanup

- [x] T022 Update app/main.py to register all three routers (assessment, knowledge_base, insights) if not already done in T005
- [x] T023 Run quickstart.md validation: test all 5 integration scenarios from quickstart.md with curl commands
- [x] T024 [P] Verify error handling consistency across all endpoints: 422 for validation, 502 for AI errors, 429 for rate limits, 404 for missing KB

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 — core MVP
- **User Story 2 (Phase 4)**: Depends on Phase 2. T017 (KB integration into assessment) depends on Phase 3 completion
- **User Story 3 (Phase 5)**: Depends on Phase 2. Uses AssessmentResult schema from US1 (but can be developed independently)
- **Polish (Phase 6)**: Depends on all user stories

### User Story Dependencies

- **US1 (Assessment)**: After Phase 2 — no dependencies on other stories
- **US2 (Knowledge Base)**: After Phase 2 — T012-T016 independent of US1. T017 (RAG integration) requires US1 assessment service
- **US3 (Insights)**: After Phase 2 — reuses AssessmentResult schema from US1 but implementation is independent

### Within Each User Story

- Schemas before services (services import schemas)
- Services before routers (routers call services)
- Parsers (US2) before services (services call parsers)

### Parallel Opportunities

Phase 1:
```
T003 (errors.py) ∥ T004 (ai_provider.py) — after T001, T002
```

Phase 3 (US1):
```
T008 (__init__.py) ∥ T009 (schemas.py) — then T010 (services) → T011 (router)
```

Phase 4 (US2):
```
T012 (__init__.py) ∥ T013 (schemas.py) ∥ T014 (parsers.py) — then T015 (services) → T016 (router) → T017 (integration)
```

Phase 5 (US3):
```
T018 (__init__.py) ∥ T019 (schemas.py) — then T020 (services) → T021 (router)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1 (Assessment)
4. **STOP and VALIDATE**: Test assessment endpoint with curl
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 (Assessment) → Test → Deploy (MVP!)
3. US2 (Knowledge Base) → Test uploads + RAG integration → Deploy
4. US3 (Insights) → Test cross-assessment analysis → Deploy
5. Polish → Final validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story
- Each story independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate independently
- No database models — all Pydantic schemas (transient)
- AI provider mocked in tests — no real LLM calls during testing
- Pinecone mocked in tests — no real vector DB calls during testing
