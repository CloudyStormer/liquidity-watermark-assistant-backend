from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@router.get("/config")
def public_config() -> dict[str, str | int]:
    return {
        "appName": settings.app_name,
        "environment": settings.app_env,
        "maxUploadBytes": settings.max_upload_bytes,
    }
