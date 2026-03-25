# Tasks: Supabase Auth Integration & User Profile

**Input**: Design documents from `/specs/001-email-auth-profile/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/api.md

**Tests**: Included per constitution Principle III (Testing Standards).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Project Initialization)

**Purpose**: Create project structure and declare dependencies

- [x] T001 Create project directory structure with all `__init__.py` files: `app/__init__.py`, `app/core/__init__.py`, `app/profile/__init__.py`, `tests/__init__.py`, `tests/core/__init__.py`, `tests/profile/__init__.py`
- [x] T002 [P] Add dependencies to `pyproject.toml`: fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, python-jose[cryptography], pydantic-settings, httpx; dev dependencies: pytest, pytest-asyncio, httpx
- [x] T003 [P] Create `.env.example` with required variables: `SUPABASE_JWT_SECRET`, `DATABASE_URL` (postgresql+asyncpg://...), `ALLOWED_ORIGINS`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Implement `Settings` class using pydantic-settings in `app/core/config.py` with fields: `SUPABASE_JWT_SECRET` (str), `DATABASE_URL` (str), `ALLOWED_ORIGINS` (list[str]); include `@lru_cache` `get_settings()` function; load from env vars with `.env` fallback
- [x] T005 [P] Implement async SQLAlchemy engine and session factory in `app/core/database.py`: `create_async_engine` with `pool_size=5`, `max_overflow=10`; `async_sessionmaker`; `get_db` async generator dependency; `Base` declarative base
- [x] T006 [P] Implement JWT verification dependency in `app/core/auth.py`: `HTTPBearer` security scheme; `get_current_user` dependency that decodes JWT with `python-jose` (HS256, audience="authenticated"), extracts `sub` (UUID) and `email`, returns typed dict; raises `HTTPException(401)` with `WWW-Authenticate: Bearer` header on failure
- [x] T007 Create FastAPI application in `app/main.py`: app instance with lifespan handler for DB engine disposal; `CORSMiddleware` with `ALLOWED_ORIGINS`, allow `Authorization` and `Content-Type` headers, allow `GET`/`PATCH`/`OPTIONS` methods; `GET /api/v1/health` endpoint returning `{"status": "ok"}`

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Authenticated API Access (Priority: P1)

**Goal**: Verify that Supabase JWTs are correctly validated and user identity is extracted from token claims

**Independent Test**: Send requests with valid JWTs, expired tokens, malformed tokens, missing tokens, and wrong audience — verify correct accept/reject behavior

### Tests for User Story 1

- [x] T008 [US1] Create shared test fixtures in `tests/conftest.py`: generate valid/expired/malformed test JWTs using `python-jose` with a test secret; create `async_client` fixture using `httpx.AsyncClient` with `ASGITransport`; create `mock_db_session` fixture; override `get_settings` dependency with test config; override `get_db` dependency with test session
- [x] T009 [US1] Write JWT verification tests in `tests/core/test_auth.py`: test valid token returns user dict with `sub` and `email`; test expired token raises 401; test malformed token raises 401; test missing Authorization header raises 401 (via test endpoint); test token with wrong audience raises 401; test tampered token raises 401

**Checkpoint**: Auth verification is proven to work correctly in isolation

---

## Phase 4: User Story 2 — View User Profile (Priority: P1)

**Goal**: Authenticated users can retrieve their profile data from the existing `public.profiles` table

**Independent Test**: Authenticate a user, request GET /api/v1/profile, verify correct profile data (id, email, display_name, created_at, updated_at) is returned; verify 404 when profile missing; verify 401 without token

### Implementation for User Story 2

- [x] T010 [US2] Create Profile SQLAlchemy model in `app/profile/models.py`: map to existing `public.profiles` table with `__tablename__ = "profiles"` and `__table_args__ = {"schema": "public"}`; columns: `id` (UUID, PK), `display_name` (Text, nullable), `email` (Text, not null), `created_at` (DateTime with timezone), `updated_at` (DateTime with timezone)
- [x] T011 [P] [US2] Create Pydantic schemas in `app/profile/schemas.py`: `ProfileResponse` with `id` (UUID), `email` (str), `display_name` (str | None), `created_at` (datetime), `updated_at` (datetime); configure `model_config = ConfigDict(from_attributes=True)`
- [x] T012 [US2] Implement `get_profile_by_id` service function in `app/profile/services.py`: accept `AsyncSession` and `user_id` (UUID), query `Profile` by id, return `Profile | None`
- [x] T013 [US2] Implement GET `/api/v1/profile` endpoint in `app/profile/router.py`: create `APIRouter(prefix="/api/v1", tags=["profile"])`; endpoint uses `Depends(get_current_user)` and `Depends(get_db)`; calls `get_profile_by_id` with user UUID from JWT `sub` claim; returns `ProfileResponse`; raises `HTTPException(404, "Profile not found")` if None; register router in `app/main.py`

### Tests for User Story 2

- [ ] T014 [P] [US2] Write profile service unit tests in `tests/profile/test_services.py`: test `get_profile_by_id` returns profile when exists (mock session); test returns None when profile not found
- [ ] T015 [US2] Write GET /api/v1/profile integration tests in `tests/profile/test_router.py`: test 200 with valid token returns profile data; test 404 when profile record missing; test 401 without token; test 401 with expired token

**Checkpoint**: User Story 2 is fully functional — authenticated users can view their profile

---

## Phase 5: User Story 3 — Update User Profile (Priority: P2)

**Goal**: Authenticated users can update their display name via PATCH endpoint

**Independent Test**: Authenticate a user, send PATCH /api/v1/profile with new display_name, verify profile is updated and updated_at changed; verify validation errors for empty/too-long names; verify 401 without token

### Implementation for User Story 3

- [ ] T016 [US3] Add `ProfileUpdate` Pydantic schema in `app/profile/schemas.py`: `display_name` field with `min_length=1`, `max_length=100`; add `@field_validator` to strip whitespace
- [ ] T017 [US3] Add `update_display_name` service function in `app/profile/services.py`: accept `AsyncSession`, `user_id` (UUID), and `display_name` (str); query profile by id, update `display_name`, commit, refresh, return updated `Profile | None`; return None if profile not found
- [ ] T018 [US3] Implement PATCH `/api/v1/profile` endpoint in `app/profile/router.py`: accept `ProfileUpdate` body; uses `Depends(get_current_user)` and `Depends(get_db)`; calls `update_display_name`; returns `ProfileResponse`; raises `HTTPException(404, "Profile not found")` if None

### Tests for User Story 3

- [ ] T019 [P] [US3] Add update service unit tests in `tests/profile/test_services.py`: test `update_display_name` updates and returns profile; test returns None when profile not found
- [ ] T020 [US3] Add PATCH /api/v1/profile integration tests in `tests/profile/test_router.py`: test 200 with valid update returns updated profile; test 422 with empty display_name; test 422 with display_name > 100 chars; test 404 when profile missing; test 401 without token

**Checkpoint**: All user stories are independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end validation and cleanup

- [ ] T021 [P] Run quickstart.md verification checklist end-to-end against running server
- [ ] T022 [P] Verify constitution compliance: module boundaries (Principle I), type hints on all signatures (Principle II), Pydantic response schemas on all endpoints (Principle IV), async-only database calls (Principle V)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational phase completion
- **US2 (Phase 4)**: Depends on Foundational phase completion (can run parallel with US1 tests)
- **US3 (Phase 5)**: Depends on US2 implementation (extends same router/service/schema files)
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Auth verification — foundation for all other stories. Tests validate auth works.
- **User Story 2 (P1)**: GET profile — depends on auth (Phase 2) but NOT on US1 tests. First protected endpoint.
- **User Story 3 (P2)**: PATCH profile — extends US2's model/service/router/schema files. Must follow US2.

### Within Each User Story

- Models before services
- Schemas can be parallel with models (different files)
- Services before endpoints
- Implementation before integration tests
- Unit tests can be parallel with implementation (different files)

### Parallel Opportunities

- T002 + T003 (Setup: pyproject.toml + .env.example)
- T005 + T006 (Foundational: database + auth — different files)
- T011 + T010 (US2: schemas + models — different files)
- T014 parallel with T013 (US2: unit tests + endpoint — different files)
- T019 parallel with T018 (US3: unit tests + endpoint — different files)
- T021 + T022 (Polish: quickstart check + compliance check)

---

## Parallel Example: User Story 2

```bash
# Launch model and schemas together:
Task: "Create Profile model in app/profile/models.py"
Task: "Create ProfileResponse schema in app/profile/schemas.py"

# Then service (depends on model):
Task: "Implement get_profile_by_id in app/profile/services.py"

# Then endpoint + unit tests together:
Task: "Implement GET /api/v1/profile in app/profile/router.py"
Task: "Write profile service unit tests in tests/profile/test_services.py"

# Finally integration tests (depend on endpoint):
Task: "Write GET /api/v1/profile integration tests in tests/profile/test_router.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 2)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: US1 (auth tests prove JWT verification works)
4. Complete Phase 4: US2 (GET profile — first real endpoint)
5. **STOP and VALIDATE**: Test GET /api/v1/profile with real Supabase JWT
6. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add US1 + US2 → Test end-to-end → Deploy/Demo (MVP!)
3. Add US3 → Test PATCH endpoint → Deploy/Demo
4. Polish phase → Final validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- The `public.profiles` table already exists — no migration tasks needed
