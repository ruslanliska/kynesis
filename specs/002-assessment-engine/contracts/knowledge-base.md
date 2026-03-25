# API Contract: Knowledge Base Endpoints

## POST /api/v1/knowledge-bases/upload

Upload a document to a knowledge base. Creates a new KB or adds to existing.

### Request

**Content-Type**: `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| file | file | yes | Document file (PDF, TXT, DOCX, MD). Max 10MB. |
| knowledge_base_id | string | no | Existing KB ID. If absent, creates new KB. |
| document_id | string | no | Document ID for replacement. If absent, generates new. |

### Response — 200 OK

```json
{
  "knowledge_base_id": "kb-uuid-123",
  "document_id": "doc-uuid-456",
  "chunk_count": 24,
  "status": "processed"
}
```

When replacing an existing document:
```json
{
  "knowledge_base_id": "kb-uuid-123",
  "document_id": "doc-uuid-456",
  "chunk_count": 28,
  "status": "replaced"
}
```

### Response — 422 Validation Error

```json
{
  "detail": "Unsupported file format '.xlsx'. Supported: PDF, TXT, DOCX, MD."
}
```

```json
{
  "detail": "File exceeds maximum size of 10MB."
}
```

### Test Scenarios

1. **Upload PDF**: Valid PDF → 200, status "processed", chunk_count > 0
2. **Upload TXT**: Valid TXT → 200
3. **Upload DOCX**: Valid DOCX → 200
4. **Upload MD**: Valid Markdown → 200
5. **Add to existing KB**: Provide `knowledge_base_id` → 200, same KB ID returned
6. **Replace document**: Provide `knowledge_base_id` + `document_id` → 200, status "replaced"
7. **Unsupported format**: .xlsx → 422
8. **File too large**: >10MB → 422
9. **Empty file**: 0 bytes → 422

---

## POST /api/v1/knowledge-bases/{knowledge_base_id}/query

Query a knowledge base for relevant chunks. (Internal/testing endpoint.)

### Request

**Content-Type**: `application/json`

```json
{
  "query": "What is the greeting protocol for support calls?",
  "top_k": 5
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| query | string | yes | — | Search query text |
| top_k | int | no | 5 | Number of results to return (1-20) |

### Response — 200 OK

```json
{
  "knowledge_base_id": "kb-uuid-123",
  "results": [
    {
      "text": "All support agents must greet customers within the first 5 seconds...",
      "score": 0.92,
      "document_id": "doc-uuid-456",
      "source_filename": "support-policy.pdf",
      "chunk_index": 3
    }
  ]
}
```

### Response — 404 Not Found

```json
{
  "detail": "Knowledge base 'kb-uuid-123' not found."
}
```

### Test Scenarios

1. **Valid query**: Existing KB + query → 200 with ranked results
2. **Non-existent KB**: Invalid KB ID → 404
3. **Custom top_k**: top_k=3 → exactly 3 results (if available)

---

## DELETE /api/v1/knowledge-bases/{knowledge_base_id}

Delete an entire knowledge base (all documents and chunks).

### Response — 200 OK

```json
{
  "knowledge_base_id": "kb-uuid-123",
  "status": "deleted"
}
```

### Response — 404 Not Found

```json
{
  "detail": "Knowledge base 'kb-uuid-123' not found."
}
```

### Test Scenarios

1. **Delete existing KB**: → 200, namespace removed from Pinecone
2. **Delete non-existent KB**: → 404
