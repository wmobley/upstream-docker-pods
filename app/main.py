from collections.abc import Awaitable, Callable
import os

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.main import api_router


app = FastAPI(
    title="Upstream Sensor Storage",
    description="Sensor Storage for Upstream data",
    version="0.0.1",
    contact={
        "name": "Will Mobley",
        "email": "wmobley@tacc.utexas.edu",
    },

)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

UPSTREAM_RELEASE = (
    os.environ.get("UPSTREAM_RELEASE")
    or os.environ.get("IMAGE_TAG")
    or os.environ.get("HOSTNAME")
    or "unknown"
)


@app.middleware("http")
async def add_cache_control_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)

    if request.url.path.startswith("/api/") or request.url.path in {"/docs", "/openapi.json", "/redoc"}:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

    response.headers["X-Upstream-Release"] = UPSTREAM_RELEASE

    return response

app.include_router(api_router, prefix="/api/v1")
