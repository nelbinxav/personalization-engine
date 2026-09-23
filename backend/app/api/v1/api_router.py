from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    exports,
    jobs,
    preview,
    prompts,
    settings,
    templates,
    uploads,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(uploads.router)
api_router.include_router(jobs.router)
api_router.include_router(prompts.router)
api_router.include_router(templates.router)
api_router.include_router(preview.router)
api_router.include_router(settings.router)
api_router.include_router(exports.router)
