from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from .config import Settings
from .schemas import CapturedSource

MAX_DOWNLOAD_BYTES = 2_000_000
MAX_REDIRECTS = 4
USER_AGENT = "AstroLearnerFactory/0.1 (+local research assistant)"
REDIRECT_CODES = {301, 302, 303, 307, 308}


def _host_is_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    normalized = host.lower().rstrip(".")
    return any(
        normalized == allowed or normalized.endswith(f".{allowed}")
        for allowed in allowed_hosts
    )


def validate_source_url(url: str, settings: Settings) -> None:
    if len(url) > 2048:
        raise ValueError("La URL de la fuente es demasiado larga")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Las fuentes deben usar HTTPS")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("El puerto de la fuente no es válido") from exc
    if port not in (None, 443):
        raise ValueError("Las fuentes HTTPS solo pueden usar el puerto 443")
    if parsed.username or parsed.password:
        raise ValueError("No se permiten credenciales dentro de una URL")
    if not _host_is_allowed(parsed.hostname, settings.allowed_source_hosts):
        raise ValueError(f"Dominio de fuente no permitido: {parsed.hostname}")

    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"No se pudo resolver {parsed.hostname}") from exc

    for address in addresses:
        candidate = ipaddress.ip_address(address[4][0])
        if not candidate.is_global:
            raise ValueError("La fuente resuelve a una dirección no pública")


def _download_html(url: str, settings: Settings) -> tuple[str, str]:
    current_url = url
    timeout = httpx.Timeout(30.0, connect=10.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"}

    with httpx.Client(
        timeout=timeout, headers=headers, follow_redirects=False
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            validate_source_url(current_url, settings)
            with client.stream("GET", current_url) as response:
                if response.status_code in REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirección sin destino")
                    current_url = urljoin(current_url, location)
                    continue

                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not any(
                    allowed in content_type
                    for allowed in ("text/html", "text/plain", "application/xhtml+xml")
                ):
                    raise ValueError(f"Tipo de fuente no admitido: {content_type}")

                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ValueError("La página supera el límite de 2 MB")
                    chunks.append(chunk)

                encoding = response.encoding or "utf-8"
                return b"".join(chunks).decode(encoding, errors="replace"), current_url

    raise ValueError("Demasiadas redirecciones")


def _extract_title(document: str, fallback: str) -> str:
    match = re.search(
        r"<title[^>]*>(.*?)</title>", document, flags=re.IGNORECASE | re.DOTALL
    )
    if not match:
        return fallback
    title = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return title[:240] or fallback


def capture_sources(urls: list[str], settings: Settings) -> list[CapturedSource]:
    if not 1 <= len(urls) <= 5:
        raise ValueError("Cada trabajo debe tener entre 1 y 5 fuentes")

    captured: list[CapturedSource] = []
    per_source_limit = max(1500, settings.max_source_chars // len(urls))

    for index, url in enumerate(urls, start=1):
        document, final_url = _download_html(url, settings)
        extracted = trafilatura.extract(
            document,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if not extracted or len(extracted.strip()) < 100:
            raise ValueError(f"No se pudo extraer texto suficiente de {final_url}")
        normalized = re.sub(r"\n{3,}", "\n\n", extracted).strip()
        excerpt = normalized[:per_source_limit]
        digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        host = urlparse(final_url).hostname or "Fuente"
        captured.append(
            CapturedSource(
                id=f"S{index}",
                url=final_url,
                title=_extract_title(document, host),
                excerpt=excerpt,
                retrieved_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
                sha256=digest,
            )
        )

    return captured
