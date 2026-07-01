from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    openid: str = Field(min_length=1, max_length=128)
    nickname: str | None = Field(default=None, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=500)


class WeappLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    nickname: str | None = Field(default=None, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=500)


class QuotaGrantRequest(BaseModel):
    extra: int = Field(default=3, ge=1, le=30)


class RatingRequest(BaseModel):
    openid: str = Field(min_length=1, max_length=128)
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    job_id: str | None = Field(default=None, max_length=64)


class FeedbackRequest(BaseModel):
    openid: str = Field(min_length=1, max_length=128)
    type: str = Field(default="general", min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=3000)
    contact: str | None = Field(default=None, max_length=120)
    job_id: str | None = Field(default=None, max_length=64)
