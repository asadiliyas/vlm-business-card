"""
Image validation and preprocessing. Runs before every file reaches the VLM:
validate by magic bytes (never trust a client-supplied extension or
Content-Type), auto-orient from EXIF, downscale, re-encode, strip metadata,
and produce a small thumbnail for the results table.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

# Magic-byte signatures for the formats we accept — checked against the
# actual bytes, not the filename or the browser-supplied Content-Type.
_SIGNATURES: dict[str, bytes] = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}
_WEBP_RIFF = b"RIFF"
_WEBP_TAG = b"WEBP"


class UnsupportedImageError(Exception):
    pass


class ImageTooLargeError(Exception):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    jpeg_bytes: bytes       # downscaled, EXIF-corrected, ready for the VLM
    thumbnail_bytes: bytes  # small JPEG for the UI
    width: int
    height: int


def sniff_mime_type(data: bytes) -> str | None:
    for mime, sig in _SIGNATURES.items():
        if data.startswith(sig):
            return mime
    if len(data) >= 12 and data[0:4] == _WEBP_RIFF and data[8:12] == _WEBP_TAG:
        return "image/webp"
    return None


def validate_upload(data: bytes, *, max_bytes: int, allowed_mime_types: tuple[str, ...]) -> str:
    """Returns the sniffed mime type, or raises UnsupportedImageError / ImageTooLargeError."""
    if len(data) > max_bytes:
        raise ImageTooLargeError(f"File is {len(data) / 1e6:.1f} MB, limit is {max_bytes / 1e6:.1f} MB")
    if len(data) == 0:
        raise UnsupportedImageError("Empty file")

    mime = sniff_mime_type(data)
    if mime is None or mime not in allowed_mime_types:
        raise UnsupportedImageError(
            f"Unrecognized or disallowed image type (detected: {mime or 'unknown'})"
        )

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception as exc:
        raise UnsupportedImageError(f"File is not a valid image: {exc}") from exc

    return mime


def preprocess_image(data: bytes, *, long_edge_px: int, thumbnail_px: int) -> ProcessedImage:
    """
    Normalize an uploaded image for VLM consumption:
    - apply EXIF orientation, then strip EXIF (avoids double-rotation downstream
      and drops any embedded location/device metadata from the source photo)
    - downscale so the long edge is at most `long_edge_px` (keeps latency and
      payload size bounded without losing legibility of card text)
    - re-encode as JPEG q85 in RGB (VLM endpoints expect JPEG/PNG; RGBA/CMYK/
      palette inputs are normalized away here)
    - also produce a small thumbnail for the UI
    """
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")

        img.thumbnail((long_edge_px, long_edge_px), Image.LANCZOS)
        width, height = img.size

        main_buf = io.BytesIO()
        img.save(main_buf, format="JPEG", quality=85, optimize=True)

        thumb = img.copy()
        thumb.thumbnail((thumbnail_px, thumbnail_px), Image.LANCZOS)
        thumb_buf = io.BytesIO()
        thumb.save(thumb_buf, format="JPEG", quality=80, optimize=True)

        return ProcessedImage(
            jpeg_bytes=main_buf.getvalue(),
            thumbnail_bytes=thumb_buf.getvalue(),
            width=width,
            height=height,
        )
