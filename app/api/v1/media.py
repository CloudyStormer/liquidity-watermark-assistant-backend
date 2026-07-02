import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.core.config import settings
from app.repositories import (
    consume_daily_quota,
    create_media_job,
    get_media_job,
    get_user,
    list_media_jobs,
)
from app.schemas.common import CleanupMethod, MediaType
from app.schemas.responses import Md5FileResponse, MediaJobResponse
from app.services.file_hashing import calculate_md5, create_unique_media_copy
from app.services.logging import log_operation
from app.services.media_processing import (
    detect_media_type,
    parse_regions,
    process_media_job,
    save_upload,
)

router = APIRouter()


@router.post("/jobs/upload", response_model=MediaJobResponse, status_code=202)
async def create_upload_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    openid: Annotated[str, Form(min_length=1, max_length=128)],
    rights_confirmed: Annotated[bool, Form()],
    method: Annotated[CleanupMethod, Form()] = CleanupMethod.BLUR,
    regions_json: Annotated[str | None, Form()] = None,
) -> MediaJobResponse:
    _require_logged_in(openid)
    if not rights_confirmed:
        log_operation(
            request,
            openid=openid,
            action="media_upload_rejected",
            detail={"reason": "rights_not_confirmed", "filename": file.filename},
        )
        raise HTTPException(status_code=422, detail="rights_confirmed must be true")

    try:
        regions = parse_regions(regions_json)
    except (ValueError, ValidationError) as exc:
        log_operation(
            request,
            openid=openid,
            action="media_upload_rejected",
            detail={"reason": "invalid_regions", "error": str(exc)},
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job_id = uuid4().hex
    try:
        saved = await save_upload(job_id, file)
    except ValueError as exc:
        log_operation(
            request,
            openid=openid,
            action="media_upload_rejected",
            detail={"reason": "invalid_upload", "error": str(exc), "filename": file.filename},
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    quota = consume_daily_quota(openid)
    if quota is None:
        log_operation(
            request,
            openid=openid,
            action="media_upload_rejected",
            detail={"reason": "quota_depleted", "filename": file.filename},
        )
        raise HTTPException(status_code=429, detail="Daily free quota has been used up")

    job = create_media_job(
        job_id=job_id,
        openid=openid,
        media_type=saved.media_type,
        original_filename=saved.original_filename,
        source_path=str(saved.source_path),
        method=method,
        regions=regions,
    )
    log_operation(
        request,
        openid=openid,
        action="media_upload_created",
        target_type="media_job",
        target_id=job.id,
        detail={
            "filename": saved.original_filename,
            "media_type": saved.media_type.value,
            "method": method.value,
            "regions_count": len(regions),
        },
    )
    background_tasks.add_task(process_media_job, job.id)
    return job


@router.post("/md5/upload", response_model=Md5FileResponse, status_code=201)
async def create_md5_variant(
    request: Request,
    file: Annotated[UploadFile, File()],
    openid: Annotated[str, Form(min_length=1, max_length=128)],
    rights_confirmed: Annotated[bool, Form()] = True,
) -> Md5FileResponse:
    _require_logged_in(openid)
    if not rights_confirmed:
        log_operation(
            request,
            openid=openid,
            action="md5_upload_rejected",
            detail={"reason": "rights_not_confirmed", "filename": file.filename},
        )
        raise HTTPException(status_code=422, detail="rights_confirmed must be true")

    try:
        media_type = detect_media_type(file.filename, file.content_type)
        source_path, original_filename, file_size = await _save_md5_upload(uuid4().hex, file)
    except ValueError as exc:
        log_operation(
            request,
            openid=openid,
            action="md5_upload_rejected",
            detail={"reason": "invalid_upload", "error": str(exc), "filename": file.filename},
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job_id = source_path.parent.name
    original_md5 = calculate_md5(source_path)
    result_path = create_unique_media_copy(source_path)
    unique_md5 = calculate_md5(result_path)
    created_at = datetime.now(UTC).replace(microsecond=0)

    metadata = {
        "openid": openid,
        "media_type": media_type.value,
        "original_filename": original_filename,
        "result_filename": _result_filename(original_filename),
        "result_path": str(result_path),
        "result_media_type": _media_download_type(media_type),
        "created_at": created_at.isoformat(),
    }
    _md5_metadata_path(job_id).write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    log_operation(
        request,
        openid=openid,
        action="md5_variant_created",
        target_type="md5_file",
        target_id=job_id,
        detail={
            "filename": original_filename,
            "media_type": media_type.value,
            "file_size": file_size,
            "original_md5": original_md5,
            "unique_md5": unique_md5,
        },
    )

    return Md5FileResponse(
        id=job_id,
        openid=openid,
        media_type=media_type,
        original_filename=original_filename,
        file_size=file_size,
        original_md5=original_md5,
        unique_md5=unique_md5,
        result_url=f"/api/media/md5/{job_id}/download?openid={openid}",
        created_at=created_at,
    )


@router.get("/md5/{job_id}/download")
def download_md5_variant(
    job_id: str,
    request: Request,
    openid: Annotated[str, Query(min_length=1, max_length=128)],
) -> FileResponse:
    metadata = _load_md5_metadata(job_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="MD5 file not found")
    if metadata["openid"] != openid:
        raise HTTPException(status_code=403, detail="MD5 file does not belong to this openid")

    result_path = Path(metadata["result_path"])
    if not result_path.exists():
        raise HTTPException(status_code=410, detail="MD5 result file is missing")

    log_operation(
        request,
        openid=openid,
        action="md5_variant_downloaded",
        target_type="md5_file",
        target_id=job_id,
        detail={"media_type": metadata["media_type"]},
    )
    return FileResponse(
        result_path,
        media_type=metadata.get("result_media_type") or "application/octet-stream",
        filename=metadata["result_filename"],
    )


@router.get("/jobs/{job_id}", response_model=MediaJobResponse)
def get_job(
    job_id: str,
    request: Request,
    openid: Annotated[str, Query(min_length=1, max_length=128)],
) -> MediaJobResponse:
    job = _get_owned_job(job_id, openid)
    log_operation(
        request,
        openid=openid,
        action="media_job_viewed",
        target_type="media_job",
        target_id=job.id,
        detail={"status": job.status.value},
    )
    return job


@router.get("/jobs/{job_id}/download")
def download_job_result(
    job_id: str,
    request: Request,
    openid: Annotated[str, Query(min_length=1, max_length=128)],
) -> FileResponse:
    job = _get_owned_job(job_id, openid)
    stored = get_media_job(job_id)
    if job.status != "succeeded" or stored is None or job.result_url is None:
        raise HTTPException(status_code=409, detail="Job result is not ready")

    from app.db import get_connection

    with get_connection() as connection:
        row = connection.execute(
            "SELECT result_path, result_media_type FROM media_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None or row["result_path"] is None:
        raise HTTPException(status_code=409, detail="Job result is not ready")

    result_path = Path(row["result_path"])
    if not result_path.exists():
        raise HTTPException(status_code=410, detail="Job result file is missing")

    log_operation(
        request,
        openid=openid,
        action="media_job_downloaded",
        target_type="media_job",
        target_id=job.id,
        detail={"media_type": job.media_type.value},
    )
    suffix = ".png" if job.media_type.value == "image" else ".mp4"
    return FileResponse(
        result_path,
        media_type=row["result_media_type"] or "application/octet-stream",
        filename=f"{job.id}{suffix}",
    )


@router.get("/users/{openid}/jobs", response_model=list[MediaJobResponse])
def get_user_jobs(
    openid: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MediaJobResponse]:
    _require_logged_in(openid)
    log_operation(
        request,
        openid=openid,
        action="media_jobs_listed",
        target_type="user",
        target_id=openid,
        detail={"limit": limit, "offset": offset},
    )
    return list_media_jobs(openid, limit=limit, offset=offset)


def _get_owned_job(job_id: str, openid: str) -> MediaJobResponse:
    job = get_media_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Media job not found")
    if job.openid != openid:
        raise HTTPException(status_code=403, detail="Media job does not belong to this openid")
    return job


def _require_logged_in(openid: str) -> None:
    if get_user(openid) is None:
        raise HTTPException(status_code=401, detail="User must login first")


async def _save_md5_upload(job_id: str, upload: UploadFile) -> tuple[Path, str, int]:
    media_type = detect_media_type(upload.filename, upload.content_type)
    original_filename = upload.filename or f"upload.{media_type.value}"
    suffix = Path(original_filename).suffix.lower()
    if not suffix:
        suffix = ".png" if media_type == MediaType.IMAGE else ".mp4"

    source_path = settings.storage_dir_path / "md5" / job_id / f"source{suffix}"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with source_path.open("wb") as output_file:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise ValueError("Uploaded file exceeds MAX_UPLOAD_BYTES")
            output_file.write(chunk)

    return source_path, original_filename, total


def _md5_metadata_path(job_id: str) -> Path:
    return settings.storage_dir_path / "md5" / job_id / "metadata.json"


def _load_md5_metadata(job_id: str) -> dict | None:
    metadata_path = _md5_metadata_path(job_id)
    if not metadata_path.exists():
        return None
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _media_download_type(media_type: MediaType) -> str:
    return "image/png" if media_type == MediaType.IMAGE else "video/mp4"


def _result_filename(original_filename: str) -> str:
    path = Path(original_filename)
    suffix = path.suffix or ".bin"
    stem = path.stem or "media"
    return f"{stem}_unique{suffix}"
