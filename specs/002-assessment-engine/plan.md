# Implementation Plan: Assessment Processing Engine

**Branch**: `002-assessment-engine` | **Date**: 2026-03-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-assessment-engine/spec.md`

## Summary

Stateless FastAPI processing engine for AI-powered scorecard assessments. Uses Pydantic AI for multi-provider AI agent orchestration with structured output validation, Pinecone for knowledge base vector storage and RAG retrieval, and Pydantic Logfire for observability. The frontend (Lovable Cloud / Supabase) handles all CRUD and storage — this backend only processes AI evaluations, document ingestion, and cross-assessment insights.

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: FastAPI, Pydantic AI, Pinecone SDK, Pydantic Logfire, python-multipart (file uploads), pypdf/python-docx/markdown (document parsing)
**Storage**: Pinecone (vector DB for knowledge base embeddings); SQLAlchemy async + asyncpg retained for future use (not used by current endpoints)
**Testing**: pytest + pytest-asyncio + httpx
**Target Platform**: Linux server (containerized)
**Project Type**: web-service (stateless processing API)
**Performance Goals**: Assessment response <30s for 10k chars + 5 criteria; Document upload <60s for 10MB; Insights <30s; 10 concurrent requests
**Constraints**: Max 100,000 chars content; Max 10MB document upload; Stateless — no user sessions or request-state DB
**Scale/Scope**: Single API service, 3 endpoint groups (assessment, knowledge base, insights)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Module-First Architecture | PASS | Three modules: `assessment/`, `knowledge_base/`, `insights/` — each with models.py, schemas.py, router.py, services.py |
| II. Code Quality | PASS | Type hints on all functions, async-only, Pydantic schemas at boundaries, Depends() for DI |
| III. Testing Standards | PASS with exception | Unit tests for services, integration tests for endpoints. Exception: no real Postgres test DB needed for current endpoints (stateless, no DB). Mock AI providers and Pinecone in tests. |
| IV. API Consistency | PASS | Pydantic response schemas, consistent error shape `{"detail": "..."}`, `/api/v1/` prefix |
| V. Performance Requirements | PASS with exception | No async DB queries in current endpoints (stateless). Exception: Alembic migrations not needed (no DB models for this feature). Long-running document processing uses BackgroundTasks. |

**Exceptions justified:**
- No real Postgres test DB: Current endpoints are stateless processing — no database tables. DB infrastructure retained for future use.
- No Alembic migrations: No new database models. Knowledge base metadata stored in Pinecone, not Postgres.

## Project Structure

### Documentation (this feature)

```text
specs/002-assessment-engine/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── assessment.md
│   ├── knowledge-base.md
│   └── insights.md
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
app/
├── __init__.py
├── main.py                    # FastAPI app factory with Logfire instrumentation
├── core/
│   ├── __init__.py
│   ├── config.py              # Settings (existing + new: AI provider, Pinecone, Logfire)
│   ├── database.py            # Retained for future use (existing)
│   ├── auth.py                # JWT verification (existing, retained)
│   ├── ai_provider.py         # Pydantic AI agent factory — configurable provider
│   └── errors.py              # Consistent error response helpers
├── assessment/
│   ├── __init__.py
│   ├── schemas.py             # Scorecard, Criterion, AssessmentResult, AssessmentRequest
│   ├── router.py              # POST /api/v1/assessments
│   └── services.py            # AI evaluation logic, score calculation
├── knowledge_base/
│   ├── __init__.py
│   ├── schemas.py             # KBUploadResponse, KBQueryRequest/Response
│   ├── router.py              # POST /api/v1/knowledge-bases, POST /api/v1/knowledge-bases/{id}/documents
│   ├── services.py            # Document processing, chunking, embedding, Pinecone ops
│   └── parsers.py             # PDF, DOCX, TXT, Markdown file parsing
└── insights/
    ├── __init__.py
    ├── schemas.py             # InsightRequest, InsightReport
    ├── router.py              # POST /api/v1/insights
    └── services.py            # Cross-assessment analysis via AI

tests/
├── conftest.py                # Shared fixtures, mock AI provider, mock Pinecone
├── assessment/
│   ├── test_router.py
│   └── test_services.py
├── knowledge_base/
│   ├── test_router.py
│   ├── test_services.py
│   └── test_parsers.py
└── insights/
    ├── test_router.py
    └── test_services.py
```

**Structure Decision**: Module-first architecture per constitution. Each feature domain (assessment, knowledge_base, insights) is a self-contained module. No models.py needed in modules since there are no database tables — schemas.py handles all Pydantic request/response models. Shared AI provider configuration lives in `core/ai_provider.py`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| No models.py in feature modules | No database tables for this feature — all entities are transient (request/response) or stored in Pinecone | Adding empty models.py files would be dead code; constitution principle I says modules MUST contain models.py but this is for SQLAlchemy models which don't exist here |
| No Alembic migrations | No new DB schema changes | Constitution principle V requires migrations for model changes, but there are no model changes |
