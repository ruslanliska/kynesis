# Feature Specification: Assessment Processing Engine

**Feature Branch**: `002-assessment-engine`
**Created**: 2026-03-25
**Status**: Draft
**Input**: Stateless FastAPI processing engine for AI-powered scorecard assessments, knowledge base RAG with Pinecone, configurable AI providers via Pydantic AI. Database settings retained for future use. Frontend (Lovable/Supabase) handles all CRUD and storage.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run Scorecard Assessment (Priority: P1)

A QA manager has created a scorecard (criteria with weights) in the frontend and wants to evaluate a piece of content (e.g., a call transcript, chat log, or code review) against it. They submit the scorecard definition and content to the backend. The system uses a configured AI provider to evaluate the content against each criterion, producing a structured score, feedback per criterion, and an overall weighted score. The frontend receives the results and stores them in Supabase.

**Why this priority**: This is the core value proposition — automated quality evaluation. Without this, the product has no processing capability. The frontend buttons for "Run Assessment" are currently disabled waiting for this endpoint.

**Independent Test**: Can be tested by sending a scorecard with 3+ criteria and a sample transcript, verifying the response contains scores for each criterion within valid ranges, per-criterion feedback, and a correctly calculated weighted total score.

**Acceptance Scenarios**:

1. **Given** a valid scorecard with criteria and content to evaluate, **When** submitted to the assessment endpoint, **Then** the system returns structured scores for each criterion, per-criterion feedback, and a weighted overall score.
2. **Given** a scorecard with a knowledge base ID, **When** submitted for assessment, **Then** the system retrieves relevant context from the knowledge base and includes it in the AI evaluation prompt.
3. **Given** content that is empty or too short to evaluate meaningfully, **When** submitted, **Then** the system returns an error indicating insufficient content.
4. **Given** the AI provider is unavailable or returns an error, **When** an assessment is submitted, **Then** the system returns a clear error with the failure reason without exposing internal details.
5. **Given** a scorecard with criteria weights, **When** scores are returned, **Then** the overall score is calculated as: `sum((score/maxScore) * weight) / totalWeight * 100`, producing a 0-100 normalized value.

---

### User Story 2 - Upload and Process Knowledge Base (Priority: P1)

A QA manager uploads documents (company policies, scripts, guidelines) that should be used as reference context when evaluating assessments. The system processes the documents — splitting them into chunks, generating embeddings, and storing them in a vector database. When an assessment is run with a knowledge base, the system retrieves relevant chunks to provide context to the AI agent.

**Why this priority**: Co-priority with assessments — knowledge-base-aware evaluation is a key differentiator. Without this, the AI evaluates without domain context, producing generic results.

**Independent Test**: Can be tested by uploading a document, then running an assessment with the knowledge base ID, verifying the AI response references concepts from the uploaded document.

**Acceptance Scenarios**:

1. **Given** a document file (PDF, TXT, DOCX, or Markdown), **When** uploaded to the knowledge base endpoint, **Then** the system chunks the document, generates embeddings, stores them in the vector database, and returns a knowledge base ID.
2. **Given** a knowledge base ID and a query, **When** the system performs retrieval, **Then** it returns the most relevant chunks ranked by similarity.
3. **Given** a document that exceeds the maximum size limit, **When** uploaded, **Then** the system returns a validation error with the size limit.
4. **Given** an unsupported file format, **When** uploaded, **Then** the system returns a clear error listing supported formats.
5. **Given** multiple documents uploaded to the same knowledge base, **When** an assessment runs, **Then** the system retrieves relevant chunks from across all documents.

---

### User Story 3 - Generate Cross-Assessment Insights (Priority: P2)

A QA manager wants to see patterns across multiple assessments — common issues, strengths, trends, and actionable recommendations. They submit a set of assessment results to the insights endpoint. The system analyzes them using AI and returns structured insights. This replaces the existing Supabase Edge Function.

**Why this priority**: Insights provide strategic value on top of individual assessments. Lower priority because users need assessments first before insights are useful.

**Independent Test**: Can be tested by submitting 5+ assessment results with varied scores, verifying the response contains identified patterns, top issues with frequency, strengths, weaknesses, and prioritized recommendations.

**Acceptance Scenarios**:

1. **Given** a set of 3 or more assessment results, **When** submitted to the insights endpoint, **Then** the system returns top issues, patterns, recommendations, strength areas, weak areas, and a summary.
2. **Given** fewer than 3 assessment results, **When** submitted, **Then** the system returns an error indicating insufficient data for meaningful analysis.
3. **Given** assessment results spanning multiple scorecards, **When** analyzed, **Then** the insights differentiate patterns per scorecard while also identifying cross-scorecard trends.

---

### Edge Cases

- What happens when the AI provider returns malformed or incomplete output? The system MUST validate the response against the expected scorecard schema and return an error if the output cannot be parsed into valid scores.
- What happens if Pinecone is unavailable during an assessment with a knowledge base? The system MUST proceed with the assessment without RAG context and include a warning in the response that knowledge base context was unavailable.
- What happens with extremely long content (e.g., a 2-hour transcript)? The system MUST handle content up to 100,000 characters. Content exceeding this limit MUST return a validation error.
- What happens if the user submits the same document to a knowledge base twice? The system MUST replace the previous version — delete old chunks from Pinecone and re-index the new document.
- How does the system handle concurrent assessment requests? The system MUST process requests independently with no shared state between requests.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a scorecard definition (criteria with names, descriptions, weights, and max scores) and content to evaluate, and return structured assessment results.
- **FR-002**: System MUST return per-criterion scores (0 to maxScore), per-criterion feedback text, and a weighted overall score (0-100).
- **FR-003**: System MUST support configurable AI providers — the provider and model are configured server-side, not sent per request.
- **FR-004**: System MUST accept document uploads, chunk them, generate embeddings, and store them in a vector database for retrieval.
- **FR-005**: System MUST retrieve relevant knowledge base chunks during assessment when a knowledge base ID is provided.
- **FR-006**: System MUST accept a set of assessment results and return structured insights (top issues, patterns, recommendations, strengths, weaknesses, summary).
- **FR-007**: System MUST validate all inputs — scorecard structure, content length, file formats, minimum assessment count for insights.
- **FR-008**: System MUST return consistent error responses with clear messages for all failure modes.
- **FR-009**: System MUST be stateless — no user sessions, no database for request state. All data needed for processing is sent in the request.
- **FR-010**: System MUST retain database configuration infrastructure for future use, even though current endpoints do not require database access.

### Key Entities

- **Scorecard** (received in request, not persisted by backend): A set of evaluation criteria. Key attributes: name, description, criteria array. Each criterion has: id, name, description, weight (1-10), maxScore (1-100).
- **Assessment Result** (returned in response, stored by frontend): Scores per criterion with feedback, overall weighted score, overall feedback. Each score has: criterionId, criterionName, score, maxScore, feedback.
- **Knowledge Base** (managed by backend): A collection of document chunks with embeddings stored in a vector database. Key attributes: knowledge base ID, document metadata, chunk count.
- **Insight Report** (returned in response, stored by frontend): Cross-assessment analysis. Key attributes: topIssues (with frequency/severity), patterns, recommendations (with priority), strengthAreas, weakAreas, summary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Assessment results are returned within 30 seconds for content up to 10,000 characters with a 5-criteria scorecard.
- **SC-002**: 100% of assessment responses conform to the expected structured output schema — no malformed or missing fields.
- **SC-003**: Knowledge base retrieval adds relevant context that measurably improves assessment quality compared to assessments without knowledge base.
- **SC-004**: Insights analysis returns actionable results for any set of 3+ assessments within 30 seconds.
- **SC-005**: Document upload and processing completes within 60 seconds for files up to 10MB.
- **SC-006**: The system handles 10 concurrent assessment requests without degradation.

## Clarifications

### Session 2026-03-25

- Q: Observability approach? → A: Full observability using Pydantic Logfire — structured logging, tracing, and metrics via Logfire integration.
- Q: Duplicate document upload strategy? → A: Replace — delete old chunks and re-index the new version of the same document.

## Assumptions

- The frontend (Lovable Cloud / Supabase) handles all data storage — scorecards, assessments, insights are stored in Supabase by the frontend after receiving processing results from FastAPI.
- AI provider configuration (API keys, model selection) is managed server-side via environment variables or config files — users do not choose providers per request.
- Pydantic AI will be used as the AI agent framework, providing structured output validation and multi-provider support.
- Pinecone will be used as the vector database for knowledge base storage and retrieval.
- Supported document formats for knowledge base: PDF, TXT, DOCX, Markdown (.md).
- Maximum document size: 10MB per file.
- Maximum content length for assessment: 100,000 characters.
- Authentication for the API is handled separately (API key or token forwarding) — not part of this spec's scope.
- The existing database infrastructure (SQLAlchemy async, connection config) is retained for future features but not used by current endpoints.
- The weighted score formula matches the frontend implementation: `sum((score/maxScore) * weight) / totalWeight * 100`.
- Pydantic Logfire will be used for observability — structured logging, tracing (OpenTelemetry-based), and metrics. Integrates natively with Pydantic AI and FastAPI.
