# Research: Supabase Auth Integration & User Profile

**Date**: 2026-03-24
**Feature**: 001-email-auth-profile

## R1: Supabase JWT Verification in FastAPI

**Decision**: Use `python-jose[cryptography]` for local HS256 JWT verification.

**Rationale**: Local verification is faster (no network call per request), works offline from Supabase API, and is the standard approach for backend services. The Supabase JWT secret is a symmetric HS256 key available in Supabase Settings → API → JWT Secret.

**Alternatives considered**:
- Remote verification via `GET /auth/v1/user` (Supabase API call per request): Adds ~50-200ms latency per request, creates Supabase API dependency on the request path. Rejected.
- JWKS-based RS256 verification: Supabase uses HS256 by default, not RS256. Would require Supabase configuration changes. Rejected.

**Implementation details**:
- Decode JWT with `python-jose`: `jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")`
- Extract `sub` (user UUID) and `email` from claims
- FastAPI dependency via `Depends()` pattern using `HTTPBearer` security scheme

## R2: SQLAlchemy Async with Existing Supabase Table

**Decision**: Map SQLAlchemy async model to existing `public.profiles` table using `__tablename__ = "profiles"` and `__table_args__ = {"schema": "public"}`. Do NOT use Alembic to manage this table.

**Rationale**: The `public.profiles` table is created and owned by Supabase's `handle_new_user` trigger. Our backend is a consumer of this table, not its owner. SQLAlchemy can map to existing tables without needing to create them.

**Alternatives considered**:
- Create a separate `backend_users` table: Adds unnecessary data duplication and sync complexity. Rejected.
- Use raw SQL queries instead of SQLAlchemy: Violates constitution Principle II (no raw SQL). Rejected.

**Implementation details**:
- Use `mapped_column()` with SQLAlchemy 2.x declarative style
- Connection string: `postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>`
- Service role connection bypasses RLS — all access control in application code
- Configure `pool_size=5`, `max_overflow=10` for connection pooling

## R3: Database Connection to Supabase Postgres

**Decision**: Use Supabase direct connection string (not pooler) with service role credentials.

**Rationale**: Direct connection provides full access bypassing RLS. For a backend with moderate concurrency, direct connection with SQLAlchemy's built-in connection pooling is simpler than Supabase's pgBouncer pooler.

**Alternatives considered**:
- Supabase connection pooler (pgBouncer): Adds transaction pooling complexity. Useful at high scale but unnecessary for v1. Can switch later.
- Anon key with RLS: Would require passing JWT to Postgres via `set_config`, adding complexity. Rejected per clarification decision.

**Implementation details**:
- Connection string from Supabase Settings → Database → Connection string (URI)
- Store as `DATABASE_URL` environment variable
- Use `create_async_engine` with `echo=False` in production

## R4: CORS Configuration

**Decision**: Configure CORS middleware to allow requests from the Lovable Cloud frontend origin.

**Rationale**: The FastAPI backend and Lovable frontend run on different origins. CORS headers must allow the frontend to send authenticated requests with Authorization headers.

**Alternatives considered**:
- Proxy through Lovable: Not supported by Lovable Cloud architecture. Rejected.
- Allow all origins (`*`): Insecure for authenticated endpoints. Rejected for production.

**Implementation details**:
- Use `CORSMiddleware` with explicit `allow_origins` list
- Allow `Authorization` and `Content-Type` headers
- Allow `GET`, `PATCH`, `OPTIONS` methods
- Frontend origin stored as `ALLOWED_ORIGINS` environment variable

## R5: Pydantic Settings for Configuration

**Decision**: Use `pydantic-settings` for environment variable management.

**Rationale**: Provides type-safe configuration with validation, `.env` file support, and integrates naturally with FastAPI's dependency injection.

**Implementation details**:
- `Settings` class with `SUPABASE_JWT_SECRET`, `DATABASE_URL`, `ALLOWED_ORIGINS`
- Load from environment variables with `.env` file fallback
- Inject via `Depends(get_settings)` using `@lru_cache` for singleton pattern
