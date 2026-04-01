import json
import re

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.auth import verify_api_key
from app.scorecards.schemas import ScorecardDefinition

router = APIRouter(
    prefix="/api/v1/scorecards",
    tags=["scorecards"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/import", response_model=ScorecardDefinition, response_model_by_alias=True)
async def import_scorecard(scorecard: ScorecardDefinition) -> ScorecardDefinition:
    """Validate and normalize a scorecard JSON from the builder.

    Accepts a scorecard definition (with or without IDs). Missing IDs are
    auto-generated. Returns the fully-populated scorecard object.
    """
    return scorecard


@router.post("/export")
async def export_scorecard(scorecard: ScorecardDefinition) -> Response:
    """Return the scorecard as a downloadable JSON file."""
    payload = scorecard.model_dump(by_alias=True, mode="json")
    body = json.dumps(payload, indent=2, ensure_ascii=False)

    safe_name = re.sub(r"[^\w\-]", "_", scorecard.name)
    filename = f"scorecard_{safe_name}.json"

    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
