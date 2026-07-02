from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.config import settings
from app.repositories import (
    get_daily_quota,
    get_user_profile,
    grant_daily_quota,
    list_operation_logs,
    upsert_user,
)
from app.schemas.common import UserProfileResponse, UserResponse
from app.schemas.requests import LoginRequest, QuotaGrantRequest, WeappLoginRequest
from app.schemas.responses import DailyQuotaResponse, OperationLogResponse
from app.services.logging import log_operation
from app.services.weapp_auth import WeappLoginConfigError, exchange_code_for_session

router = APIRouter()

AVATAR_MAX_BYTES = 5 * 1024 * 1024


@router.post("/login", response_model=UserResponse)
def login_user(payload: LoginRequest, request: Request) -> UserResponse:
    user = upsert_user(
        openid=payload.openid,
        nickname=payload.nickname,
        avatar_url=payload.avatar_url,
    )
    log_operation(
        request,
        openid=payload.openid,
        action="user_login",
        target_type="user",
        target_id=payload.openid,
        detail={"has_nickname": payload.nickname is not None},
    )
    return user


@router.post("/weapp-login", response_model=UserResponse)
def login_weapp_user(payload: WeappLoginRequest, request: Request) -> UserResponse:
    try:
        session = exchange_code_for_session(payload.code)
    except WeappLoginConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    user = upsert_user(
        openid=session.openid,
        nickname=payload.nickname,
        avatar_url=payload.avatar_url,
    )
    log_operation(
        request,
        openid=session.openid,
        action="weapp_user_login",
        target_type="user",
        target_id=session.openid,
        detail={
            "has_unionid": session.unionid is not None,
            "has_session_key": session.session_key is not None,
            "has_nickname": payload.nickname is not None,
        },
    )
    return user


@router.post("/{openid}/avatar", response_model=UserResponse)
async def upload_avatar(
    openid: str,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> UserResponse:
    profile = get_user_profile(openid)
    if profile is None:
        raise HTTPException(status_code=401, detail="User must login first")

    suffix = _avatar_suffix(file.filename, file.content_type)
    avatar_path = _avatar_path(openid, suffix)
    avatar_path.parent.mkdir(parents=True, exist_ok=True)
    for old_avatar in avatar_path.parent.glob(f"{_safe_openid(openid)}.*"):
        if old_avatar != avatar_path:
            old_avatar.unlink(missing_ok=True)

    total = 0
    with avatar_path.open("wb") as output_file:
        while chunk := await file.read(256 * 1024):
            total += len(chunk)
            if total > AVATAR_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Avatar file is too large")
            output_file.write(chunk)

    user = upsert_user(openid=openid, avatar_url=f"/api/users/{openid}/avatar")
    log_operation(
        request,
        openid=openid,
        action="user_avatar_updated",
        target_type="user",
        target_id=openid,
        detail={"bytes": total, "content_type": file.content_type},
    )
    return user


@router.get("/{openid}/avatar")
def get_avatar(openid: str) -> FileResponse:
    avatar_path = _find_avatar_path(openid)
    if avatar_path is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(avatar_path, media_type=_avatar_media_type(avatar_path.suffix))


@router.get("/{openid}/profile", response_model=UserProfileResponse)
def get_profile(openid: str, request: Request) -> UserProfileResponse:
    profile = get_user_profile(openid)
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found")
    log_operation(
        request,
        openid=openid,
        action="user_profile_viewed",
        target_type="user",
        target_id=openid,
    )
    return profile


@router.get("/{openid}/quota", response_model=DailyQuotaResponse)
def get_quota(openid: str, request: Request) -> DailyQuotaResponse:
    profile = get_user_profile(openid)
    if profile is None:
        raise HTTPException(status_code=401, detail="User must login first")
    quota = get_daily_quota(openid)
    log_operation(
        request,
        openid=openid,
        action="daily_quota_viewed",
        target_type="user",
        target_id=openid,
        detail={"remaining": quota.remaining, "total": quota.total},
    )
    return quota


@router.post("/{openid}/quota/grant", response_model=DailyQuotaResponse)
def grant_quota(
    openid: str,
    payload: QuotaGrantRequest,
    request: Request,
) -> DailyQuotaResponse:
    profile = get_user_profile(openid)
    if profile is None:
        raise HTTPException(status_code=401, detail="User must login first")
    quota = grant_daily_quota(openid, payload.extra)
    log_operation(
        request,
        openid=openid,
        action="daily_quota_granted",
        target_type="user",
        target_id=openid,
        detail={"extra": payload.extra, "remaining": quota.remaining, "total": quota.total},
    )
    return quota


@router.get("/{openid}/logs", response_model=list[OperationLogResponse])
def get_user_logs(
    openid: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OperationLogResponse]:
    profile = get_user_profile(openid)
    if profile is None:
        raise HTTPException(status_code=401, detail="User must login first")
    log_operation(
        request,
        openid=openid,
        action="operation_logs_viewed",
        target_type="user",
        target_id=openid,
        detail={"limit": limit, "offset": offset},
    )
    return list_operation_logs(openid, limit=limit, offset=offset)


def _safe_openid(openid: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in openid)


def _avatar_path(openid: str, suffix: str) -> Path:
    return settings.storage_dir_path / "avatars" / f"{_safe_openid(openid)}{suffix}"


def _find_avatar_path(openid: str) -> Path | None:
    avatar_dir = settings.storage_dir_path / "avatars"
    if not avatar_dir.exists():
        return None
    matches = sorted(avatar_dir.glob(f"{_safe_openid(openid)}.*"))
    return matches[-1] if matches else None


def _avatar_suffix(filename: str | None, content_type: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return suffix
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    return ".jpg"


def _avatar_media_type(suffix: str) -> str:
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"
