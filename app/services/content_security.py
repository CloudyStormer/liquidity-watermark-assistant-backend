from __future__ import annotations

import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from app.core.config import settings

CONTENT_RISK_MESSAGE = "用户所发布内容含违规信息，请更换后再提交"
CONTENT_CHECK_UNAVAILABLE_MESSAGE = "内容安全检测暂不可用，请稍后再试"

_TOKEN_VALUE = ""
_TOKEN_EXPIRES_AT = 0.0


class ContentSecurityViolation(ValueError):
    pass


class ContentSecurityUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    raw: dict


def ensure_safe_text(openid: str, content: str | None, *, scene: int = 2) -> None:
    normalized = (content or "").strip()
    if not normalized or not settings.weapp_content_security_configured:
        return

    for chunk in _text_chunks(normalized):
        payload = {
            "content": chunk,
            "version": 2,
            "scene": scene,
            "openid": openid,
        }
        result = _post_json_sec_check(settings.weapp_msg_sec_check_url, payload)
        _raise_if_unsafe(result)


def ensure_safe_image(openid: str, image_path: Path, *, scene: int = 1) -> None:
    if not settings.weapp_content_security_configured:
        return

    media = _prepare_image_for_check(image_path)
    token = _get_access_token()
    try:
        response = httpx.post(
            settings.weapp_img_sec_check_url,
            params={"access_token": token},
            files={"media": ("media.jpg", media, "image/jpeg")},
            timeout=settings.weapp_sec_check_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ContentSecurityUnavailable(CONTENT_CHECK_UNAVAILABLE_MESSAGE) from exc

    _raise_if_unsafe(CheckResult(passed=_is_pass_payload(payload), raw=payload))


def _post_json_sec_check(url: str, payload: dict) -> CheckResult:
    token = _get_access_token()
    try:
        response = httpx.post(
            url,
            params={"access_token": token},
            json=payload,
            timeout=settings.weapp_sec_check_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ContentSecurityUnavailable(CONTENT_CHECK_UNAVAILABLE_MESSAGE) from exc

    return CheckResult(passed=_is_pass_payload(data), raw=data)


def _get_access_token() -> str:
    global _TOKEN_EXPIRES_AT, _TOKEN_VALUE

    now = time.time()
    if _TOKEN_VALUE and now < _TOKEN_EXPIRES_AT:
        return _TOKEN_VALUE

    try:
        response = httpx.get(
            settings.weapp_access_token_url,
            params={
                "grant_type": "client_credential",
                "appid": settings.weapp_appid,
                "secret": settings.weapp_secret,
            },
            timeout=settings.weapp_sec_check_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ContentSecurityUnavailable(CONTENT_CHECK_UNAVAILABLE_MESSAGE) from exc

    token = payload.get("access_token")
    if not token:
        raise ContentSecurityUnavailable(CONTENT_CHECK_UNAVAILABLE_MESSAGE)

    expires_in = int(payload.get("expires_in") or 7200)
    _TOKEN_VALUE = str(token)
    _TOKEN_EXPIRES_AT = now + max(60, expires_in - 300)
    return _TOKEN_VALUE


def _is_pass_payload(payload: dict) -> bool:
    errcode = int(payload.get("errcode") or 0)
    if errcode == 87014:
        return False
    if errcode != 0:
        raise ContentSecurityUnavailable(CONTENT_CHECK_UNAVAILABLE_MESSAGE)

    result = payload.get("result")
    if isinstance(result, dict):
        return result.get("suggest") == "pass"
    return True


def _raise_if_unsafe(result: CheckResult) -> None:
    if not result.passed:
        raise ContentSecurityViolation(CONTENT_RISK_MESSAGE)


def _prepare_image_for_check(image_path: Path) -> bytes:
    try:
        with Image.open(image_path) as image:
            output = ImageOps.exif_transpose(image).convert("RGB")
            output.thumbnail((1440, 1440))
            for quality in (88, 78, 68, 58):
                buffer = BytesIO()
                output.save(buffer, format="JPEG", quality=quality, optimize=True)
                if buffer.tell() <= 1024 * 1024:
                    return buffer.getvalue()
            return buffer.getvalue()
    except Exception as exc:
        raise ContentSecurityUnavailable(CONTENT_CHECK_UNAVAILABLE_MESSAGE) from exc


def _text_chunks(content: str) -> list[str]:
    limit = 1800
    return [content[index : index + limit] for index in range(0, len(content), limit)]
