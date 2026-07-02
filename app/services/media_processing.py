import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageFilter, ImageOps

from app.core.config import settings
from app.repositories import create_operation_log, get_media_job, update_media_job
from app.schemas.common import CleanupMethod, JobStatus, MediaType, WatermarkRegion
from app.services.file_hashing import calculate_md5

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png"}
VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-msvideo",
    "video/x-matroska",
}


@dataclass(frozen=True)
class UploadSaveResult:
    media_type: MediaType
    source_path: Path
    original_filename: str


def detect_media_type(filename: str | None, content_type: str | None) -> MediaType:
    suffix = Path(filename or "").suffix.lower()
    normalized_content_type = (content_type or "").split(";")[0].lower()

    if suffix in IMAGE_EXTENSIONS or normalized_content_type in IMAGE_CONTENT_TYPES:
        return MediaType.IMAGE
    if suffix in VIDEO_EXTENSIONS or normalized_content_type in VIDEO_CONTENT_TYPES:
        return MediaType.VIDEO

    raise ValueError("Only image jpg/png and video mp4/mov/webm/avi/mkv uploads are supported")


async def save_upload(job_id: str, upload: UploadFile) -> UploadSaveResult:
    media_type = detect_media_type(upload.filename, upload.content_type)
    original_filename = upload.filename or f"upload.{media_type.value}"
    suffix = Path(original_filename).suffix.lower()
    if not suffix:
        suffix = ".png" if media_type == MediaType.IMAGE else ".mp4"

    source_path = settings.storage_dir_path / "jobs" / job_id / f"source{suffix}"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with source_path.open("wb") as output_file:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise ValueError("Uploaded file exceeds MAX_UPLOAD_BYTES")
            output_file.write(chunk)

    return UploadSaveResult(
        media_type=media_type,
        source_path=source_path,
        original_filename=original_filename,
    )


def parse_regions(regions_json: str | None) -> list[WatermarkRegion]:
    if not regions_json:
        return []

    try:
        raw = json.loads(regions_json)
    except json.JSONDecodeError as exc:
        raise ValueError("regions_json must be valid JSON") from exc

    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("regions_json must be an object or array")

    return [WatermarkRegion.model_validate(item) for item in raw]


def process_media_job(job_id: str) -> None:
    job = get_media_job(job_id)
    if job is None:
        return

    update_media_job(job_id, status=JobStatus.RUNNING)
    create_operation_log(
        openid=job.openid,
        action="media_job_started",
        target_type="media_job",
        target_id=job.id,
        detail={"media_type": job.media_type.value, "method": job.method.value},
    )

    try:
        stored_job = _get_stored_job(job_id)
        source_path = Path(stored_job["source_path"])
        if job.media_type == MediaType.IMAGE:
            result_path = _process_image(source_path, job.regions, job.method)
            result_media_type = "image/png"
        else:
            result_path = _process_video(source_path, job.regions, job.method)
            result_media_type = "video/mp4"

        update_media_job(
            job_id,
            status=JobStatus.SUCCEEDED,
            result_path=str(result_path),
            result_media_type=result_media_type,
            result_md5=calculate_md5(result_path),
        )
        create_operation_log(
            openid=job.openid,
            action="media_job_succeeded",
            target_type="media_job",
            target_id=job.id,
            detail={"result_media_type": result_media_type},
        )
    except Exception as exc:
        update_media_job(job_id, status=JobStatus.FAILED, error=str(exc))
        create_operation_log(
            openid=job.openid,
            action="media_job_failed",
            target_type="media_job",
            target_id=job.id,
            detail={"error": str(exc)},
        )


def build_video_ffmpeg_command(
    *,
    ffmpeg_path: str,
    source_path: Path,
    result_path: Path,
    regions: list[WatermarkRegion],
    method: CleanupMethod,
) -> list[str]:
    if method == CleanupMethod.INPAINT:
        raise ValueError("Video inpaint is not supported; use blur for video jobs")

    filters = _build_video_blur_filter(regions)
    return [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-filter_complex",
        filters,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "copy",
        str(result_path),
    ]


def _process_image(
    source_path: Path,
    regions: list[WatermarkRegion],
    method: CleanupMethod,
) -> Path:
    result_path = source_path.parent / "result.png"
    with Image.open(source_path) as image:
        output = ImageOps.exif_transpose(image).convert("RGBA")
        selected_regions = regions or _default_image_regions(output.width, output.height)

        region_boxes = [
            (region, box)
            for region in selected_regions
            if (box := _clamped_box(region, output.width, output.height)) is not None
        ]
        boxes = [box for _, box in region_boxes]
        if method == CleanupMethod.INPAINT:
            _apply_inpaint_regions(output, boxes)
        else:
            for region, box in region_boxes:
                _apply_blur(output, box, region.blur_radius)

        output.save(result_path, format="PNG")
    return result_path


def _process_video(
    source_path: Path,
    regions: list[WatermarkRegion],
    method: CleanupMethod,
) -> Path:
    ffmpeg_path = shutil.which(settings.ffmpeg_path)
    if ffmpeg_path is None:
        raise RuntimeError("FFmpeg is required for video processing but was not found")

    result_path = source_path.parent / "result.mp4"
    command = build_video_ffmpeg_command(
        ffmpeg_path=ffmpeg_path,
        source_path=source_path,
        result_path=result_path,
        regions=regions,
        method=method,
    )
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "FFmpeg failed")
    return result_path


def _apply_blur(image: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    patch = image.crop(box).filter(ImageFilter.GaussianBlur(radius=radius))
    image.paste(patch, box)


def _apply_inpaint_regions(image: Image.Image, boxes: list[tuple[int, int, int, int]]) -> None:
    if not boxes:
        return
    if _apply_opencv_inpaint(image, boxes):
        return
    for box in boxes:
        _apply_soft_fill(image, box)


def _apply_opencv_inpaint(image: Image.Image, boxes: list[tuple[int, int, int, int]]) -> bool:
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except Exception:
        return False

    rgb_image = image.convert("RGB")
    source = np.array(rgb_image)
    mask = np.zeros((image.height, image.width), dtype=np.uint8)
    expand = max(2, min(image.width, image.height) // 360)
    for left, top, right, bottom in boxes:
        mask[
            max(0, top - expand) : min(image.height, bottom + expand),
            max(0, left - expand) : min(image.width, right + expand),
        ] = 255

    if not np.any(mask):
        return True

    kernel_size = max(3, expand * 2 + 1)
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)

    radius = max(3, min(9, min(image.width, image.height) // 220))
    telea = cv2.inpaint(source, mask, radius, cv2.INPAINT_TELEA)
    navier = cv2.inpaint(source, mask, radius, cv2.INPAINT_NS)
    repaired = cv2.addWeighted(telea, 0.72, navier, 0.28, 0)

    alpha = mask.astype(np.float32) / 255.0
    alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=max(1.2, expand * 0.9))
    alpha = np.clip(alpha[..., None], 0, 1)
    blended_float = repaired.astype(np.float32) * alpha + source.astype(np.float32) * (1 - alpha)
    blended = blended_float.astype(np.uint8)

    repaired_image = Image.fromarray(blended).convert("RGBA")
    if image.mode == "RGBA":
        repaired_image.putalpha(image.getchannel("A"))
    image.paste(repaired_image)
    return True


def _apply_soft_fill(image: Image.Image, box: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = box
    pad = max(8, min(image.width, image.height) // 80)
    sample_box = (
        max(0, left - pad),
        max(0, top - pad),
        min(image.width, right + pad),
        min(image.height, bottom + pad),
    )
    sample = image.crop(sample_box).filter(ImageFilter.GaussianBlur(radius=18))
    patch = sample.resize((right - left, bottom - top))
    image.paste(patch, box)


def _clamped_box(
    region: WatermarkRegion,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    left = min(region.x, width)
    top = min(region.y, height)
    right = min(region.x + region.width, width)
    bottom = min(region.y + region.height, height)
    if left >= right or top >= bottom:
        return None
    return left, top, right, bottom


def _default_image_regions(width: int, height: int) -> list[WatermarkRegion]:
    region_width = max(32, int(width * 0.24))
    region_height = max(24, int(height * 0.14))
    return [
        WatermarkRegion(x=0, y=0, width=region_width, height=region_height, blur_radius=24),
        WatermarkRegion(
            x=max(0, width - region_width),
            y=max(0, height - region_height),
            width=region_width,
            height=region_height,
            blur_radius=24,
        ),
    ]


def _build_video_blur_filter(regions: list[WatermarkRegion]) -> str:
    filter_regions = _video_filter_regions(regions)
    split_labels = "".join(f"[wm{index}]" for index in range(len(filter_regions)))
    filters = [f"[0:v]split={len(filter_regions) + 1}[base]{split_labels}"]

    for index, region in enumerate(filter_regions):
        filters.append(
            f"[wm{index}]crop={region['width']}:{region['height']}:"
            f"{region['crop_x']}:{region['crop_y']},"
            f"boxblur={region['blur_radius']}:1[blur{index}]"
        )

    current = "base"
    for index, region in enumerate(filter_regions):
        output = "v" if index == len(filter_regions) - 1 else f"tmp{index}"
        filters.append(
            f"[{current}][blur{index}]overlay={region['overlay_x']}:{region['overlay_y']}[{output}]"
        )
        current = output

    return ";".join(filters)


def _video_filter_regions(regions: list[WatermarkRegion]) -> list[dict[str, str | int]]:
    if regions:
        return [
            {
                "crop_x": str(region.x),
                "crop_y": str(region.y),
                "overlay_x": str(region.x),
                "overlay_y": str(region.y),
                "width": str(region.width),
                "height": str(region.height),
                "blur_radius": region.blur_radius,
            }
            for region in regions
        ]

    return [
        {
            "crop_x": "0",
            "crop_y": "0",
            "overlay_x": "0",
            "overlay_y": "0",
            "width": "iw*0.24",
            "height": "ih*0.14",
            "blur_radius": 24,
        },
        {
            "crop_x": "iw-iw*0.28",
            "crop_y": "ih-ih*0.16",
            "overlay_x": "main_w-overlay_w",
            "overlay_y": "main_h-overlay_h",
            "width": "iw*0.28",
            "height": "ih*0.16",
            "blur_radius": 24,
        },
    ]


def _get_stored_job(job_id: str) -> dict:
    from app.db import get_connection

    with get_connection() as connection:
        row = connection.execute("SELECT * FROM media_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise ValueError("Media job not found")
    return dict(row)
