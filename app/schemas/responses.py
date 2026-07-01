from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import CleanupMethod, JobStatus, MediaType, WatermarkRegion


class MediaJobResponse(BaseModel):
    id: str
    openid: str
    media_type: MediaType
    original_filename: str
    method: CleanupMethod
    status: JobStatus
    regions: list[WatermarkRegion]
    error: str | None = None
    result_url: str | None = None
    result_md5: str | None = None
    created_at: datetime
    updated_at: datetime


class Md5FileResponse(BaseModel):
    id: str
    openid: str
    media_type: MediaType
    original_filename: str
    file_size: int
    original_md5: str
    unique_md5: str
    result_url: str
    created_at: datetime


class DailyQuotaResponse(BaseModel):
    openid: str
    date: str
    total: int
    used: int
    remaining: int


class RatingResponse(BaseModel):
    id: str
    openid: str
    score: int
    comment: str | None = None
    job_id: str | None = None
    created_at: datetime


class FeedbackResponse(BaseModel):
    id: str
    openid: str
    type: str
    content: str
    contact: str | None = None
    job_id: str | None = None
    created_at: datetime


class OperationLogResponse(BaseModel):
    id: int
    openid: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    detail: dict
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime
