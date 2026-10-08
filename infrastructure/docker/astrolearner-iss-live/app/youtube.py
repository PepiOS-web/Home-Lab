from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube"]


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
            credentials.refresh(Request())
            _write_private(token_path, credentials.to_json())
        if not credentials.valid:
            raise RuntimeError("La autorización OAuth de YouTube no es válida")
        self.api = build(
            "youtube", "v3", credentials=credentials, cache_discovery=False
        )
        self.privacy = privacy
        self.source_label = source_label.strip()

    def create(self, block_seconds: int) -> Broadcast:
        now = datetime.now(UTC)
        stamp = now.astimezone().strftime("%d/%m/%Y %H:%M")
        if "NASA IMAGE" in self.source_label.upper():
            visual_description = (
                "Fondo visual: vídeos grabados de NASA Johnson Space Center e "
                "imágenes recientes de NASA EPIC/DSCOVR. No es una cámara en "
                "directo desde la ISS."
            )
        elif "NASA EPIC" in self.source_label.upper():
            visual_description = (
                "Fondo visual: imágenes recientes de NASA EPIC/DSCOVR. "
                "No es una cámara en directo desde la ISS."
            )
        else:
            visual_description = (
                f"Fuente visual autorizada: {self.source_label}."
                if self.source_label
                else "Fuente visual autorizada configurada por AstroLearner."
            )
        broadcast = (
            self.api.liveBroadcasts()
            .insert(
                part="snippet,status,contentDetails",
                body={
                    "snippet": {
                        "title": (
                            "ISS en tiempo real · mapa orbital y Tierra | "
                            f"{stamp}"
                        ),
                        "description": (
                            "Seguimiento automatizado de la posición de la ISS con mapas "
                            "y datos orbitales actualizados en tiempo real. "
                            f"{visual_description} "
                            "Música ambiental procedural creada localmente, sin micrófono. "
                            "AstroLearner es un canal independiente no afiliado a NASA."
                        ),
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
                        "enableAutoStop": True,
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
