from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .broadcast_metadata import default_metadata, validate_metadata

SCOPES = ["https://www.googleapis.com/auth/youtube"]
API_TIMEOUT_SECONDS = 15
STREAM_STATUSES = {"active", "created", "error", "inactive", "ready"}
STREAM_HEALTH_STATUSES = {"good", "ok", "bad", "noData"}
STREAM_ISSUE_SEVERITIES = {"info", "warning", "error"}
# Only documented diagnostic codes may be copied into public portal status.
# The free-form reason/description and all ingestion credentials stay private.
STREAM_ISSUE_TYPES = {
    "audioBitrateHigh", "audioBitrateLow", "audioBitrateMismatch", "audioCodec",
    "audioCodecMismatch", "audioSampleRate", "audioSampleRateMismatch",
    "audioStereoMismatch", "audioTooManyChannels", "badContainer", "bitrateHigh",
    "bitrateLow", "framerateMismatch", "frameRateHigh", "gopMismatch",
    "gopSizeLong", "gopSizeOver", "gopSizeShort", "multipleAudioStreams",
    "multipleVideoStreams", "noAudioStream", "noVideoStream", "openGop",
    "resolutionMismatch", "videoBitrateMismatch", "videoCodec",
    "videoCodecMismatch", "videoIngestionStarved", "videoInterlaceMismatch",
    "videoProfileMismatch", "videoResolutionSuboptimal", "videoResolutionUnsupported",
}


def _known_code(value: object, allowed: set[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def _health_updated_at(value: object) -> str | None:
    """Convert YouTube's unsigned Unix seconds without trusting malformed data."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and (not value.isascii() or not value.isdecimal()):
        return None
    try:
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0 or not seconds.is_integer():
            return None
        return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


class _TimedRequest(Request):
    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = API_TIMEOUT_SECONDS
        return super().__call__(*args, **kwargs)


def _write_private(path: Path, content: str) -> None:
    """Write an OAuth token with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as token_file:
        token_file.write(content)
    os.chmod(path, 0o600)


@dataclass(frozen=True)
class Broadcast:
    broadcast_id: str
    stream_id: str
    rtmp_url: str
    watch_url: str


class BroadcastUnavailableError(RuntimeError):
    """YouTube no longer exposes the broadcast created by this controller."""


class YouTubeLive:
    def __init__(
        self, token_path: Path, privacy: str, source_label: str = ""
    ) -> None:
        if not token_path.exists():
            raise RuntimeError("Falta la autorización OAuth de YouTube")
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(_TimedRequest())
            _write_private(token_path, credentials.to_json())
        if not credentials.valid:
            raise RuntimeError("La autorización OAuth de YouTube no es válida")
        transport = AuthorizedHttp(credentials, http=httplib2.Http(timeout=API_TIMEOUT_SECONDS))
        self.api = build("youtube", "v3", http=transport, cache_discovery=False)
        self.privacy = privacy
        self.source_label = source_label.strip()

    def create(
        self, block_seconds: int, *, title: str | None = None,
        description: str | None = None,
    ) -> Broadcast:
        now = datetime.now(UTC)
        stamp = now.astimezone().strftime("%d/%m/%Y %H:%M")
        defaults = default_metadata(self.source_label)
        metadata = validate_metadata(
            title if title is not None else f"{defaults['title']} | {stamp}",
            description if description is not None else defaults["description"],
        )
        broadcast = (
            self.api.liveBroadcasts()
            .insert(
                part="snippet,status,contentDetails",
                body={
                    "snippet": {
                        **metadata,
                        "scheduledStartTime": (now + timedelta(seconds=45)).isoformat(),
                        "scheduledEndTime": (
                            now + timedelta(seconds=block_seconds + 180)
                        ).isoformat(),
                    },
                    "status": {
                        "privacyStatus": self.privacy,
                        "selfDeclaredMadeForKids": False,
                    },
                    "contentDetails": {
                        "enableAutoStart": True,
                        # A brief RTMP outage must not finalize the video while
                        # the controller reconnects to its original stream.
                        "enableAutoStop": False,
                        "enableDvr": True,
                        "recordFromStart": True,
                        "monitorStream": {"enableMonitorStream": False},
                    },
                },
            )
            .execute()
        )
        stream = (
            self.api.liveStreams()
            .insert(
                part="snippet,cdn,status",
                body={
                    "snippet": {"title": f"AstroLearner ISS {stamp}"},
                    "cdn": {
                        # The server's low-load profile currently emits 12 fps.
                        # Let YouTube detect the actual stream parameters rather
                        # than declaring a fixed frame rate that does not match.
                        "frameRate": "variable",
                        "ingestionType": "rtmp",
                        "resolution": "variable",
                    },
                },
            )
            .execute()
        )
        self.api.liveBroadcasts().bind(
            part="id,contentDetails", id=broadcast["id"], streamId=stream["id"]
        ).execute()
        ingestion = stream["cdn"]["ingestionInfo"]
        return Broadcast(
            broadcast_id=broadcast["id"],
            stream_id=stream["id"],
            rtmp_url=f"{ingestion['ingestionAddress']}/{ingestion['streamName']}",
            watch_url=f"https://www.youtube.com/watch?v={broadcast['id']}",
        )

    def update_metadata(self, broadcast_id: str, title: str, description: str) -> bool:
        """Edit only the matching video's snippet, never stream/privacy controls."""
        metadata = validate_metadata(title, description)
        result = self.api.videos().list(part="snippet", id=broadcast_id).execute()
        items = result.get("items", [])
        if not items:
            raise BroadcastUnavailableError("YouTube ya no encuentra el directo actual")
        snippet = items[0].get("snippet", {})
        if not snippet.get("categoryId"):
            raise RuntimeError("YouTube no devolvió la categoría del directo")
        if all(snippet.get(key, "") == value for key, value in metadata.items()):
            return False
        # Updating a part replaces its writable fields. Preserve existing values
        # and omit read-only snippet fields such as thumbnails/channel/publishedAt.
        writable = {
            key: snippet[key]
            for key in ("categoryId", "tags", "defaultLanguage", "defaultAudioLanguage")
            if key in snippet
        }
        self.api.videos().update(
            part="snippet", body={"id": broadcast_id, "snippet": {**writable, **metadata}}
        ).execute()
        return True

    def complete(self, broadcast_id: str) -> None:
        item = self.api.liveBroadcasts().list(part="status", id=broadcast_id).execute()
        if item.get("items") and item["items"][0]["status"]["lifeCycleStatus"] in {
            "live",
            "testing",
        }:
            self.api.liveBroadcasts().transition(
                part="status", id=broadcast_id, broadcastStatus="complete"
            ).execute()

    def broadcast_status(self, broadcast_id: str) -> dict[str, str] | None:
        """Return YouTube's lifecycle and privacy for a broadcast, if it exists."""
        result = (
            self.api.liveBroadcasts()
            .list(part="id,status", id=broadcast_id)
            .execute()
        )
        items = result.get("items", [])
        if not items:
            return None
        status = items[0].get("status", {})
        return {
            "life_cycle_status": status.get("lifeCycleStatus", "unknown"),
            "privacy_status": status.get("privacyStatus", "unknown"),
        }

    def stream_health(self, stream_id: str) -> dict[str, object] | None:
        """Read ingest health, exporting only safe diagnostic enums to the portal."""
        result = self.api.liveStreams().list(part="status", id=stream_id).execute()
        items = result.get("items", []) if isinstance(result, dict) else []
        if not isinstance(items, list) or not items:
            return None
        item = items[0] if isinstance(items[0], dict) else {}
        status = item.get("status", {})
        status = status if isinstance(status, dict) else {}
        health = status.get("healthStatus", {})
        health = health if isinstance(health, dict) else {}
        raw_issues = health.get("configurationIssues", [])
        issues = []
        if isinstance(raw_issues, list):
            for issue in raw_issues:
                if not isinstance(issue, dict):
                    continue
                issues.append({
                    "type": _known_code(issue.get("type"), STREAM_ISSUE_TYPES),
                    "severity": _known_code(issue.get("severity"), STREAM_ISSUE_SEVERITIES),
                })
                if len(issues) >= 8:
                    break
        return {
            "stream_status": _known_code(status.get("streamStatus"), STREAM_STATUSES),
            "health_status": _known_code(health.get("status"), STREAM_HEALTH_STATUSES),
            "health_updated_at": _health_updated_at(health.get("lastUpdateTimeSeconds")),
            "issues": issues,
        }


def create_authorization(client_secret: Path, token_path: Path) -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not client_secret.exists():
        raise FileNotFoundError(client_secret)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    credentials = flow.run_local_server(
        host="localhost",
        bind_addr="0.0.0.0",
        port=8093,
        open_browser=False,
        access_type="offline",
        prompt="consent",
    )
    _write_private(token_path, credentials.to_json())
    return json.dumps({"authorized": True})
