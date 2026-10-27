import asyncio
import base64
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import browser_snapshot
from app.browser_snapshot import (
    CAPTURE_TIMEOUT_SECONDS,
    MAX_ENCODED_JPEG_BYTES,
    MAX_JPEG_BYTES,
    capture_jpeg,
)


def snapshot(data=b"\xff\xd8test\xff\xd9"):
    return {"data": base64.b64encode(data).decode("ascii")}


def capture(response):
    session = SimpleNamespace(send=AsyncMock(return_value=response))
    return asyncio.run(capture_jpeg(session)), session


def test_capture_only_requests_the_existing_viewport_with_fast_jpeg_encoding():
    expected = b"\xff\xd8test\xff\xd9"
    image, session = capture(snapshot(expected))
    assert image == expected
    session.send.assert_awaited_once_with("Page.captureScreenshot", {
        "format": "jpeg",
        "quality": 75,
        "fromSurface": True,
        "captureBeyondViewport": False,
        "optimizeForSpeed": True,
    })


def test_capture_uses_a_hard_bounded_deadline(monkeypatch):
    original_wait_for = asyncio.wait_for
    deadlines = []

    async def bounded_wait_for(awaitable, *, timeout):
        deadlines.append(timeout)
        return await original_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(browser_snapshot.asyncio, "wait_for", bounded_wait_for)
    capture(snapshot())
    assert deadlines == [2.5]
    assert CAPTURE_TIMEOUT_SECONDS == 2.5


def test_timeout_cancels_the_pending_capture(monkeypatch):
    pending_cancelled = []

    async def slow_send(*_args):
        try:
            await asyncio.sleep(60)
        finally:
            pending_cancelled.append(True)

    monkeypatch.setattr(browser_snapshot, "CAPTURE_TIMEOUT_SECONDS", 0.01)
    session = SimpleNamespace(send=AsyncMock(side_effect=slow_send))
    with pytest.raises(TimeoutError):
        asyncio.run(capture_jpeg(session))
    assert pending_cancelled == [True]


@pytest.mark.parametrize("response", [None, [], "SECRET", {}, {"data": None}, {"data": 1}, {"data": b"AAAA"}])
def test_response_and_data_types_are_checked_without_echoing_private_data(response):
    with pytest.raises(ValueError, match="no encoded image") as error:
        capture(response)
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("data", ["not base64! SECRET https://private.invalid", "\u2603", "/9j/2Q==\n", "AA=!"])
def test_invalid_base64_is_rejected_without_echoing_the_payload(data):
    with pytest.raises(ValueError, match="invalid base64") as error:
        capture({"data": data})
    assert "SECRET" not in str(error.value)
    assert "private.invalid" not in str(error.value)


def test_encoded_limit_is_checked_before_base64_decode(monkeypatch):
    def unexpected_decode(*_args, **_kwargs):
        raise AssertionError("Oversized encoded payload must not be decoded")

    monkeypatch.setattr(browser_snapshot.base64, "b64decode", unexpected_decode)
    with pytest.raises(ValueError, match="encoded size limit"):
        capture({"data": "A" * (MAX_ENCODED_JPEG_BYTES + 1)})


def test_decoded_limit_is_enforced_after_valid_base64():
    oversized = b"\xff\xd8" + b"x" * (MAX_JPEG_BYTES - 3) + b"\xff\xd9"
    encoded = snapshot(oversized)
    assert len(oversized) == MAX_JPEG_BYTES + 1
    assert len(encoded["data"]) == MAX_ENCODED_JPEG_BYTES
    with pytest.raises(ValueError, match="bounded JPEG"):
        capture(encoded)


def test_exact_decoded_limit_is_accepted():
    expected = b"\xff\xd8" + b"x" * (MAX_JPEG_BYTES - 4) + b"\xff\xd9"
    image, _session = capture(snapshot(expected))
    assert image == expected


@pytest.mark.parametrize("data", [b"", b"\xff", b"\xff\xd8\xd9", b"not a JPEG", b"\xff\xd8no end", b"no start\xff\xd9"])
def test_both_jpeg_markers_and_minimum_length_are_required(data):
    with pytest.raises(ValueError, match="bounded JPEG"):
        capture(snapshot(data))


def test_minimum_jpeg_marker_pair_is_accepted():
    image, _session = capture(snapshot(b"\xff\xd8\xff\xd9"))
    assert image == b"\xff\xd8\xff\xd9"


def test_helper_never_opens_a_page_profile_credentials_or_files():
    source = inspect.getsource(browser_snapshot)
    for forbidden in ("http://", "https://", ".goto(", ".launch(", ".new_context(",
                      "persistent_context", "storage_state", "os.environ", "open(", "print("):
        assert forbidden not in source
