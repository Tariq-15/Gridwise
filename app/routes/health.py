from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    # Zero I/O, no LLM call — readiness must not depend on any external provider.
    return {"status": "ok"}
