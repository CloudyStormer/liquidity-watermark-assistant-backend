import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def calculate_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as input_file:
        while chunk := input_file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def create_unique_media_copy(source_path: Path) -> Path:
    result_path = source_path.with_name(f"unique{source_path.suffix or '.bin'}")
    marker = (
        f"\nwatermark-assistant-md5={uuid4().hex};"
        f"created_at={datetime.now(UTC).isoformat()}\n"
    ).encode()

    with source_path.open("rb") as input_file, result_path.open("wb") as output_file:
        while chunk := input_file.read(1024 * 1024):
            output_file.write(chunk)
        output_file.write(marker)

    return result_path
