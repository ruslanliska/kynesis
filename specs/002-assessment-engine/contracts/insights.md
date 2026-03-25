# API Contract: Insights Endpoint

## POST /api/v1/insights

Generate cross-assessment insights from a set of assessment results.

### Request

**Content-Type**: `application/json`

```json
{
  "assessments": [
    {
      "scorecard_id": "sc-uuid-1",
      "scorecard_name": "Customer Support QA",
      "subject": "Call #1234",
      "scores": [
        {
          "criterion_id": "crit-1",
          "criterion_name": "Greeting",
          "score": 8,
          "max_score": 10,
          "feedback": "Good greeting..."
        },
        {
          "criterion_id": "crit-2",
          "criterion_name": "Resolution",
          "score": 4,
          "max_score": 10,
          "feedback": "Issue not fully resolved..."
        }
      ],
      "total_score": 55.0,
      "max_total_score": 100,
      "overall_feedback": "Mixed performance...",
      "knowledge_base_used": false,
      "knowledge_base_warning": null
    },
    {
      "scorecard_id": "sc-uuid-1",
      "scorecard_name": "Customer Support QA",
      "subject": "Call #1235",
      "scores": [
        {
          "criterion_id": "crit-1",
          "criterion_name": "Greeting",
          "score": 9,
          "max_score": 10,
          "feedback": "Excellent greeting..."
        },
        {
          "criterion_id": "crit-2",
          "criterion_name": "Resolution",
          "score": 3,
          "max_score": 10,
          "feedback": "Failed to resolve..."
        }
      ],
      "total_score": 50.0,
      "max_total_score": 100,
      "overall_feedback": "Needs improvement on resolution...",
      "knowledge_base_used": false,
      "knowledge_base_warning": null
    },
    {
      "scorecard_id": "sc-uuid-1",
      "scorecard_name": "Customer Support QA",
      "subject": "Call #1236",
      "scores": [
        {
          "criterion_id": "crit-1",
          "criterion_name": "Greeting",
          "score": 7,
          "max_score": 10,
          "feedback": "Adequate greeting..."
        },
        {
          "criterion_id": "crit-2",
          "criterion_name": "Resolution",
          "score": 9,
          "max_score": 10,
          "feedback": "Thorough resolution..."
        }
      ],
      "total_score": 82.5,
      "max_total_score": 100,
      "overall_feedback": "Strong performance...",
      "knowledge_base_used": false,
      "knowledge_base_warning": null
    }
  ]
}
```

**Validation rules**:
- `assessments`: min 3 items

### Response — 200 OK

```json
{
  "top_issues": [
    {
      "title": "Inconsistent Issue Resolution",
      "description": "2 out of 3 assessments show low resolution scores...",
      "frequency": 2,
      "severity": "high"
    }
  ],
  "patterns": [
    {
      "title": "Strong Opening Interactions",
      "description": "Greeting scores consistently high across all assessments...",
      "category": "Communication"
    }
  ],
  "recommendations": [
    {
      "title": "Implement Resolution Checklist",
      "description": "Create a step-by-step checklist for issue resolution...",
      "priority": "high",
      "impact": "Could improve resolution scores by 30-40%"
    }
  ],
  "summary": "Analysis of 3 assessments reveals strong customer greeting skills but significant gaps in issue resolution...",
  "strength_areas": [
    {
      "name": "Greeting",
      "score": 8.0
    }
  ],
  "weak_areas": [
    {
      "name": "Resolution",
      "score": 5.33,
      "suggestion": "Focus on thorough troubleshooting before closing tickets"
    }
  ]
}
```

### Response — 422 Validation Error

```json
{
  "detail": "Minimum 3 assessments required for insights analysis."
}
```

### Response — 502 AI Provider Error

```json
{
  "detail": "AI provider returned invalid output. Please retry."
}
```

### Test Scenarios

1. **Happy path**: 3+ assessments → 200 with complete insight report
2. **Multiple scorecards**: Assessments from different scorecards → 200, patterns differentiated per scorecard
3. **Too few assessments**: <3 → 422
4. **Large batch**: 20+ assessments → 200 within 30s
5. **AI provider down**: → 502
