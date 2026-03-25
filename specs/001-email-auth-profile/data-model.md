# Data Model: Supabase Auth Integration & User Profile

**Date**: 2026-03-24
**Feature**: 001-email-auth-profile

## Entities

### Profile (existing table: `public.profiles`)

**Owner**: Supabase (created by `handle_new_user` trigger on `auth.users` INSERT)
**Backend role**: Read/write consumer (NOT owner — do not migrate)

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK, references auth.users(id) ON DELETE CASCADE | Supabase user UUID |
| display_name | TEXT | nullable | Set from `user_metadata.display_name` on signup |
| email | TEXT | not null | Set from `NEW.email` on signup, lowercase |
| created_at | TIMESTAMPTZ | not null, default now() | Auto-set on insert |
| updated_at | TIMESTAMPTZ | not null, default now() | Auto-updated by `update_updated_at_column` trigger |

**Indexes** (managed by Supabase):
- Primary key on `id`

**RLS policies** (managed by Supabase, bypassed by backend service role):
- `SELECT`: Users can view own profile (`auth.uid() = id`)
- `UPDATE`: Users can update own profile (`auth.uid() = id`)
- `INSERT`: Restricted to trigger (with check true for early_access)

### JWT Claims (not persisted — in-memory only)

Extracted from Supabase-issued JWT on each request.

| Claim | Type | Description |
|-------|------|-------------|
| sub | UUID string | Supabase user UUID (maps to profiles.id) |
| email | string | User's email address |
| aud | string | Must be `"authenticated"` |
| exp | integer | Token expiration (Unix timestamp) |
| iat | integer | Token issued at (Unix timestamp) |
| role | string | Supabase role (always `"authenticated"` for logged-in users) |

## Relationships

```text
auth.users (Supabase-managed)
    │
    │ 1:1 (ON DELETE CASCADE)
    │
    ▼
public.profiles (Supabase trigger creates, backend reads/writes)
```

## State Transitions

The `public.profiles` entity has no explicit state machine. It is:
1. **Created** automatically by Supabase trigger when a user signs up
2. **Read** by the backend on GET profile requests
3. **Updated** by the backend on PATCH profile requests (display_name only)
4. **Deleted** automatically by CASCADE when Supabase user is deleted

## Validation Rules

| Field | Rule | Source |
|-------|------|--------|
| display_name | Non-empty after trim, max 100 characters | FR-005 |
| email | Read-only from backend perspective — synced by Supabase | FR-009 |
| id | Read-only — set by Supabase, used as lookup key from JWT `sub` | FR-006 |
