from __future__ import annotations

import pytest

from app.image_pipeline import (
    ImageTooLargeError,
    UnsupportedImageError,
    preprocess_image,
    sniff_mime_type,
    validate_upload,
)


def test_sniff_jpeg(sample_jpeg_bytes):
    assert sniff_mime_type(sample_jpeg_bytes) == "image/jpeg"


def test_sniff_png(sample_png_bytes):
    assert sniff_mime_type(sample_png_bytes) == "image/png"


def test_sniff_unknown_returns_none():
    assert sniff_mime_type(b"not an image at all") is None


def test_validate_upload_accepts_valid_jpeg(sample_jpeg_bytes):
    mime = validate_upload(
        sample_jpeg_bytes, max_bytes=10_000_000, allowed_mime_types=("image/jpeg", "image/png")
    )
    assert mime == "image/jpeg"


def test_validate_upload_rejects_oversized(sample_jpeg_bytes):
    with pytest.raises(ImageTooLargeError):
        validate_upload(sample_jpeg_bytes, max_bytes=10, allowed_mime_types=("image/jpeg",))


def test_validate_upload_rejects_disguised_non_image():
    # A text file renamed to .jpg — magic-byte sniffing must catch this even
    # though a naive check on the filename extension would not.
    fake = b"<html><body>not an image</body></html>"
    with pytest.raises(UnsupportedImageError):
        validate_upload(fake, max_bytes=10_000_000, allowed_mime_types=("image/jpeg", "image/png"))


def test_validate_upload_rejects_empty():
    with pytest.raises(UnsupportedImageError):
        validate_upload(b"", max_bytes=10_000_000, allowed_mime_types=("image/jpeg",))


def test_validate_upload_rejects_disallowed_type(sample_png_bytes):
    with pytest.raises(UnsupportedImageError):
        validate_upload(sample_png_bytes, max_bytes=10_000_000, allowed_mime_types=("image/jpeg",))


def test_preprocess_downscales_large_image(sample_jpeg_bytes):
    result = preprocess_image(sample_jpeg_bytes, long_edge_px=200, thumbnail_px=50)
    assert max(result.width, result.height) <= 200
    assert len(result.thumbnail_bytes) < len(result.jpeg_bytes)


def test_preprocess_converts_rgba_png_to_rgb_jpeg(sample_png_bytes):
    result = preprocess_image(sample_png_bytes, long_edge_px=1280, thumbnail_px=256)
    # Must not raise (RGBA -> JPEG requires an RGB conversion first) and must
    # produce valid, non-empty JPEG output.
    assert len(result.jpeg_bytes) > 0
    assert result.jpeg_bytes[:3] == b"\xff\xd8\xff"
