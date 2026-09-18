from fastapi import APIRouter

from app.schemas.request import ScenarioRequest
from app.schemas.response import OptimizeResponse
from app.services.orchestrator import handle_request
from app.services.semantic_validation import SemanticValidationError, check_semantic_validity

router = APIRouter()


@router.post("/optimize-energy", response_model=OptimizeResponse)
async def optimize_energy(scenario: ScenarioRequest):
    check_semantic_validity(scenario)  # raises SemanticValidationError -> 422, handled in main.py
    result = await handle_request(scenario)
    return result
