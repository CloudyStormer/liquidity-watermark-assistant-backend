from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.repositories import create_rating, get_user, list_ratings
from app.schemas.requests import RatingRequest
from app.schemas.responses import RatingResponse
from app.services.content_security import (
    CONTENT_CHECK_UNAVAILABLE_MESSAGE,
    CONTENT_RISK_MESSAGE,
    ContentSecurityUnavailable,
    ContentSecurityViolation,
    ensure_safe_text,
)
from app.services.logging import log_operation

router = APIRouter()


@router.post("", response_model=RatingResponse, status_code=201)
def submit_rating(payload: RatingRequest, request: Request) -> RatingResponse:
    _require_logged_in(payload.openid)
    try:
        ensure_safe_text(payload.openid, payload.comment, scene=2)
    except ContentSecurityViolation as exc:
        raise HTTPException(status_code=400, detail=CONTENT_RISK_MESSAGE) from exc
    except ContentSecurityUnavailable as exc:
        raise HTTPException(status_code=503, detail=CONTENT_CHECK_UNAVAILABLE_MESSAGE) from exc

    rating = create_rating(
        openid=payload.openid,
        score=payload.score,
        comment=payload.comment,
        job_id=payload.job_id,
    )
    log_operation(
        request,
        openid=payload.openid,
        action="rating_created",
        target_type="rating",
        target_id=rating.id,
        detail={"score": payload.score, "job_id": payload.job_id},
    )
    return rating


@router.get("/users/{openid}", response_model=list[RatingResponse])
def get_user_ratings(
    openid: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RatingResponse]:
    _require_logged_in(openid)
    log_operation(
        request,
        openid=openid,
        action="ratings_listed",
        target_type="user",
        target_id=openid,
        detail={"limit": limit, "offset": offset},
    )
    return list_ratings(openid, limit=limit, offset=offset)


def _require_logged_in(openid: str) -> None:
    if get_user(openid) is None:
        raise HTTPException(status_code=401, detail="User must login first")
