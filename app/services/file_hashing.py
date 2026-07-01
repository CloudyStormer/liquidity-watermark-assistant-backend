import hashlib
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.config import settings

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


def calculate_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as input_file:
        while chunk := input_file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def create_unique_media_copy(source_path: Path) -> Path:
    result_path = source_path.with_name(f"unique{source_path.suffix or '.bin'}")
    if source_path.suffix.lower() in VIDEO_EXTENSIONS and _rewrite_video_metadata(
        source_path,
        result_path,
    ):
        return result_path

    _copy_with_unique_marker(source_path, result_path)
    return result_path


def _rewrite_video_metadata(source_path: Path, result_path: Path) -> bool:
    ffmpeg_path = shutil.which(settings.ffmpeg_path)
    if ffmpeg_path is None:
        return False

    unique_id = uuid4().hex
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0",
        "-c",
        "copy",
        "-metadata",
        f"watermark_assistant_uid={unique_id}",
        "-metadata",
        f"comment=md5-unique-{unique_id}",
        "-metadata",
        f"creation_time={datetime.now(UTC).replace(microsecond=0).isoformat()}",
        "-movflags",
        "use_metadata_tags",
        str(result_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode == 0 and result_path.exists() and result_path.stat().st_size > 0


def _copy_with_unique_marker(source_path: Path, result_path: Path) -> None:
    marker = (
        f"\nwatermark-assistant-md5={uuid4().hex};"
        f"created_at={datetime.now(UTC).isoformat()}\n"
    ).encode()

    with source_path.open("rb") as input_file, result_path.open("wb") as output_file:
        while chunk := input_file.read(1024 * 1024):
            output_file.write(chunk)
        output_file.write(marker)
