# API Contract: Assessment Endpoint

## POST /api/v1/assessments

Run a scorecard assessment against content using AI evaluation.

### Request

**Content-Type**: `application/json`

```json
{
  "scorecard": {
    "id": "uuid-string",
    "name": "Customer Support QA",
    "description": "Evaluate customer support interactions",
    "criteria": [
      {
        "id": "crit-uuid-1",
        "name": "Greeting",
        "description": "Did the agent greet the customer properly?",
        "weight": 3,
        "max_score": 10
      },
      {
        "id": "crit-uuid-2",
        "name": "Resolution",
        "description": "Was the issue resolved?",
        "weight": 5,
        "max_score": 10
      }
    ]
  },
  "content": "Agent: Hello, thank you for calling...\nCustomer: Hi, I have an issue with...",
  "subject": "Support call #1234",
  "knowledge_base_id": "kb-uuid-optional"
}
```

**Validation rules**:
- `scorecard.criteria`: min 1 item
- `scorecard.criteria[].weight`: 1-10
- `scorecard.criteria[].max_score`: 1-100
- `content`: min 50 chars, max 100,000 chars
- `knowledge_base_id`: optional, if provided must be valid Pinecone namespace

### Response — 200 OK

```json
{
  "scorecard_id": "uuid-string",
  "scorecard_name": "Customer Support QA",
  "subject": "Support call #1234",
  "scores": [
    {
      "criterion_id": "crit-uuid-1",
      "criterion_name": "Greeting",
      "score": 8,
      "max_score": 10,
      "feedback": "Agent provided a warm and professional greeting..."
    },
    {
      "criterion_id": "crit-uuid-2",
      "criterion_name": "Resolution",
      "score": 7,
      "max_score": 10,
      "feedback": "The issue was addressed but follow-up steps were missing..."
    }
  ],
  "total_score": 78.13,
  "max_total_score": 100,
  "overall_feedback": "Overall, the agent demonstrated good customer service skills...",
  "knowledge_base_used": true,
  "knowledge_base_warning": null
}
```

**Score calculation**: `((8/10)*3 + (7/10)*5) / (3+5) * 100 = (2.4+3.5)/8*100 = 73.75`

### Response — 422 Validation Error

```json
{
  "detail": "Content too short. Minimum 50 characters required."
}
```

### Response — 502 AI Provider Error

```json
{
  "detail": "AI provider returned invalid output. Please retry."
}
```

### Test Scenarios

1. **Happy path**: Valid scorecard + content → 200 with structured scores
2. **With knowledge base**: Valid request + `knowledge_base_id` → 200, `knowledge_base_used: true`
3. **KB unavailable**: Valid request + invalid `knowledge_base_id` → 200, `knowledge_base_used: false`, `knowledge_base_warning` set
4. **Empty content**: content="" → 422
5. **Content too long**: >100k chars → 422
6. **No criteria**: empty criteria array → 422
7. **AI provider down**: → 502
