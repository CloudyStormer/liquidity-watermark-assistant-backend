from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.repositories import create_feedback, list_feedback
from app.schemas.requests import FeedbackRequest
from app.schemas.responses import FeedbackResponse
from app.services.logging import log_operation

router = APIRouter()


@router.post("", response_model=FeedbackResponse, status_code=201)
def submit_feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
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
    log_operation(
        request,
        openid=openid,
        action="feedback_listed",
        target_type="user",
        target_id=openid,
        detail={"limit": limit, "offset": offset},
    )
    return list_feedback(openid, limit=limit, offset=offset)
