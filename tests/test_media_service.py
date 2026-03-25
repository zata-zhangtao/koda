"""Tests for media upload helpers."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from dsl.services.media_service import MediaService
from utils.settings import config


def _build_bmp_image_bytes() -> bytes:
    """Build a tiny BMP image payload for upload tests.

    Returns:
        bytes: Encoded BMP image bytes.
    """
    image_buffer = io.BytesIO()
    image = Image.new("RGB", (8, 8), color=(12, 34, 56))
    image.save(image_buffer, format="BMP")
    return image_buffer.getvalue()


def test_save_image_accepts_bmp_upload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """BMP screenshots should be accepted by the image upload pipeline."""
    media_storage_path = tmp_path / "media"
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_PATH", media_storage_path)

    upload_file = UploadFile(
        file=io.BytesIO(_build_bmp_image_bytes()),
        filename="clipboard.bmp",
        headers=Headers({"content-type": "image/bmp"}),
    )

    original_relative_path, thumbnail_relative_path = asyncio.run(
        MediaService.save_image(upload_file)
    )

    assert original_relative_path.endswith(".png")
    assert thumbnail_relative_path.endswith(".png")
    assert (tmp_path / original_relative_path).exists()
    assert (tmp_path / thumbnail_relative_path).exists()
