<!--
Sync Impact Report
- Version change: 0.0.0 → 1.0.0 (initial ratification)
- Added principles:
  - I. Module-First Architecture
  - II. Code Quality
  - III. Testing Standards
  - IV. API Consistency
  - V. Performance Requirements
- Added sections:
  - Technology Stack & Constraints
  - Development Workflow
  - Governance
- Templates requiring updates:
  - .specify/templates/plan-template.md ✅ no updates needed (generic)
  - .specify/templates/spec-template.md ✅ no updates needed (generic)
  - .specify/templates/tasks-template.md ✅ no updates needed (generic)
  - .specify/templates/commands/ ✅ no command files exist
- Follow-up TODOs: none
-->

# Kynesis Constitution

## Core Principles

### I. Module-First Architecture

Every feature MUST be organized as a self-contained module
(directory) containing its own models, schemas, router, and
services files. A module represents a bounded domain concept.

- Each module directory MUST contain:
  - `models.py` — SQLAlchemy async models
  - `schemas.py` — Pydantic request/response schemas
  - `router.py` — FastAPI router with endpoint definitions
  - `services.py` — Business logic layer
- Cross-module imports MUST flow through explicit public
  interfaces (importing from the module's `__init__.py` or
  directly from the specific file).
- No circular dependencies between modules. If two modules
  depend on each other, extract shared logic into a common
  module or restructure.
- Shared infrastructure (database session, config, middleware,
  exceptions) lives outside feature modules in a `core/` or
  `common/` package.

### II. Code Quality

All code MUST be clear, consistent, and maintainable.

- Type hints MUST be used on all function signatures and
  return types. Pydantic models enforce runtime validation
  at API boundaries.
- Async/await MUST be used consistently — no mixing of sync
  and async database calls within the same request path.
- Functions MUST do one thing. Service functions MUST NOT
  contain router logic; routers MUST NOT contain business
  logic or direct database queries.
- No raw SQL strings in service or router code. All database
  access MUST go through SQLAlchemy async ORM or Core
  expressions.
- Dependencies MUST be injected via FastAPI's `Depends()`
  mechanism for database sessions, auth, and shared services.
- Unused imports, dead code, and commented-out code MUST NOT
  be committed.

### III. Testing Standards

Every feature MUST include tests that verify correctness at
appropriate layers.

- Unit tests MUST cover service-layer business logic in
  isolation (mock database dependencies).
- Integration tests MUST verify endpoint behavior against a
  real async Postgres test database using `httpx.AsyncClient`.
- Each endpoint MUST have at least one happy-path and one
  error-path test.
- Tests MUST be async (`pytest-asyncio`) and MUST NOT use
  synchronous database connections.
- Test files MUST mirror the module structure:
  `tests/<module_name>/test_services.py`,
  `tests/<module_name>/test_router.py`.
- Fixtures for database sessions, test client, and test data
  MUST be defined in `conftest.py` files and reused across
  test modules.

### IV. API Consistency

All API endpoints MUST follow a uniform contract so that
consumers experience predictable behavior.

- All endpoints MUST return Pydantic response schemas — never
  raw dicts or ORM objects.
- Error responses MUST use a consistent shape:
  `{"detail": "<message>"}` with appropriate HTTP status codes.
- Pagination MUST use `limit`/`offset` query parameters with
  a consistent response envelope containing `items`, `total`,
  `limit`, and `offset`.
- Naming conventions: plural nouns for resource collections
  (`/users`, `/orders`), nested routes for sub-resources
  (`/users/{id}/orders`).
- All request body and query parameter validation MUST be
  handled by Pydantic schemas in `schemas.py`, not by manual
  checks in router or service code.
- API versioning (if needed) MUST use URL prefix (`/api/v1/`).

### V. Performance Requirements

The application MUST meet performance targets suitable for a
production async Python backend.

- Database queries MUST use async drivers (`asyncpg` via
  SQLAlchemy async engine). No synchronous I/O on the request
  path.
- N+1 query patterns are prohibited. Use `selectinload` or
  `joinedload` for eager loading of relationships.
- Endpoints that return lists MUST support pagination and MUST
  NOT return unbounded result sets.
- Database migrations MUST use Alembic with async support.
  Every model change MUST have a corresponding migration.
- Connection pooling MUST be configured via SQLAlchemy async
  engine settings (`pool_size`, `max_overflow`).
- Long-running operations MUST be offloaded to background
  tasks (FastAPI `BackgroundTasks` or a task queue), not
  handled inline in request handlers.

## Technology Stack & Constraints

- **Language**: Python 3.13+
- **Framework**: FastAPI (latest stable)
- **ORM**: SQLAlchemy 2.x with async extension
- **Database**: PostgreSQL (async via `asyncpg`)
- **Schemas**: Pydantic v2
- **Migrations**: Alembic (async)
- **Testing**: pytest + pytest-asyncio + httpx
- **Project structure**: Module-level (each feature is a
  directory with models, schemas, router, services)

All dependencies MUST be declared in `pyproject.toml`. No
implicit or undeclared dependencies.

## Development Workflow

- All code changes MUST pass linting and type checking before
  merge.
- Every pull request MUST include tests for new or changed
  behavior.
- Database migrations MUST be reviewed for correctness and
  reversibility.
- Code review MUST verify compliance with this constitution,
  particularly module boundaries (Principle I) and async
  consistency (Principle II).
- Feature branches MUST be based on `main` and merged via
  pull request.

## Governance

This constitution is the authoritative source for project
standards. All development decisions MUST comply with the
principles defined above.

- **Amendments**: Any change to this constitution MUST be
  documented with a version bump, rationale, and updated
  date. Breaking changes to principles require MAJOR version
  increment.
- **Compliance**: All pull requests and code reviews MUST
  verify adherence to these principles.
- **Exceptions**: Deviations from any principle MUST be
  documented in the relevant spec or plan with explicit
  justification and approval.
- **Versioning**: MAJOR.MINOR.PATCH — MAJOR for principle
  removals/redefinitions, MINOR for new principles or
  material expansions, PATCH for clarifications.

**Version**: 1.0.0 | **Ratified**: 2026-03-24 | **Last Amended**: 2026-03-24
