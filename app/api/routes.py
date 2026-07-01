from fastapi import APIRouter

from app.api.v1.feedback import router as feedback_router
from app.api.v1.health import router as health_router
from app.api.v1.media import router as media_router
from app.api.v1.ratings import router as ratings_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(media_router, prefix="/media", tags=["media"])
api_router.include_router(ratings_router, prefix="/ratings", tags=["ratings"])
api_router.include_router(feedback_router, prefix="/feedback", tags=["feedback"])
