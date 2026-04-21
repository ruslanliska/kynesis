# Quickstart: Image Assessment Endpoint (feature 004)

**Feature**: 004-image-assessment
**Date**: 2026-04-20

This is a developer-facing smoke-test guide. It assumes you have a working local checkout of kynesis with the text, document, and audio assessment endpoints already running.

---

## 1. Prerequisites

Required env vars (already present for earlier features):

```bash
API_KEY=<any non-empty value for local>
OPENAI__API_KEY=<an OpenAI key with GPT-4o access>
DEEPSEEK__API_KEY=<optional; unchanged from features 002/003>
PINECONE__API_KEY=<optional; only needed if you want to smoke-test use_knowledge_base=true>
LANGSMITH__TRACING=true      # optional, for trace visibility
LANGSMITH__API_KEY=<optional>
```

New (this feature) — all optional, defaults shown:

```bash
# In AssessmentConfig (nested via the ASSESSMENT__ prefix):
ASSESSMENT__VISION_REASONING_MODEL=gpt-4o
ASSESSMENT__IMAGE_KB_DESCRIBE_MODEL=gpt-4o-mini
```

Dependencies: no new packages. The feature uses `langchain-openai` (already installed) and `python-multipart` (already installed).

## 2. Run the server

From repo root:

```bash
uvicorn app.main:app --reload --port 8000
```

Expected: server starts, existing routes resolve, and the new route shows up in `GET /docs` as `POST /api/v1/assessments/image`.

## 3. Smoke test — happy path (no KB)

Save a tiny scorecard JSON locally:

```bash
cat > /tmp/sc.json <<'JSON'
{
  "id": "sc-smoke",
  "name": "Screenshot QA",
  "description": "Smoke test",
  "status": "active",
  "scoringMode": "add",
  "maxScore": 10,
  "passingThreshold": 5,
  "allowQuestionComments": true,
  "allowOverallComment": true,
  "showPointsToEvaluator": true,
  "version": 1,
  "sections": [
    {
      "id": "sec-1",
      "name": "Clarity",
      "description": "Is the screenshot legible?",
      "orderIndex": 0,
      "weight": 100,
      "questions": [
        {
          "id": "q1",
          "text": "Is the image clear and readable?",
          "description": "",
          "scoringType": "binary",
          "maxPoints": 10,
          "required": true,
          "critical": "none",
          "orderIndex": 0,
          "options": [
            {"id": "opt-yes", "label": "Yes", "value": 1, "pointsChange": 10, "orderIndex": 0},
            {"id": "opt-no",  "label": "No",  "value": 0, "pointsChange": 0,  "orderIndex": 1}
          ]
        }
      ]
    }
  ]
}
JSON
```

Pick any PNG/JPEG on disk under 20 MB:

```bash
curl -sS -X POST http://localhost:8000/api/v1/assessments/image \
  -H "X-API-Key: $API_KEY" \
  -F "file=@/path/to/screenshot.png" \
  -F "scorecard=$(cat /tmp/sc.json)" \
  -F "use_knowledge_base=false" | jq .
```

Expected response:
- `200 OK`
- `contentType: "image"`
- `questions[0].rationale` non-empty
- `overall.score` between 0 and 100

## 4. Smoke test — validation errors

Empty file:

```bash
: > /tmp/empty.png
curl -i -X POST http://localhost:8000/api/v1/assessments/image \
  -H "X-API-Key: $API_KEY" \
  -F "file=@/tmp/empty.png" \
  -F "scorecard=$(cat /tmp/sc.json)"
# → 422 { "detail": "File is empty." }
```

Unsupported format:

```bash
echo "hi" > /tmp/x.bmp
curl -i -X POST http://localhost:8000/api/v1/assessments/image \
  -H "X-API-Key: $API_KEY" \
  -F "file=@/tmp/x.bmp" \
  -F "scorecard=$(cat /tmp/sc.json)"
# → 422 { "detail": "Unsupported file format '.bmp'. Supported: .gif, .jpeg, .jpg, .png, .webp." }
```

Invalid scorecard JSON:

```bash
curl -i -X POST http://localhost:8000/api/v1/assessments/image \
  -H "X-API-Key: $API_KEY" \
  -F "file=@/path/to/screenshot.png" \
  -F "scorecard={not json"
# → 422 { "detail": "Invalid scorecard JSON: ..." }
```

## 5. Smoke test — knowledge base enabled

Requires Pinecone set up with the scorecard's knowledge base (see feature 002 quickstart).

```bash
curl -sS -X POST http://localhost:8000/api/v1/assessments/image \
  -H "X-API-Key: $API_KEY" \
  -F "file=@/path/to/screenshot.png" \
  -F "scorecard=$(cat /tmp/sc.json)" \
  -F "use_knowledge_base=true" | jq .
```

Expected:
- Logfire span `image_assessment` with `knowledge_base_used=true` and `knowledge_base_hit=true|false`.
- Response body shape identical to §3.
- If Pinecone is unreachable, the response still succeeds (same graceful-degradation semantics as the other endpoints) and includes a warning indicating KB was unavailable.

## 6. Verify tracing discipline

With Logfire enabled locally, confirm:

- Span `image_assessment` records `filename`, `mime`, `size_bytes`, `outcome`, `latency_ms`.
- Span `image_assessment` does **not** record the image bytes or any base64 content — grep the span attributes; no long base64 strings should appear.
- The actual LLM call shows up in LangSmith (if `LANGSMITH__TRACING=true`) with the image URL/base64 — this is expected and acceptable.

## 7. Run the test suite

```bash
pytest tests/assessment -q
```

The feature adds tests under `tests/assessment/test_services.py` and `tests/assessment/test_router.py`. Expected: all pass, including the new image-specific ones.

---

## 8. Known sharp edges

- **Safety rejections**: Certain images trigger OpenAI content policy rejections. These surface as 422 with a user-facing message, not 502.
- **Cold GPT-4o latency**: First request may take ~8–15s if the provider cold-starts a session. Subsequent requests are much faster.
- **20 MB ceiling**: Phone-camera shots occasionally exceed this; compress client-side if needed.
- **`rationale` vs `thinking_trace`**: GPT-4o does not expose a thinking trace; `ReasoningQuestionRecord.thinking_trace` is always `None` on this path, while `rationale` is always populated.
