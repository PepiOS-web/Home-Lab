from unittest.mock import Mock

import pytest

from app.youtube import BroadcastUnavailableError, YouTubeLive


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeBroadcasts:
    def __init__(self, response):
        self.response = response

    def list(self, **_kwargs):
        return FakeRequest(self.response)


class FakeAPI:
    def __init__(self, response):
        self.response = response

    def liveBroadcasts(self):
        return FakeBroadcasts(self.response)


def test_broadcast_status_returns_youtube_lifecycle_and_privacy():
    youtube = YouTubeLive.__new__(YouTubeLive)
    youtube.api = FakeAPI(
        {
            "items": [
                {
                    "status": {
                        "lifeCycleStatus": "live",
                        "privacyStatus": "public",
                    }
                }
            ]
        }
    )

    assert youtube.broadcast_status("broadcast-id") == {
        "life_cycle_status": "live",
        "privacy_status": "public",
    }


def test_broadcast_status_returns_none_when_youtube_does_not_find_it():
    youtube = YouTubeLive.__new__(YouTubeLive)
    youtube.api = FakeAPI({"items": []})

    assert youtube.broadcast_status("missing-id") is None


def youtube_with_stream_health(response):
    youtube = YouTubeLive.__new__(YouTubeLive)
    youtube.api = Mock()
    youtube.api.liveStreams.return_value.list.return_value.execute.return_value = response
    return youtube


def test_stream_health_reads_only_status_and_exports_safe_diagnostics():
    youtube = youtube_with_stream_health({
        "items": [{
            "id": "private-stream-id",
            "cdn": {"ingestionInfo": {"streamName": "private-stream-key"}},
            "status": {
                "streamStatus": "active",
                "healthStatus": {
                    "status": "ok",
                    "lastUpdateTimeSeconds": "1791806400",
                    "configurationIssues": [{
                        "type": "bitrateLow", "severity": "warning",
                        "reason": "A free-form reason",
                        "description": "Do not expose private-stream-key or arbitrary text",
                    }],
                },
            },
        }],
    })

    assert youtube.stream_health("private-stream-id") == {
        "stream_status": "active",
        "health_status": "ok",
        "health_updated_at": "2026-10-12T12:00:00Z",
        "issues": [{"type": "bitrateLow", "severity": "warning"}],
    }
    youtube.api.liveStreams.return_value.list.assert_called_once_with(
        part="status", id="private-stream-id"
    )
    youtube.api.liveStreams.return_value.list.return_value.execute.assert_called_once_with()
    youtube.api.liveBroadcasts.assert_not_called()


@pytest.mark.parametrize("response", [{}, {"items": []}, {"items": None}, None])
def test_stream_health_returns_none_when_stream_is_missing(response):
    assert youtube_with_stream_health(response).stream_health("missing-id") is None


@pytest.mark.parametrize("item", [None, {}, {"status": []}, {"status": {"healthStatus": "bad"}}])
def test_stream_health_malformed_item_is_unknown_instead_of_healthy(item):
    youtube = youtube_with_stream_health({"items": [item]})
    assert youtube.stream_health("stream-id") == {
        "stream_status": "unknown", "health_status": "unknown",
        "health_updated_at": None, "issues": [],
    }


@pytest.mark.parametrize("stream_status", ["active", "created", "error", "inactive", "ready"])
@pytest.mark.parametrize("health_status", ["good", "ok", "bad", "noData"])
def test_stream_health_preserves_documented_status_codes(stream_status, health_status):
    youtube = youtube_with_stream_health({"items": [{"status": {
        "streamStatus": stream_status, "healthStatus": {"status": health_status},
    }}]})
    result = youtube.stream_health("stream-id")
    assert result["stream_status"] == stream_status
    assert result["health_status"] == health_status


@pytest.mark.parametrize("invalid", [True, [], {}, None, "unknown-status", "<script>" ])
def test_stream_health_never_copies_unknown_status_values(invalid):
    youtube = youtube_with_stream_health({"items": [{"status": {
        "streamStatus": invalid, "healthStatus": {"status": invalid},
    }}]})
    result = youtube.stream_health("stream-id")
    assert result["stream_status"] == "unknown"
    assert result["health_status"] == "unknown"


@pytest.mark.parametrize("timestamp", [
    None, True, False, [], {}, -1, 1.5, float("nan"), float("inf"),
    "NaN", "Infinity", "-1", "1.5", " 1791806400", "١٧٩١٨٠٦٤٠٠", 10 ** 100,
])
def test_stream_health_rejects_invalid_timestamps(timestamp):
    youtube = youtube_with_stream_health({"items": [{"status": {"healthStatus": {
        "lastUpdateTimeSeconds": timestamp,
    }}}]})
    assert youtube.stream_health("stream-id")["health_updated_at"] is None


@pytest.mark.parametrize("timestamp", [1791806400, 1791806400.0, "1791806400"])
def test_stream_health_accepts_integer_unix_seconds(timestamp):
    youtube = youtube_with_stream_health({"items": [{"status": {"healthStatus": {
        "lastUpdateTimeSeconds": timestamp,
    }}}]})
    assert youtube.stream_health("stream-id")["health_updated_at"] == "2026-10-12T12:00:00Z"


def test_stream_health_bounds_issues_and_strips_free_form_values():
    youtube = youtube_with_stream_health({"items": [{"status": {"healthStatus": {
        "configurationIssues": [None, "not-an-object", {
            "type": "https://example.invalid/private-stream-key",
            "severity": {"malformed": True}, "description": "private-stream-key",
        }] + [{"type": "videoIngestionStarved", "severity": "error"}] * 12,
    }}}]})
    issues = youtube.stream_health("stream-id")["issues"]
    assert len(issues) == 8
    assert issues[0] == {"type": "unknown", "severity": "unknown"}
    assert issues[1:] == [{"type": "videoIngestionStarved", "severity": "error"}] * 7


@pytest.mark.parametrize("issues", [None, {}, "noAudioStream"])
def test_stream_health_malformed_issue_list_is_empty(issues):
    youtube = youtube_with_stream_health({"items": [{"status": {"healthStatus": {
        "configurationIssues": issues,
    }}}]})
    assert youtube.stream_health("stream-id")["issues"] == []


def test_stream_health_api_errors_propagate_without_retry_or_mutation():
    youtube = youtube_with_stream_health({})
    youtube.api.liveStreams.return_value.list.return_value.execute.side_effect = RuntimeError(
        "temporarily unavailable"
    )
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        youtube.stream_health("stream-id")
    youtube.api.liveStreams.return_value.list.assert_called_once_with(part="status", id="stream-id")
    youtube.api.liveStreams.return_value.insert.assert_not_called()
    youtube.api.liveStreams.return_value.update.assert_not_called()
    youtube.api.liveStreams.return_value.delete.assert_not_called()


def youtube_with_video_snippet(snippet):
    youtube = YouTubeLive.__new__(YouTubeLive)
    youtube.api = Mock()
    youtube.api.videos.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "broadcast-id", "snippet": snippet}]
    }
    return youtube


def test_update_metadata_changes_only_writable_snippet_and_preserves_existing_fields():
    existing = {
        "title": "Título anterior",
        "description": "Descripción anterior",
        "categoryId": "28",
        "tags": ["ISS", "lofi"],
        "defaultLanguage": "es",
        "defaultAudioLanguage": "es",
        "publishedAt": "2026-10-12T10:00:00Z",
        "channelId": "channel-id",
        "thumbnails": {"default": {"url": "https://example.invalid/thumb.jpg"}},
        "localized": {"title": "Título anterior", "description": "Descripción anterior"},
        "liveBroadcastContent": "live",
    }
    youtube = youtube_with_video_snippet(existing)

    assert youtube.update_metadata("broadcast-id", "Título nuevo", "Descripción nueva") is True

    videos = youtube.api.videos.return_value
    videos.list.assert_called_once_with(part="snippet", id="broadcast-id")
    videos.update.assert_called_once_with(
        part="snippet",
        body={
            "id": "broadcast-id",
            "snippet": {
                "title": "Título nuevo",
                "description": "Descripción nueva",
                "categoryId": "28",
                "tags": ["ISS", "lofi"],
                "defaultLanguage": "es",
                "defaultAudioLanguage": "es",
            },
        },
    )
    videos.update.return_value.execute.assert_called_once_with()
    youtube.api.liveBroadcasts.assert_not_called()
    assert existing["title"] == "Título anterior"


def test_update_metadata_skips_api_write_when_text_is_unchanged():
    youtube = youtube_with_video_snippet(
        {"title": "ISS y música", "description": "Sesión original", "categoryId": "28"}
    )

    assert youtube.update_metadata("broadcast-id", "ISS y música", "Sesión original") is False
    youtube.api.videos.return_value.update.assert_not_called()


def test_update_metadata_can_clear_description_without_dropping_category():
    youtube = youtube_with_video_snippet(
        {"title": "ISS y música", "description": "Descripción anterior", "categoryId": "28"}
    )

    assert youtube.update_metadata("broadcast-id", "ISS y música", "") is True
    youtube.api.videos.return_value.update.assert_called_once_with(
        part="snippet",
        body={
            "id": "broadcast-id",
            "snippet": {"title": "ISS y música", "description": "", "categoryId": "28"},
        },
    )


def test_update_metadata_raises_when_video_is_unavailable():
    youtube = youtube_with_video_snippet({})
    youtube.api.videos.return_value.list.return_value.execute.return_value = {"items": []}

    with pytest.raises(BroadcastUnavailableError):
        youtube.update_metadata("broadcast-id", "Título nuevo", "Descripción nueva")

    youtube.api.videos.return_value.update.assert_not_called()


def test_update_metadata_raises_without_category_instead_of_guessing_one():
    youtube = youtube_with_video_snippet(
        {"title": "Título anterior", "description": "Descripción anterior"}
    )

    with pytest.raises(RuntimeError):
        youtube.update_metadata("broadcast-id", "Título nuevo", "Descripción nueva")

    youtube.api.videos.return_value.update.assert_not_called()


def test_update_metadata_propagates_api_failure_without_retrying():
    youtube = youtube_with_video_snippet(
        {"title": "Título anterior", "description": "Descripción anterior", "categoryId": "28"}
    )
    videos = youtube.api.videos.return_value
    videos.update.return_value.execute.side_effect = RuntimeError("YouTube rate limit")

    with pytest.raises(RuntimeError, match="YouTube rate limit"):
        youtube.update_metadata("broadcast-id", "Título nuevo", "Descripción nueva")

    videos.update.assert_called_once()
    videos.update.return_value.execute.assert_called_once_with()


@pytest.mark.parametrize("description", ["Descripción personalizada", ""])
def test_create_uses_custom_metadata_without_appending_a_timestamp(description):
    youtube = YouTubeLive.__new__(YouTubeLive)
    youtube.api = Mock()
    youtube.privacy = "public"
    youtube.source_label = "NASA Image and Video Library"
    youtube.api.liveBroadcasts.return_value.insert.return_value.execute.return_value = {
        "id": "broadcast-id"
    }
    youtube.api.liveStreams.return_value.insert.return_value.execute.return_value = {
        "id": "stream-id",
        "cdn": {
            "ingestionInfo": {
                "ingestionAddress": "rtmp://example.invalid/live2",
                "streamName": "test-stream-name",
            }
        },
    }

    broadcast = youtube.create(39000, title="Título personalizado", description=description)

    body = youtube.api.liveBroadcasts.return_value.insert.call_args.kwargs["body"]
    assert body["snippet"]["title"] == "Título personalizado"
    assert body["snippet"]["description"] == description
    assert body["status"]["privacyStatus"] == "public"
    assert body["contentDetails"]["enableAutoStop"] is False
    assert body["contentDetails"]["enableAutoStart"] is True
    assert broadcast.broadcast_id == "broadcast-id"
    assert broadcast.watch_url == "https://www.youtube.com/watch?v=broadcast-id"
    youtube.api.liveBroadcasts.return_value.bind.assert_called_once_with(
        part="id,contentDetails", id="broadcast-id", streamId="stream-id"
    )
