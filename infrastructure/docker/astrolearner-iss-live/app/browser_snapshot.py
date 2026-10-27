"""Bounded JPEG capture from an already isolated browser context.

This helper only uses the supplied CDP session. It does not launch a browser,
load a URL, inspect credentials, write files or log browser responses.
"""
from __future__ import annotations

import asyncio
import base64
import binascii

MAX_JPEG_BYTES = 2 * 1024 * 1024
MAX_ENCODED_JPEG_BYTES = 4 * ((MAX_JPEG_BYTES + 2) // 3)
CAPTURE_TIMEOUT_SECONDS = 2.5


async def capture_jpeg(session) -> bytes:
    """Capture the current viewport without per-frame screenshot preparation."""
    response = await asyncio.wait_for(
        session.send("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": 75,
            "fromSurface": True,
            "captureBeyondViewport": False,
            "optimizeForSpeed": True,
        }),
        timeout=CAPTURE_TIMEOUT_SECONDS,
    )
    if not isinstance(response, dict) or not isinstance(response.get("data"), str):
        raise ValueError("Browser snapshot has no encoded image")
    encoded = response["data"]
    if len(encoded) > MAX_ENCODED_JPEG_BYTES:
        raise ValueError("Browser snapshot exceeds the encoded size limit")
    try:
        jpeg = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Browser snapshot has invalid base64 data") from None
    if not (4 <= len(jpeg) <= MAX_JPEG_BYTES
            and jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")):
        raise ValueError("Browser snapshot is not a bounded JPEG image")
    return jpeg
