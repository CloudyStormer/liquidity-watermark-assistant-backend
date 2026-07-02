import json
from datetime import UTC, datetime
from sqlite3 import Row
from uuid import uuid4

from app.core.config import settings
from app.db import get_connection
from app.schemas.common import (
    CleanupMethod,
    JobStatus,
    MediaType,
    UserProfileResponse,
    UserResponse,
    WatermarkRegion,
)
from app.schemas.responses import (
    DailyQuotaResponse,
    FeedbackResponse,
    MediaJobResponse,
    OperationLogResponse,
    RatingResponse,
)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def upsert_user(
    *,
    openid: str,
    nickname: str | None = None,
    avatar_url: str | None = None,
) -> UserResponse:
    timestamp = now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (openid, nickname, avatar_url, created_at, updated_at, last_login_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(openid) DO UPDATE SET
              nickname = COALESCE(excluded.nickname, users.nickname),
              avatar_url = COALESCE(excluded.avatar_url, users.avatar_url),
              updated_at = excluded.updated_at,
              last_login_at = excluded.last_login_at
            """,
            (openid, nickname, avatar_url, timestamp, timestamp, timestamp),
        )
        row = connection.execute("SELECT * FROM users WHERE openid = ?", (openid,)).fetchone()
    return _row_to_user(row)


def ensure_user(openid: str) -> UserResponse:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM users WHERE openid = ?", (openid,)).fetchone()
    if row is not None:
        return _row_to_user(row)
    return upsert_user(openid=openid)


def get_user(openid: str) -> UserResponse | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM users WHERE openid = ?", (openid,)).fetchone()
    return _row_to_user(row) if row is not None else None


def get_user_profile(openid: str) -> UserProfileResponse | None:
    with get_connection() as connection:
        user_row = connection.execute("SELECT * FROM users WHERE openid = ?", (openid,)).fetchone()
        if user_row is None:
            return None

        total_jobs = _count(connection, "media_jobs", openid)
        succeeded_jobs = _count(connection, "media_jobs", openid, status=JobStatus.SUCCEEDED.value)
        failed_jobs = _count(connection, "media_jobs", openid, status=JobStatus.FAILED.value)
        ratings_count = _count(connection, "ratings", openid)
        feedback_count = _count(connection, "feedback", openid)
        usage_total = _sum_daily_quota_used(connection, openid)
        latest_rating = _latest_rating(connection, openid)

    return UserProfileResponse(
        user=_row_to_user(user_row),
        usage_total=usage_total,
        total_jobs=total_jobs,
        succeeded_jobs=succeeded_jobs,
        failed_jobs=failed_jobs,
        ratings_count=ratings_count,
        feedback_count=feedback_count,
        latest_rating_score=latest_rating.score if latest_rating else None,
        latest_rating_comment=latest_rating.comment if latest_rating else None,
        latest_rating_at=latest_rating.created_at if latest_rating else None,
    )


def create_media_job(
    *,
    openid: str,
    media_type: MediaType,
    original_filename: str,
    source_path: str,
    method: CleanupMethod,
    regions: list[WatermarkRegion],
    job_id: str | None = None,
) -> MediaJobResponse:
    ensure_user(openid)
    timestamp = now_iso()
    job_id = job_id or uuid4().hex
    regions_json = json.dumps([region.model_dump() for region in regions], ensure_ascii=False)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO media_jobs (
              id, openid, media_type, original_filename, source_path, method, status,
              regions_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                openid,
                media_type.value,
                original_filename,
                source_path,
                method.value,
                JobStatus.QUEUED.value,
                regions_json,
                timestamp,
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM media_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_media_job(row)


def update_media_job(
    job_id: str,
    *,
    status: JobStatus,
    result_path: str | None = None,
    result_media_type: str | None = None,
    result_md5: str | None = None,
    error: str | None = None,
) -> MediaJobResponse:
    timestamp = now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE media_jobs
            SET status = ?, result_path = COALESCE(?, result_path),
                result_media_type = COALESCE(?, result_media_type),
                result_md5 = COALESCE(?, result_md5),
                error = ?, updated_at = ?
            WHERE id = ?
            """,
            (status.value, result_path, result_media_type, result_md5, error, timestamp, job_id),
        )
        row = connection.execute("SELECT * FROM media_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_media_job(row)


def get_media_job(job_id: str) -> MediaJobResponse | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM media_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_media_job(row) if row is not None else None


def list_media_jobs(openid: str, *, limit: int, offset: int) -> list[MediaJobResponse]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM media_jobs
            WHERE openid = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (openid, limit, offset),
        ).fetchall()
    return [_row_to_media_job(row) for row in rows]


def get_daily_quota(openid: str) -> DailyQuotaResponse:
    ensure_user(openid)
    quota_date = _quota_date()
    timestamp = now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO daily_quotas (
              openid, quota_date, used, bonus, created_at, updated_at
            )
            VALUES (?, ?, 0, 0, ?, ?)
            """,
            (openid, quota_date, timestamp, timestamp),
        )
        row = connection.execute(
            "SELECT * FROM daily_quotas WHERE openid = ? AND quota_date = ?",
            (openid, quota_date),
        ).fetchone()
    return _row_to_daily_quota(row)


def consume_daily_quota(openid: str) -> DailyQuotaResponse | None:
    quota = get_daily_quota(openid)
    if quota.remaining <= 0:
        return None

    timestamp = now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE daily_quotas
            SET used = used + 1, updated_at = ?
            WHERE openid = ? AND quota_date = ?
            """,
            (timestamp, openid, quota.date),
        )
        row = connection.execute(
            "SELECT * FROM daily_quotas WHERE openid = ? AND quota_date = ?",
            (openid, quota.date),
        ).fetchone()
    return _row_to_daily_quota(row)


def grant_daily_quota(openid: str, extra: int) -> DailyQuotaResponse:
    quota = get_daily_quota(openid)
    timestamp = now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE daily_quotas
            SET bonus = bonus + ?, updated_at = ?
            WHERE openid = ? AND quota_date = ?
            """,
            (extra, timestamp, openid, quota.date),
        )
        row = connection.execute(
            "SELECT * FROM daily_quotas WHERE openid = ? AND quota_date = ?",
            (openid, quota.date),
        ).fetchone()
    return _row_to_daily_quota(row)


def create_rating(
    *,
    openid: str,
    score: int,
    comment: str | None,
    job_id: str | None,
) -> RatingResponse:
    ensure_user(openid)
    timestamp = now_iso()
    rating_id = uuid4().hex
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO ratings (id, openid, score, comment, job_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (rating_id, openid, score, comment, job_id, timestamp),
        )
        row = connection.execute("SELECT * FROM ratings WHERE id = ?", (rating_id,)).fetchone()
    return _row_to_rating(row)


def list_ratings(openid: str, *, limit: int, offset: int) -> list[RatingResponse]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM ratings
            WHERE openid = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (openid, limit, offset),
        ).fetchall()
    return [_row_to_rating(row) for row in rows]


def create_feedback(
    *,
    openid: str,
    feedback_type: str,
    content: str,
    contact: str | None,
    job_id: str | None,
) -> FeedbackResponse:
    ensure_user(openid)
    timestamp = now_iso()
    feedback_id = uuid4().hex
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO feedback (id, openid, type, content, contact, job_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (feedback_id, openid, feedback_type, content, contact, job_id, timestamp),
        )
        row = connection.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    return _row_to_feedback(row)


def list_feedback(openid: str, *, limit: int, offset: int) -> list[FeedbackResponse]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM feedback
            WHERE openid = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (openid, limit, offset),
        ).fetchall()
    return [_row_to_feedback(row) for row in rows]


def create_operation_log(
    *,
    openid: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> OperationLogResponse:
    timestamp = now_iso()
    detail_json = json.dumps(detail or {}, ensure_ascii=False)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO operation_logs (
              openid, action, target_type, target_id, detail_json, ip, user_agent, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (openid, action, target_type, target_id, detail_json, ip, user_agent, timestamp),
        )
        row = connection.execute(
            "SELECT * FROM operation_logs WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _row_to_operation_log(row)


def list_operation_logs(openid: str, *, limit: int, offset: int) -> list[OperationLogResponse]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM operation_logs
            WHERE openid = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (openid, limit, offset),
        ).fetchall()
    return [_row_to_operation_log(row) for row in rows]


def _count(connection, table: str, openid: str, *, status: str | None = None) -> int:
    if status is None:
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE openid = ?",
            (openid,),
        ).fetchone()
    else:
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE openid = ? AND status = ?",
            (openid, status),
        ).fetchone()
    return int(row["count"])


def _sum_daily_quota_used(connection, openid: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(SUM(used), 0) AS total_used FROM daily_quotas WHERE openid = ?",
        (openid,),
    ).fetchone()
    return int(row["total_used"])


def _latest_rating(connection, openid: str) -> RatingResponse | None:
    row = connection.execute(
        """
        SELECT * FROM ratings
        WHERE openid = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (openid,),
    ).fetchone()
    return _row_to_rating(row) if row is not None else None


def _row_to_user(row: Row) -> UserResponse:
    return UserResponse(**dict(row))


def _row_to_media_job(row: Row) -> MediaJobResponse:
    data = dict(row)
    result_url = None
    if data.get("result_path") and data["status"] == JobStatus.SUCCEEDED.value:
        result_url = f"/api/media/jobs/{data['id']}/download?openid={data['openid']}"

    return MediaJobResponse(
        id=data["id"],
        openid=data["openid"],
        media_type=data["media_type"],
        original_filename=data["original_filename"],
        method=data["method"],
        status=data["status"],
        regions=[WatermarkRegion.model_validate(item) for item in json.loads(data["regions_json"])],
        error=data["error"],
        result_url=result_url,
        result_md5=data.get("result_md5"),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _quota_date() -> str:
    return datetime.now(UTC).date().isoformat()


def _row_to_daily_quota(row: Row) -> DailyQuotaResponse:
    data = dict(row)
    total = settings.daily_free_quota + int(data["bonus"])
    used = int(data["used"])
    return DailyQuotaResponse(
        openid=data["openid"],
        date=data["quota_date"],
        total=total,
        used=used,
        remaining=max(0, total - used),
    )


def _row_to_rating(row: Row) -> RatingResponse:
    return RatingResponse(**dict(row))


def _row_to_feedback(row: Row) -> FeedbackResponse:
    return FeedbackResponse(**dict(row))


def _row_to_operation_log(row: Row) -> OperationLogResponse:
    data = dict(row)
    return OperationLogResponse(
        id=data["id"],
        openid=data["openid"],
        action=data["action"],
        target_type=data["target_type"],
        target_id=data["target_id"],
        detail=json.loads(data["detail_json"]),
        ip=data["ip"],
        user_agent=data["user_agent"],
        created_at=data["created_at"],
    )
