# kynesis Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-25

## Active Technologies
- Python 3.13+ + FastAPI, Pydantic AI, Pinecone SDK, Pydantic Logfire, python-multipart (file uploads), pypdf/python-docx/markdown (document parsing) (002-assessment-engine)
- Pinecone (vector DB for knowledge base embeddings); SQLAlchemy async + asyncpg retained for future use (not used by current endpoints) (002-assessment-engine)

- Python 3.13+ + FastAPI, SQLAlchemy 2.x (async), python-jose[cryptography], Pydantic v2, asyncpg (001-email-auth-profile)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.13+: Follow standard conventions

## Recent Changes
- 002-assessment-engine: Added Python 3.13+ + FastAPI, Pydantic AI, Pinecone SDK, Pydantic Logfire, python-multipart (file uploads), pypdf/python-docx/markdown (document parsing)

- 001-email-auth-profile: Added Python 3.13+ + FastAPI, SQLAlchemy 2.x (async), python-jose[cryptography], Pydantic v2, asyncpg

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
