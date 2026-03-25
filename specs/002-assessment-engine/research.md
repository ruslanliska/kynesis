# Research: Assessment Processing Engine

**Date**: 2026-03-25
**Branch**: `002-assessment-engine`

## 1. Pydantic AI — Agent Framework

**Decision**: Use `pydantic-ai` as the AI agent framework for structured assessment output.

**Rationale**:
- First-class structured output via `result_type` (Pydantic model) — agent validates LLM output against schema and auto-retries on validation failure
- Model-agnostic: define agent once (tools, prompts, result type), swap providers at runtime via `agent.run(..., model='openai:gpt-4o')`
- Built-in dependency injection via `deps_type` — bridges FastAPI `Depends()` to agent context via `RunContext`
- Native Logfire integration — `logfire.instrument_pydantic_ai()` auto-traces all agent runs, LLM calls, tool calls, retries
- `result_validator` decorator for custom business logic validation (e.g., weighted score consistency)
- `retries` parameter on Agent constructor controls retry loop for both Pydantic validation and custom validator failures

**Key patterns**:
- Agent creation: `Agent('openai:gpt-4o', result_type=ScorecardResult, system_prompt='...', retries=3)`
- Runtime model override: `await agent.run(prompt, model='anthropic:claude-sonnet-4-20250514', deps=deps)`
- Dynamic system prompts via `@agent.system_prompt` decorator accessing `ctx.deps`
- Error handling: catch `UnexpectedModelBehavior`, `UsageLimitExceeded`, httpx errors

**Alternatives considered**:
- LangChain: Heavier, more complex, not needed for structured output use case
- Direct OpenAI/Anthropic SDK: No built-in structured output validation, no multi-provider abstraction
- CrewAI: Multi-agent framework, overkill for single-agent evaluation tasks

**Installation**: `pip install pydantic-ai` (or `pydantic-ai-slim[openai,anthropic,gemini]` for selective providers)

---

## 2. Pinecone — Vector Database for Knowledge Base RAG

**Decision**: Use Pinecone Serverless with one index and namespaces per knowledge base.

**Rationale**:
- Serverless auto-scales, pay-per-usage, no infrastructure management
- Namespaces provide clean KB isolation — each `knowledge_base_id` gets its own namespace
- Efficient queries (Pinecone only scans vectors in target namespace)
- Easy KB deletion: `index.delete(delete_all=True, namespace=kb_id)`
- Metadata filtering available for document-level operations within a namespace

**Key patterns**:
- SDK v5+: `from pinecone import Pinecone; pc = Pinecone(api_key="...")`
- Async support: `PineconeAsyncio` class or `asyncio.to_thread()` fallback
- Upsert with metadata: `index.upsert(vectors=[...], namespace=kb_id)`
- Query: `index.query(vector=query_emb, top_k=5, namespace=kb_id, include_metadata=True)`
- Document replacement: delete by metadata filter `{"document_id": {"$eq": doc_id}}`, then re-upsert
- Batch upsert: 100 vectors per batch

**Index configuration**:
- Metric: cosine
- Dimensions: 1536 (matching text-embedding-3-small)
- Spec: ServerlessSpec(cloud="aws", region="us-east-1")

**Alternatives considered**:
- pgvector: Would require Postgres access (Lovable doesn't expose credentials)
- ChromaDB: Good for local/dev but no managed serverless offering
- Weaviate: More complex, kubernetes-oriented
- Qdrant: Good alternative but Pinecone was user's explicit choice

**Installation**: `pip install pinecone`

---

## 3. Embedding Model

**Decision**: OpenAI `text-embedding-3-small` (1536 dimensions)

**Rationale**:
- Best price/performance ratio (~$0.02 per 1M tokens)
- 1536 dimensions — good balance of quality and storage cost
- Successor to ada-002 with better quality at lower cost
- Supports Matryoshka dimensionality reduction if needed later
- OpenAI SDK already available via Pydantic AI dependency

**Alternatives considered**:
- `text-embedding-3-large` (3072 dims): Higher quality but 6.5x more expensive, unnecessary for QA docs
- `text-embedding-ada-002`: Legacy, deprecated in favor of v3 models
- Cohere `embed-v3`: Good but adds another API dependency
- Local sentence-transformers: Free but requires GPU, adds deployment complexity

**Installation**: OpenAI SDK included via `pydantic-ai[openai]`

---

## 4. Document Processing Pipeline

**Decision**: Use `pymupdf` for PDF, `python-docx` for DOCX, `langchain-text-splitters` for chunking.

**Rationale**:
- `pymupdf` (fitz): Fast, handles complex PDF layouts, extracts text + tables
- `python-docx`: Standard, reliable DOCX parsing
- `langchain-text-splitters`: Standalone package (no full LangChain needed), provides `RecursiveCharacterTextSplitter` with configurable separators
- Markdown and TXT: Built-in Python, no extra deps needed

**Chunking strategy**:
- Chunk size: 800 characters (~200-300 tokens), suitable for QA criteria documents
- Overlap: 80 characters (~10%)
- Separators: `["\n\n", "\n", ". ", " ", ""]` (section → paragraph → sentence)
- QA docs are dense and structured — smaller chunks preserve criterion-level precision

**Pipeline flow**:
```
Upload → Parse (extract text) → Clean → Chunk → Embed → Upsert to Pinecone
```

**Installation**: `pip install pymupdf python-docx langchain-text-splitters`

---

## 5. Pydantic Logfire — Observability

**Decision**: Use Logfire for full observability — HTTP traces, AI agent traces, custom spans.

**Rationale**:
- Native integration with both FastAPI and Pydantic AI — two `instrument_*()` calls cover most tracing
- Built on OpenTelemetry — can export to any OTEL-compatible backend if needed
- `instrument_fastapi(app)`: auto-traces HTTP requests, route info, status codes, Pydantic validation errors
- `instrument_pydantic_ai()`: auto-traces agent runs, LLM calls with token counts, tool calls, retries, result validation
- Custom spans via `logfire.span()` and `@logfire.instrument()` for document processing, embedding generation, vector search

**Configuration**:
- `LOGFIRE_TOKEN` env var for cloud backend
- `LOGFIRE_SEND_TO_LOGFIRE=false` for local dev (console output only)
- `logfire.configure(service_name="kynesis-api")` in app startup

**Manual instrumentation needed for**:
- Document chunking/processing pipeline
- Embedding generation batches
- Pinecone vector operations (upsert, query, delete)

**Installation**: `pip install logfire[fastapi]`

---

## 6. AI Provider Configuration

**Decision**: Server-side configuration via environment variables. Single active provider, swappable without code changes.

**Rationale**:
- Spec requires server-side configuration, not per-request
- Pydantic AI supports runtime model override: store model string in config, pass to `agent.run(model=...)`
- API keys per provider via env vars: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`

**Settings pattern**:
```python
class Settings(BaseSettings):
    AI_MODEL: str = "openai:gpt-4o"  # Pydantic AI model string
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
```

**No fallback chain for v1** — single configured provider. Fallback across providers adds complexity; better to monitor and alert on provider failures via Logfire.

---

## 7. File Upload Handling

**Decision**: Use FastAPI `UploadFile` with `python-multipart` for file uploads.

**Rationale**:
- FastAPI's built-in file upload support via `UploadFile` (async, streaming)
- `python-multipart` is required by FastAPI for form/file parsing
- Validate file size and format before processing
- Process in-memory for files ≤10MB (spec limit)

**Installation**: `pip install python-multipart`

---

## Dependencies Summary

**Production**:
```
fastapi>=0.115.0
uvicorn>=0.34.0
pydantic-settings>=2.0.0
pydantic-ai
pinecone
logfire[fastapi]
pymupdf
python-docx
langchain-text-splitters
python-multipart
httpx>=0.28.0
sqlalchemy[asyncio]>=2.0.0   # retained for future use
asyncpg>=0.30.0              # retained for future use
python-jose[cryptography]>=3.3.0  # retained for future use
```

**Dev**:
```
pytest>=8.0.0
pytest-asyncio>=0.24.0
httpx>=0.28.0
```
