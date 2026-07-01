from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Watermark Assistant API"
    app_env: str = "local"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    storage_dir: str = "storage"
    database_path: str = "storage/app.db"
    max_upload_bytes: int = 200 * 1024 * 1024
    ffmpeg_path: str = "ffmpeg"
    daily_free_quota: int = 3
    weapp_appid: str = ""
    weapp_secret: str = ""
    weapp_code2session_url: str = "https://api.weixin.qq.com/sns/jscode2session"
    weapp_login_timeout_seconds: float = 6.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def storage_dir_path(self) -> Path:
        return Path(self.storage_dir).resolve()

    @property
    def database_file_path(self) -> Path:
        return Path(self.database_path).resolve()

    @property
    def weapp_login_configured(self) -> bool:
        return bool(self.weapp_appid and self.weapp_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
