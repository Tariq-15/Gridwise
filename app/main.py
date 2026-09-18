import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.logging_utils import get_logger
from app.routes.health import router as health_router
from app.routes.optimize import router as optimize_router
from app.services.semantic_validation import SemanticValidationError

logger = get_logger(__name__)

app = FastAPI(title="GridWise LLM-Assisted Energy Optimizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(optimize_router)


@app.exception_handler(RequestValidationError)
async def malformed_request_handler(request: Request, exc: RequestValidationError):
    # The Problem Statement wants malformed/structurally invalid requests to be
    # 400, not FastAPI's default 422.
    return JSONResponse(status_code=400, content={"error": "invalid_request", "message": "Malformed or structurally invalid request."})


@app.exception_handler(SemanticValidationError)
async def semantic_validation_handler(request: Request, exc: SemanticValidationError):
    return JSONResponse(status_code=422, content={"error": "semantically_invalid", "message": exc.message})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled exception on %s: %s", request.url.path, type(exc).__name__, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "internal_error", "message": "An internal error occurred."})


@app.middleware("http")
async def log_timing(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info("%s %s -> %s in %sms", request.method, request.url.path, response.status_code, elapsed_ms)
    return response
