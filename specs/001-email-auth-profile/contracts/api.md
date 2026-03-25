# API Contract: Supabase Auth Integration & User Profile

**Date**: 2026-03-24
**Base URL**: `/api/v1`
**Auth**: All endpoints require `Authorization: Bearer <supabase_jwt>` header

## Authentication

All protected endpoints use the `HTTPBearer` security scheme. The JWT is verified locally using the Supabase JWT secret (HS256, audience: `"authenticated"`).

**Error response** (all auth failures):
```json
{
  "detail": "Invalid or expired token"
}
```
Status: `401 Unauthorized`
Header: `WWW-Authenticate: Bearer`

---

## Endpoints

### GET /api/v1/profile

**Description**: Retrieve the authenticated user's profile.

**Auth**: Required

**Response 200**:
```json
{
  "id": "uuid-string",
  "email": "user@example.com",
  "display_name": "John Doe",
  "created_at": "2026-03-24T10:30:00Z",
  "updated_at": "2026-03-24T10:30:00Z"
}
```

**Response 401**: Invalid or missing token
```json
{
  "detail": "Invalid or expired token"
}
```

**Response 404**: Profile not found (Supabase trigger failure edge case)
```json
{
  "detail": "Profile not found"
}
```

---

### PATCH /api/v1/profile

**Description**: Update the authenticated user's display name.

**Auth**: Required

**Request body**:
```json
{
  "display_name": "New Name"
}
```

**Validation**:
- `display_name`: required, string, non-empty after trim, max 100 characters

**Response 200**: Updated profile
```json
{
  "id": "uuid-string",
  "email": "user@example.com",
  "display_name": "New Name",
  "created_at": "2026-03-24T10:30:00Z",
  "updated_at": "2026-03-24T11:00:00Z"
}
```

**Response 401**: Invalid or missing token
```json
{
  "detail": "Invalid or expired token"
}
```

**Response 404**: Profile not found
```json
{
  "detail": "Profile not found"
}
```

**Response 422**: Validation error
```json
{
  "detail": [
    {
      "loc": ["body", "display_name"],
      "msg": "String should have at most 100 characters",
      "type": "string_too_long"
    }
  ]
}
```

---

### GET /api/v1/health

**Description**: Health check endpoint (unauthenticated).

**Auth**: Not required

**Response 200**:
```json
{
  "status": "ok"
}
```

---

## Pydantic Schemas

### ProfileResponse
```
id: UUID
email: str
display_name: str | None
created_at: datetime
updated_at: datetime
```

### ProfileUpdate
```
display_name: str (min_length=1, max_length=100, stripped)
```

## Error Format

All errors follow FastAPI's default format:

- **Auth errors**: `{"detail": "string"}`
- **Validation errors**: `{"detail": [{"loc": [...], "msg": "string", "type": "string"}]}`
- **Not found**: `{"detail": "string"}`
- **Server errors**: `{"detail": "string"}` with 503 status for DB unavailability
