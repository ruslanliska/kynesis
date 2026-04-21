"""Feature 004 — image assessment pipeline.

Holds:

- Shared constants for image handling (``SUPPORTED_IMAGE_EXTENSIONS``,
  ``MAX_IMAGE_SIZE``, ``MIME_TYPES``) used by both the OCR path
  (``app/assessment/ocr.py``) and the vision-assessment path.
- ``vision_reasoning_stage`` — image-bearing stage-1 call that produces
  per-question rationale. Decorated with ``@traceable`` so the run appears
  in LangSmith alongside the rest of the image pipeline.
- ``image_describe_for_kb`` — small vision call used to build a text query
  for Pinecone retrieval when ``use_knowledge_base=true``. Also
  ``@traceable``.
"""

from __future__ import annotations

import base64
from pathlib import Path

import logfire
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

from app.assessment.schemas import (
    AggregatedReasoning,
    ContentType,
    ReasoningQuestionRecord,
)
from app.core.ai_provider import (
    get_image_kb_describe_llm,
    get_vision_reasoning_llm,
)
from app.scorecards.schemas import ScorecardDefinition


SUPPORTED_IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMAGE_SIZE: int = 20 * 1024 * 1024  # 20 MB (GPT-4o Vision limit)

MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def resolve_mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    mime = MIME_TYPES.get(ext, "image/jpeg")
    # GPT-4o vision does not accept image/gif; re-encode hint uses PNG mime.
    return "image/png" if mime == "image/gif" else mime


_VISION_REASONING_PROMPT = """\
You are a rigorous QA auditor producing a deep, evidence-grounded reasoning pass over a VISUAL artifact.

## YOUR TASK
Analyse the IMAGE below against EVERY question on the scorecard. Consider BOTH
the text visible in the image AND its visual aspects (layout, tone cues,
branding, completeness, legibility). Produce a thorough rationale for each
question BEFORE any score is computed by the downstream formatter.

## OUTPUT FORMAT — STRICT
For every question in the scorecard, emit a block of the form:

### Q: <question_id>
<Your analysis: what the image shows, which visible evidence is relevant
(verbatim quotes when text is visible; described visual evidence otherwise),
what is missing, and the answer the evidence best supports — naming the exact
option_id or numeric value. At least 50 characters, ideally 2–6 sentences.>

Use the EXACT question id from the scorecard as `<question_id>` (do not paraphrase).
Do not merge questions. Do not add commentary outside the `### Q:` blocks.

## RULES
- Never claim something appears in the image without concrete visual evidence.
- Quote text verbatim when text is visible; describe visual elements precisely otherwise.
- For HARD CRITICAL questions, explicitly state whether the evidence supports awarding points.
- Score conservatively when evidence is absent, ambiguous, or illegible.
"""


_KB_DESCRIBE_PROMPT = """\
Describe this image in one concise paragraph (3–5 sentences) capturing the
type of content, visible participants/entities, any visible text (quoted
briefly), and the apparent context. Do not score, evaluate, or speculate
beyond what is visible. This description is used as a search query against a
knowledge base.
"""


@traceable(name="vision_reasoning_stage", run_type="chain")
async def vision_reasoning_stage(
    scorecard: ScorecardDefinition,
    image_bytes: bytes,
    filename: str,
    mime: str,
    knowledge_base_context: str | None = None,
) -> AggregatedReasoning:
    """Stage-1 image reasoning. Returns per-question rationale records.

    Decorated with ``@traceable`` so the run (including its message payload
    containing the image) appears in LangSmith alongside the rest of the
    image pipeline. LangSmith is an access-controlled analytics backend.
    """
    from app.assessment.services import (  # local import to avoid cycle
        _build_scorecard_context,
        parse_reasoning_response,
    )

    b64 = base64.b64encode(image_bytes).decode()
    scorecard_context = _build_scorecard_context(scorecard, knowledge_base_context)
    system_prompt = _VISION_REASONING_PROMPT + "\n\n" + scorecard_context

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Evaluate the following IMAGE against every scorecard question. "
                        "Emit one `### Q: <id>` block per question."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
            ]
        ),
    ]

    llm = get_vision_reasoning_llm()
    with logfire.span(
        "vision_reasoning_stage",
        scorecard_id=scorecard.id,
        filename=filename,
        size_bytes=len(image_bytes),
        mime=mime,
    ):
        response = await llm.ainvoke(messages)

    text = response.content if isinstance(response.content, str) else str(response.content)
    records = parse_reasoning_response(text, scorecard)

    expected_ids = {q.id for s in scorecard.sections for q in s.questions}
    produced_ids = {r.question_id for r in records}
    missing = expected_ids - produced_ids
    if missing:
        from app.core.errors import ReasoningCoverageError

        raise ReasoningCoverageError(missing)

    return AggregatedReasoning(
        scorecard_id=scorecard.id,
        content_type=ContentType.image,
        content_preview=f"[image: {filename}, {mime}, {len(image_bytes)}B]",
        records=records,
        full_trace_available=False,
    )


@traceable(name="image_describe_for_kb", run_type="chain")
async def image_describe_for_kb(
    image_bytes: bytes,
    filename: str,
    mime: str,
) -> str:
    """Produce a short textual description of an image for KB retrieval.

    Used only when the caller opted into ``use_knowledge_base=true``.
    Decorated with ``@traceable`` so the describe call shows up in LangSmith.
    """
    b64 = base64.b64encode(image_bytes).decode()
    messages = [
        HumanMessage(
            content=[
                {"type": "text", "text": _KB_DESCRIBE_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
            ]
        ),
    ]

    llm = get_image_kb_describe_llm()
    with logfire.span(
        "image_describe_for_kb",
        filename=filename,
        size_bytes=len(image_bytes),
        mime=mime,
    ):
        response = await llm.ainvoke(messages, config={"callbacks": []})

    return (response.content if isinstance(response.content, str) else str(response.content)).strip()
