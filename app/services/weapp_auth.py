from dataclasses import dataclass

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class WeappSession:
    openid: str
    session_key: str | None = None
    unionid: str | None = None


class WeappLoginConfigError(RuntimeError):
    pass


def exchange_code_for_session(code: str) -> WeappSession:
    if not settings.weapp_login_configured:
        raise WeappLoginConfigError("WEAPP_APPID and WEAPP_SECRET must be configured")

    response = httpx.get(
        settings.weapp_code2session_url,
        params={
            "appid": settings.weapp_appid,
            "secret": settings.weapp_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        },
        timeout=settings.weapp_login_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()

    errcode = int(payload.get("errcode") or 0)
    if errcode:
        errmsg = payload.get("errmsg") or "unknown error"
        raise ValueError(f"WeChat code2Session failed: {errcode} {errmsg}")

    openid = payload.get("openid")
    if not openid:
        raise ValueError("WeChat code2Session response missing openid")

    return WeappSession(
        openid=openid,
        session_key=payload.get("session_key"),
        unionid=payload.get("unionid"),
    )
