# Data Model: Assessment Processing Engine

**Date**: 2026-03-25
**Branch**: `002-assessment-engine`

## Overview

All entities in this feature are **transient** — they exist as Pydantic schemas for request/response validation, not as database models. The only persistent storage is Pinecone (vector DB) for knowledge base embeddings. No SQLAlchemy models are created for this feature.

## Entities

### 1. ScorecardCriterion (request input)

Received as part of the assessment request. Matches frontend `ScorecardCriterion` type.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | str | required | Criterion identifier (UUID from frontend) |
| name | str | required, min_length=1 | Criterion name |
| description | str | required | What this criterion evaluates |
| weight | int | required, ge=1, le=10 | Relative importance weight |
| max_score | int | required, ge=1, le=100 | Maximum possible score for this criterion |

### 2. Scorecard (request input)

Received in assessment request. Not persisted by backend.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | str | required | Scorecard ID (UUID from frontend) |
| name | str | required, min_length=1 | Scorecard name |
| description | str | optional, default="" | Scorecard description |
| criteria | list[ScorecardCriterion] | required, min_length=1 | Evaluation criteria |

### 3. AssessmentRequest (request input)

The full request body for running an assessment.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| scorecard | Scorecard | required | Scorecard definition with criteria |
| content | str | required, min_length=50, max_length=100000 | Content to evaluate (transcript, chat log, etc.) |
| subject | str | optional, default="" | Subject/title for the assessment |
| knowledge_base_id | str | optional | Pinecone namespace for RAG context |

### 4. CriterionScore (response output)

Per-criterion evaluation result. Matches frontend `AssessmentScore` type.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| criterion_id | str | required | Maps to ScorecardCriterion.id |
| criterion_name | str | required | Criterion name (echoed back) |
| score | int | required, ge=0 | Score awarded (0 to max_score) |
| max_score | int | required, ge=1 | Maximum possible score |
| feedback | str | required | Detailed feedback for this criterion |

**Validation**: `score <= max_score` (enforced by result validator)

### 5. AssessmentResult (response output)

Complete assessment response. Matches frontend `Assessment` type (minus frontend-only fields like `id`, `createdAt`).

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| scorecard_id | str | required | ID of the scorecard used |
| scorecard_name | str | required | Name of the scorecard used |
| subject | str | required | Subject echoed from request |
| scores | list[CriterionScore] | required | Per-criterion scores |
| total_score | float | required, ge=0, le=100 | Weighted overall score (0-100) |
| max_total_score | float | required | Maximum possible weighted score (always 100) |
| overall_feedback | str | required | Summary feedback across all criteria |
| knowledge_base_used | bool | required, default=False | Whether RAG context was included |
| knowledge_base_warning | str | optional | Warning if KB was unavailable |

**Score formula**: `sum((score/max_score) * weight) / total_weight * 100`

### 6. KnowledgeBaseUploadRequest (request input — multipart form)

Document upload for knowledge base processing.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| file | UploadFile | required, max 10MB | Document file (PDF, TXT, DOCX, MD) |
| knowledge_base_id | str | optional | Existing KB ID to add to; if absent, creates new |
| document_id | str | optional | Document ID for replacement; if absent, generates new |

**Supported formats**: `.pdf`, `.txt`, `.docx`, `.md`

### 7. KnowledgeBaseUploadResponse (response output)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| knowledge_base_id | str | required | KB namespace in Pinecone |
| document_id | str | required | Document identifier |
| chunk_count | int | required, ge=0 | Number of chunks created |
| status | str | required | "processed" or "replaced" |

### 8. InsightIssue (response nested)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| title | str | required | Issue title |
| description | str | required | Issue description |
| frequency | int | required, ge=1 | How many assessments show this issue |
| severity | str | required, enum: high/medium/low | Issue severity |

### 9. InsightPattern (response nested)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| title | str | required | Pattern title |
| description | str | required | Pattern description |
| category | str | required | Pattern category |

### 10. InsightRecommendation (response nested)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| title | str | required | Recommendation title |
| description | str | required | Recommendation description |
| priority | str | required, enum: high/medium/low | Priority level |
| impact | str | required | Expected impact |

### 11. InsightArea (response nested)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| name | str | required | Area name |
| score | float | required, ge=0 | Average score in this area |
| suggestion | str | optional | Improvement suggestion (for weak areas only) |

### 12. InsightRequest (request input)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| assessments | list[AssessmentResult] | required, min_length=3 | Assessment results to analyze |

### 13. InsightReport (response output)

Matches frontend `InsightsData` type.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| top_issues | list[InsightIssue] | required | Top issues with frequency/severity |
| patterns | list[InsightPattern] | required | Detected patterns |
| recommendations | list[InsightRecommendation] | required | Prioritized recommendations |
| summary | str | required | Executive summary |
| strength_areas | list[InsightArea] | required | Strong performance areas |
| weak_areas | list[InsightArea] | required | Areas needing improvement |

## Relationships

```text
AssessmentRequest
├── Scorecard
│   └── ScorecardCriterion (1:N)
└── knowledge_base_id → Pinecone namespace

AssessmentResult
├── CriterionScore (1:N, one per ScorecardCriterion)
└── scorecard_id (echoed from request)

InsightRequest
└── AssessmentResult (N, min 3)

InsightReport
├── InsightIssue (1:N)
├── InsightPattern (1:N)
├── InsightRecommendation (1:N)
├── InsightArea (strength, 1:N)
└── InsightArea (weak, 1:N)

KnowledgeBaseUploadRequest → Pinecone (namespace = knowledge_base_id)
```

## Pinecone Vector Schema

Stored in Pinecone serverless index, one namespace per knowledge base.

| Field | Location | Type | Description |
|-------|----------|------|-------------|
| id | vector ID | str | `{document_id}-{chunk_index}` |
| values | vector | list[float] | 1536-dim embedding (text-embedding-3-small) |
| knowledge_base_id | metadata | str | KB identifier (also used as namespace) |
| document_id | metadata | str | Source document identifier |
| chunk_index | metadata | int | Position of chunk in document |
| text | metadata | str | Original chunk text |
| source_filename | metadata | str | Original file name |
