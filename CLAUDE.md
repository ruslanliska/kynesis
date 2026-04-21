# kynesis Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-20

## Active Technologies
- Python 3.13+ + FastAPI, Pydantic AI, Pinecone SDK, Pydantic Logfire, python-multipart (file uploads), pypdf/python-docx/markdown (document parsing) (002-assessment-engine)
- Pinecone (vector DB for knowledge base embeddings); SQLAlchemy async + asyncpg retained for future use (not used by current endpoints) (002-assessment-engine)
- Python 3.13+ + FastAPI, LangChain (`langchain-deepseek`, `langchain-openai`, `langchain-core`), Pydantic v2, LangSmith (already in `pyproject.toml`; enabled via `LANGSMITH__TRACING=true` in `.env`), Logfire, Pinecone SDK (003-reasoning-aggregation)
- N/A (stateless feature; reuses feature-002 Pinecone for optional RAG context) (003-reasoning-aggregation)
- Python 3.13+ + FastAPI, LangChain (`langchain-openai` for vision via `ChatOpenAI`, `langchain-deepseek` unchanged), Pydantic v2, Logfire, LangSmith, Pinecone SDK, `python-multipart` for image upload (already installed) (004-image-assessment)
- N/A — stateless feature. Pinecone reused read-only for optional RAG context (feature 002). (004-image-assessment)

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
- 004-image-assessment: Added Python 3.13+ + FastAPI, LangChain (`langchain-openai` for vision via `ChatOpenAI`, `langchain-deepseek` unchanged), Pydantic v2, Logfire, LangSmith, Pinecone SDK, `python-multipart` for image upload (already installed)
- 003-reasoning-aggregation: Added Python 3.13+ + FastAPI, LangChain (`langchain-deepseek`, `langchain-openai`, `langchain-core`), Pydantic v2, LangSmith (already in `pyproject.toml`; enabled via `LANGSMITH__TRACING=true` in `.env`), Logfire, Pinecone SDK
- 002-assessment-engine: Added Python 3.13+ + FastAPI, Pydantic AI, Pinecone SDK, Pydantic Logfire, python-multipart (file uploads), pypdf/python-docx/markdown (document parsing)


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
