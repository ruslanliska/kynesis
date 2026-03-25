# Quickstart: Supabase Auth Integration & User Profile

**Date**: 2026-03-24
**Feature**: 001-email-auth-profile

## Prerequisites

- Python 3.13+
- Access to the Supabase project (Lovable Cloud)
- Supabase JWT secret (Settings → API → JWT Secret)
- Supabase database connection string (Settings → Database → Connection string URI)

## 1. Install Dependencies

```bash
pip install fastapi uvicorn sqlalchemy[asyncio] asyncpg python-jose[cryptography] pydantic-settings httpx
```

Or add to `pyproject.toml`:
```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.30.0",
    "python-jose[cryptography]>=3.3.0",
    "pydantic-settings>=2.0.0",
    "httpx>=0.28.0",
]
```

## 2. Configure Environment

Create `.env` in project root:
```env
SUPABASE_JWT_SECRET=your-jwt-secret-from-supabase-settings
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
ALLOWED_ORIGINS=https://your-lovable-app.lovable.app
```

## 3. Run the Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 4. Test Authentication

### Health check (no auth):
```bash
curl http://localhost:8000/api/v1/health
# {"status": "ok"}
```

### Get profile (with Supabase JWT):
```bash
curl -H "Authorization: Bearer <your-supabase-jwt>" \
  http://localhost:8000/api/v1/profile
```

### Update display name:
```bash
curl -X PATCH \
  -H "Authorization: Bearer <your-supabase-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "New Name"}' \
  http://localhost:8000/api/v1/profile
```

### Get a test JWT:
1. Log in via your Lovable frontend
2. Open browser DevTools → Application → Local Storage
3. Find the Supabase session key → copy `access_token`

## 5. Run Tests

```bash
pytest tests/ -v --asyncio-mode=auto
```

## Verification Checklist

- [ ] `GET /api/v1/health` returns `{"status": "ok"}`
- [ ] `GET /api/v1/profile` with valid JWT returns profile data
- [ ] `GET /api/v1/profile` without JWT returns 401
- [ ] `PATCH /api/v1/profile` updates display name and returns updated profile
- [ ] `PATCH /api/v1/profile` with empty display name returns 422
- [ ] `updated_at` changes after PATCH
