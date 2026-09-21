from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def sample_jpeg_bytes() -> bytes:
    """A small synthetic in-memory JPEG — enough to exercise the image
    pipeline without needing a real business card on disk."""
    img = Image.new("RGB", (800, 500), color=(240, 240, 235))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture
def sample_png_bytes() -> bytes:
    img = Image.new("RGBA", (400, 300), color=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    (tmp_path / "uploads").mkdir()
    (tmp_path / "thumbnails").mkdir()
    return tmp_path
