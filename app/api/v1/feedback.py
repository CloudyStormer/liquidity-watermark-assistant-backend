from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.repositories import create_feedback, get_user, list_feedback
from app.schemas.requests import FeedbackRequest
from app.schemas.responses import FeedbackResponse
from app.services.content_security import (
    CONTENT_CHECK_UNAVAILABLE_MESSAGE,
    CONTENT_RISK_MESSAGE,
    ContentSecurityUnavailable,
    ContentSecurityViolation,
    ensure_safe_text,
)
from app.services.logging import log_operation

router = APIRouter()


@router.post("", response_model=FeedbackResponse, status_code=201)
def submit_feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
    _require_logged_in(payload.openid)
    try:
        ensure_safe_text(payload.openid, payload.content, scene=2)
        ensure_safe_text(payload.openid, payload.contact, scene=2)
    except ContentSecurityViolation as exc:
        raise HTTPException(status_code=400, detail=CONTENT_RISK_MESSAGE) from exc
    except ContentSecurityUnavailable as exc:
        raise HTTPException(status_code=503, detail=CONTENT_CHECK_UNAVAILABLE_MESSAGE) from exc

    feedback = create_feedback(
        openid=payload.openid,
        feedback_type=payload.type,
        content=payload.content,
        contact=payload.contact,
        job_id=payload.job_id,
    )
    log_operation(
        request,
        openid=payload.openid,
        action="feedback_created",
        target_type="feedback",
        target_id=feedback.id,
        detail={"type": payload.type, "job_id": payload.job_id},
    )
    return feedback


@router.get("/users/{openid}", response_model=list[FeedbackResponse])
def get_user_feedback(
    openid: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FeedbackResponse]:
    _require_logged_in(openid)
    log_operation(
        request,
        openid=openid,
        action="feedback_listed",
        target_type="user",
        target_id=openid,
        detail={"limit": limit, "offset": offset},
    )
    return list_feedback(openid, limit=limit, offset=offset)


def _require_logged_in(openid: str) -> None:
    if get_user(openid) is None:
        raise HTTPException(status_code=401, detail="User must login first")
