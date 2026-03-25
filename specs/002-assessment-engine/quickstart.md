# Quickstart: Assessment Processing Engine

**Date**: 2026-03-25
**Branch**: `002-assessment-engine`

## Prerequisites

1. Python 3.13+
2. Pinecone account with API key
3. At least one AI provider API key (OpenAI, Anthropic, or Google)
4. (Optional) Logfire account for observability

## Environment Setup

```bash
# .env file
AI_MODEL=openai:gpt-4o
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=pc-...
PINECONE_INDEX_NAME=kynesis-kb
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
LOGFIRE_TOKEN=...                    # optional
LOGFIRE_SEND_TO_LOGFIRE=false        # set true for cloud

# Retained from 001 (not used by current endpoints)
SUPABASE_JWT_SECRET=your-jwt-secret
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
ALLOWED_ORIGINS=["http://localhost:5173"]
```

## Install & Run

```bash
cd /Users/ruslan.liska/PycharmProjects/kynesis/kynesis
uv sync                    # install dependencies
uvicorn app.main:app --reload --port 8000
```

## Integration Scenarios

### Scenario 1: Run Assessment (no knowledge base)

```bash
curl -X POST http://localhost:8000/api/v1/assessments \
  -H "Content-Type: application/json" \
  -d '{
    "scorecard": {
      "id": "sc-1",
      "name": "Support QA",
      "description": "Evaluate support calls",
      "criteria": [
        {"id": "c1", "name": "Greeting", "description": "Proper greeting", "weight": 3, "max_score": 10},
        {"id": "c2", "name": "Resolution", "description": "Issue resolved", "weight": 5, "max_score": 10},
        {"id": "c3", "name": "Closing", "description": "Proper closing", "weight": 2, "max_score": 10}
      ]
    },
    "content": "Agent: Hello, thank you for calling Acme Support. My name is Sarah. How can I help you today?\nCustomer: Hi Sarah, I have been having trouble logging into my account for the past two days.\nAgent: I am sorry to hear that. Let me look into your account right away. Can you please verify your email address?\nCustomer: Sure, it is john@example.com.\nAgent: Thank you John. I can see there was a security lock on your account. I have removed it now. Please try logging in again.\nCustomer: It works now, thank you!\nAgent: You are welcome! Is there anything else I can help with today?\nCustomer: No, that is all. Thanks!\nAgent: Thank you for calling Acme Support. Have a great day!",
    "subject": "Support call #1234"
  }'
```

**Expected**: 200 with scores for each criterion, weighted total, and overall feedback.

### Scenario 2: Upload Document to Knowledge Base

```bash
curl -X POST http://localhost:8000/api/v1/knowledge-bases/upload \
  -F "file=@support-policy.pdf" \
  -F "knowledge_base_id=kb-support"
```

**Expected**: 200 with `knowledge_base_id`, `document_id`, `chunk_count`.

### Scenario 3: Run Assessment with Knowledge Base

```bash
curl -X POST http://localhost:8000/api/v1/assessments \
  -H "Content-Type: application/json" \
  -d '{
    "scorecard": { ... },
    "content": "...",
    "subject": "Call #1235",
    "knowledge_base_id": "kb-support"
  }'
```

**Expected**: 200 with `knowledge_base_used: true`. AI evaluation references policy from uploaded documents.

### Scenario 4: Generate Insights

```bash
curl -X POST http://localhost:8000/api/v1/insights \
  -H "Content-Type: application/json" \
  -d '{
    "assessments": [
      { "scorecard_id": "sc-1", "scorecard_name": "Support QA", "subject": "Call #1", "scores": [...], "total_score": 75.0, "max_total_score": 100, "overall_feedback": "...", "knowledge_base_used": false },
      { "scorecard_id": "sc-1", "scorecard_name": "Support QA", "subject": "Call #2", "scores": [...], "total_score": 60.0, "max_total_score": 100, "overall_feedback": "...", "knowledge_base_used": false },
      { "scorecard_id": "sc-1", "scorecard_name": "Support QA", "subject": "Call #3", "scores": [...], "total_score": 85.0, "max_total_score": 100, "overall_feedback": "...", "knowledge_base_used": false }
    ]
  }'
```

**Expected**: 200 with top_issues, patterns, recommendations, strength_areas, weak_areas, summary.

### Scenario 5: Query Knowledge Base (debug/test)

```bash
curl -X POST http://localhost:8000/api/v1/knowledge-bases/kb-support/query \
  -H "Content-Type: application/json" \
  -d '{"query": "greeting protocol", "top_k": 3}'
```

**Expected**: 200 with ranked text chunks from uploaded documents.

## Running Tests

```bash
pytest                     # all tests
pytest tests/assessment/   # assessment module only
pytest tests/knowledge_base/
pytest tests/insights/
```
