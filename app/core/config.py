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
    inpaint_engine: str = "local"
    ai_inpaint_url: str = ""
    ai_inpaint_api_key: str = ""
    ai_inpaint_timeout_seconds: float = 45.0
    weapp_appid: str = ""
    weapp_secret: str = ""
    weapp_content_security_enabled: bool = True
    weapp_access_token_url: str = "https://api.weixin.qq.com/cgi-bin/token"
    weapp_code2session_url: str = "https://api.weixin.qq.com/sns/jscode2session"
    weapp_msg_sec_check_url: str = "https://api.weixin.qq.com/wxa/msg_sec_check"
    weapp_img_sec_check_url: str = "https://api.weixin.qq.com/wxa/img_sec_check"
    weapp_media_check_async_url: str = "https://api.weixin.qq.com/wxa/media_check_async"
    weapp_login_timeout_seconds: float = 6.0
    weapp_sec_check_timeout_seconds: float = 10.0
    public_api_base_url: str = ""

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

    @property
    def weapp_content_security_configured(self) -> bool:
        return self.weapp_content_security_enabled and self.weapp_login_configured


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
