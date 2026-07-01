from fastapi import Request

from app.repositories import create_operation_log


def log_operation(
    request: Request | None,
    *,
    openid: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    ip = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None
    create_operation_log(
        openid=openid,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip=ip,
        user_agent=user_agent,
    )
