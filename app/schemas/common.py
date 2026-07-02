from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class CleanupMethod(StrEnum):
    BLUR = "blur"
    INPAINT = "inpaint"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WatermarkRegion(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    blur_radius: int = Field(default=20, ge=2, le=100)


class UserResponse(BaseModel):
    openid: str
    nickname: str | None = None
    avatar_url: str | None = None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime


class UserProfileResponse(BaseModel):
    user: UserResponse
    usage_total: int
    total_jobs: int
    succeeded_jobs: int
    failed_jobs: int
    ratings_count: int
    feedback_count: int
    latest_rating_score: int | None = None
    latest_rating_comment: str | None = None
    latest_rating_at: datetime | None = None
