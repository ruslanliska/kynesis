# Feature Specification: Supabase Auth Integration & User Profile

**Feature Branch**: `001-email-auth-profile`
**Created**: 2026-03-24
**Status**: Draft
**Input**: User description: "build a backend with fastapi, create auth please, so user can login with email, and get password, create some mock endpoint for user profile"

## Clarifications

### Session 2026-03-24

- Q: Email case sensitivity? → A: Case-insensitive — normalize to lowercase before storage and comparison.
- Q: Auth architecture? → A: Lovable Cloud handles frontend auth via Supabase Auth. FastAPI backend verifies Supabase-issued JWT tokens. No registration/login endpoints in backend.
- Q: Profile update capability? → A: Read + update — GET profile and PATCH to update display name.
- Q: Shared database? → A: FastAPI connects to the same Supabase Postgres database. Uses existing `public.profiles` table (auto-created by Supabase trigger on signup). No separate user table needed.
- Q: Database connection method? → A: Service role / direct connection — bypass RLS, enforce access control in application code.

### Session 2026-03-25

- Q: Core backend purpose? → A: FastAPI handles everything — scorecard CRUD, assessment processing, and insights analysis. Replace all Supabase Edge Functions for core functionality.
- Q: Who are the users? → A: QA managers scoring team interactions (calls, chats, code). Users upload knowledge bases, create AI agents tied to scorecards, and agents evaluate content producing structured output per scorecard schema.
- Q: AI provider for evaluation agents? → A: Configurable — support multiple providers (OpenAI, Anthropic, Gemini, etc.), user chooses per agent.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Authenticated API Access (Priority: P1)

A user who has logged in via the Lovable frontend (Supabase Auth) makes a request to the FastAPI backend. The backend extracts the Supabase JWT from the Authorization header, verifies it using the Supabase JWT secret (HS256), and identifies the user. If the token is valid, the request proceeds. If invalid or missing, the request is rejected.

**Why this priority**: Every protected endpoint depends on token verification. Without this, no backend functionality is accessible to authenticated users.

**Independent Test**: Can be tested by sending requests with valid Supabase JWTs, expired tokens, malformed tokens, and no token — verifying correct accept/reject behavior in each case.

**Acceptance Scenarios**:

1. **Given** a request with a valid Supabase JWT in the Authorization header, **When** the backend receives it, **Then** the request is processed and the user identity (UUID from `sub` claim, email) is available to the endpoint.
2. **Given** a request with an expired JWT, **When** the backend receives it, **Then** the system returns a 401 unauthorized response.
3. **Given** a request with a malformed or tampered JWT, **When** the backend receives it, **Then** the system returns a 401 unauthorized response.
4. **Given** a request with no Authorization header, **When** the backend receives it, **Then** the system returns a 401 unauthorized response.
5. **Given** a valid JWT with `aud` claim not equal to `"authenticated"`, **When** the backend receives it, **Then** the system returns a 401 unauthorized response.

---

### User Story 2 - View User Profile (Priority: P1)

An authenticated user requests their profile information from the backend. The system verifies the JWT, reads the user's record from the existing `public.profiles` table in the shared Supabase Postgres database, and returns their profile data.

**Why this priority**: Co-priority with auth — this is the first concrete protected endpoint and validates the entire auth flow end-to-end. The profiles table already exists (created by Supabase trigger on signup), so this is primarily a read operation.

**Independent Test**: Can be tested by authenticating a user, requesting the profile endpoint, and verifying the correct profile data is returned.

**Acceptance Scenarios**:

1. **Given** an authenticated user with an existing profile record, **When** they request their profile, **Then** the system returns their id, email, display name, and created date from `public.profiles`.
2. **Given** an authenticated user whose profile does not yet exist in `public.profiles` (edge case — trigger failure), **When** they request their profile, **Then** the system returns a 404 with a clear error message.
3. **Given** an unauthenticated request to the profile endpoint, **When** processed, **Then** the system returns a 401 unauthorized response.

---

### User Story 3 - Update User Profile (Priority: P2)

An authenticated user updates their display name via the backend. The system verifies the JWT, updates only the `display_name` field in the user's `public.profiles` record, and returns the updated profile. The `updated_at` timestamp is automatically set by the existing database trigger.

**Why this priority**: Allows users to personalize their profile. Lower priority than read because the display name is set during signup and updating is optional.

**Independent Test**: Can be tested by authenticating a user, sending a PATCH request with a new display name, and verifying the profile is updated and the `updated_at` timestamp changed.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they submit a valid display name update, **Then** the system updates their display name in `public.profiles` and returns the updated profile.
2. **Given** an authenticated user submits an empty or whitespace-only display name, **When** processed, **Then** the system returns a validation error.
3. **Given** an authenticated user submits a display name exceeding 100 characters, **When** processed, **Then** the system returns a validation error.
4. **Given** an unauthenticated request to update a profile, **When** processed, **Then** the system returns a 401 unauthorized response.

---

### Edge Cases

- What if the Supabase trigger that creates profiles fails and a user has a JWT but no profile record? The system MUST return a 404 — not create a profile (Supabase owns profile creation).
- What if the JWT email claim differs from the `public.profiles` email? The `public.profiles` email is set by the Supabase trigger and synced by Supabase — the backend reads it as-is and does NOT override it.
- How does the system handle a valid JWT for a Supabase user who was deleted? The token remains valid until expiration, but the profile query will return 404.
- What if the Supabase JWT secret is misconfigured? All requests MUST fail with 401 — the system MUST NOT fall through to unauthenticated access.
- What if the database connection to Supabase Postgres is unavailable? The system MUST return a 503 service unavailable response, not expose internal errors.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST verify Supabase-issued JWT tokens using the Supabase JWT secret with HS256 algorithm and `"authenticated"` audience claim.
- **FR-002**: System MUST extract user identity (UUID from `sub` claim, email) from verified JWT claims.
- **FR-003**: System MUST provide a protected GET endpoint that returns the authenticated user's profile from the existing `public.profiles` table.
- **FR-004**: System MUST provide a protected PATCH endpoint that allows the authenticated user to update their display name.
- **FR-005**: System MUST validate display name updates (non-empty, max 100 characters).
- **FR-006**: System MUST only allow users to read and update their own profile (scoped by Supabase UUID from JWT).
- **FR-007**: System MUST reject all requests to protected endpoints with a 401 status when no valid token is provided.
- **FR-008**: System MUST NOT implement registration, login, or password management endpoints — these are handled by Supabase Auth via the Lovable frontend.
- **FR-009**: System MUST NOT create or manage user records in `public.profiles` — profile creation is handled by the Supabase database trigger (`handle_new_user`).

### Key Entities

- **Profile** (existing `public.profiles` table): Represents a user's profile. Key attributes: id (UUID, references Supabase auth.users), display_name (text, optional), email (text, set by trigger), created_at (timestamp), updated_at (timestamp, auto-updated by trigger).
- **Access Token**: A Supabase-issued JWT containing user UUID (`sub` claim), email, audience (`aud: "authenticated"`), and expiration. Verified by the backend but never issued or stored by it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of requests with valid Supabase JWTs are correctly authenticated and processed.
- **SC-002**: 100% of requests with invalid, expired, or missing tokens are rejected with 401 responses.
- **SC-003**: Profile retrieval returns complete user data in under 1 second for authenticated users.
- **SC-004**: Profile updates persist correctly and the `updated_at` timestamp reflects the change.
- **SC-005**: Users can only access and modify their own profile — no cross-user data leakage.

## Assumptions

- Lovable Cloud handles the frontend and provisions Supabase Auth automatically.
- FastAPI connects to the **same Supabase Postgres database** — connection string from Supabase Settings → Database.
- The `public.profiles` table already exists with columns: `id` (UUID, PK, references auth.users), `display_name` (text), `email` (text), `created_at` (timestamptz), `updated_at` (timestamptz).
- The `handle_new_user` trigger automatically creates a profile row on Supabase signup.
- The `update_updated_at_column` trigger automatically sets `updated_at` on profile updates.
- FastAPI connects with a service role / direct database connection that bypasses RLS. Access control is enforced in application code by scoping all queries to the authenticated user's UUID.
- The Supabase JWT secret is available as an environment variable (`SUPABASE_JWT_SECRET`).
- Token refresh and session management are handled entirely by the Lovable frontend / Supabase client.
- Rate limiting is out of scope for v1 but recommended for production.
- HTTPS is assumed to be handled at the infrastructure level.
