from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.assignments import router as assignments_router
from app.api.routes.auth import router as auth_router
from app.api.routes.availability import router as availability_router
from app.api.routes.calendar import router as calendar_router
from app.api.routes.organization import router as organization_router
from app.api.routes.rosters import router as rosters_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(organization_router)
app.include_router(auth_router)
app.include_router(rosters_router)
app.include_router(assignments_router)
app.include_router(calendar_router)
app.include_router(availability_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
