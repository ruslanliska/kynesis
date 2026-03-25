# Implementation Plan: Supabase Auth Integration & User Profile

**Branch**: `001-email-auth-profile` | **Date**: 2026-03-24 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-email-auth-profile/spec.md`

## Summary

Build FastAPI backend authentication and profile endpoints that integrate with an existing Supabase Auth system (managed by Lovable Cloud). The backend verifies Supabase-issued JWTs locally using HS256, reads/writes the existing `public.profiles` table in the shared Supabase Postgres database, and exposes GET/PATCH profile endpoints. No registration or login endpoints — auth is fully handled by the frontend.

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: FastAPI, SQLAlchemy 2.x (async), python-jose[cryptography], Pydantic v2, asyncpg
**Storage**: PostgreSQL (Supabase-hosted, shared with Lovable frontend, accessed via direct connection bypassing RLS)
**Testing**: pytest + pytest-asyncio + httpx
**Target Platform**: Linux server / cloud deployment
**Project Type**: Web service (async API backend)
**Performance Goals**: <1s response time for all endpoints (SC-003, SC-004)
**Constraints**: Async-only I/O, no sync database calls, service role DB connection
**Scale/Scope**: Single-user profile operations, low scale for v1

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Module-First Architecture | ✅ PASS | `core/` for shared infra (auth, db, config), `profile/` module with models/schemas/router/services |
| II. Code Quality | ✅ PASS | Type hints on all signatures, async/await throughout, Depends() for DI, no raw SQL |
| III. Testing Standards | ✅ PASS | Unit tests for services, integration tests for endpoints, async test client |
| IV. API Consistency | ✅ PASS | Pydantic response schemas, `{"detail": "..."}` error format, `/api/v1/` prefix |
| V. Performance | ✅ PASS (with justified exception) | Async asyncpg driver, connection pooling configured |

**Justified Exception — Alembic Migrations (Principle V)**:
The constitution requires Alembic migrations for every model change. However, the `public.profiles` table is **owned and managed by Supabase** (created by the `handle_new_user` trigger). We map to it as a read/write target using SQLAlchemy, but do NOT create or migrate it. Alembic will be configured for future application-owned tables but will NOT manage Supabase-owned tables.

## Project Structure

### Documentation (this feature)

```text
specs/001-email-auth-profile/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.md
└── tasks.md
```

### Source Code (repository root)

```text
app/
├── __init__.py
├── main.py                    # FastAPI app, CORS, router includes
├── core/
│   ├── __init__.py
│   ├── config.py              # Pydantic Settings (env vars)
│   ├── database.py            # Async SQLAlchemy engine + session
│   └── auth.py                # JWT verification dependency
└── profile/
    ├── __init__.py
    ├── models.py              # SQLAlchemy model for public.profiles
    ├── schemas.py             # Pydantic request/response schemas
    ├── router.py              # GET /api/v1/profile, PATCH /api/v1/profile
    └── services.py            # Profile read/update business logic

tests/
├── conftest.py                # Async fixtures: db session, test client, auth mock
├── core/
│   └── test_auth.py           # JWT verification tests
└── profile/
    ├── test_services.py       # Unit tests for profile service
    └── test_router.py         # Integration tests for profile endpoints
```

**Structure Decision**: Module-first layout per constitution. `core/` holds shared infrastructure (auth, database, config). `profile/` is a self-contained feature module. Frontend is managed separately by Lovable Cloud — not part of this repository.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| No Alembic migration for profiles | Table owned by Supabase trigger | Creating a duplicate migration would conflict with Supabase's schema management |
