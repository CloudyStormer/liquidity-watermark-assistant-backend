from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

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
    log_operation(
        request,
        openid=openid,
        action="operation_logs_viewed",
        target_type="user",
        target_id=openid,
        detail={"limit": limit, "offset": offset},
    )
    return list_operation_logs(openid, limit=limit, offset=offset)
