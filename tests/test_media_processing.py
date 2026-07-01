from pathlib import Path

import pytest

from app.schemas.common import CleanupMethod, MediaType, WatermarkRegion
from app.services.media_processing import (
    build_video_ffmpeg_command,
    detect_media_type,
    parse_regions,
)


def test_detect_media_type() -> None:
    assert detect_media_type("demo.png", "image/png") == MediaType.IMAGE
    assert detect_media_type("demo.mp4", "video/mp4") == MediaType.VIDEO


def test_parse_regions_accepts_single_object() -> None:
    regions = parse_regions('{"x": 1, "y": 2, "width": 30, "height": 40}')

    assert regions == [WatermarkRegion(x=1, y=2, width=30, height=40)]


def test_parse_regions_rejects_invalid_json() -> None:
    with pytest.raises(ValueError):
        parse_regions("{bad")


def test_build_video_blur_command_contains_regions() -> None:
    command = build_video_ffmpeg_command(
        ffmpeg_path="ffmpeg",
        source_path=Path("input.mp4"),
        result_path=Path("output.mp4"),
        regions=[WatermarkRegion(x=10, y=20, width=100, height=60, blur_radius=18)],
        method=CleanupMethod.BLUR,
    )

    assert "-filter_complex" in command
    assert any("crop=100:60:10:20,boxblur=18:1" in part for part in command)
