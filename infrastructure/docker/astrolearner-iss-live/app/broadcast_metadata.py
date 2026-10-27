from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

LOG = logging.getLogger(__name__)


def default_metadata(source_label: str = "") -> dict[str, str]:
    source_label = source_label.strip()
    if "NASA IMAGE" in source_label.upper():
        visual = (
            "Fondo visual: vídeos grabados de NASA Johnson Space Center e imágenes "
            "recientes de NASA EPIC/DSCOVR. No es una cámara en directo desde la ISS."
        )
    elif "NASA EPIC" in source_label.upper():
        visual = (
            "Fondo visual: imágenes recientes de NASA EPIC/DSCOVR. "
            "No es una cámara en directo desde la ISS."
        )
    else:
        visual = (
            f"Fuente visual autorizada: {source_label}."
            if source_label
            else "Fuente visual autorizada configurada por AstroLearner."
        )
    return {
        "title": "ISS en tiempo real · mapa orbital y Tierra",
        "description": (
            "Seguimiento automatizado de la posición de la ISS con mapas y datos "
            f"orbitales actualizados en tiempo real.\n\n{visual}\n\n"
            "Música Lo-Fi original creada localmente, sin micrófono. "
            "AstroLearner es un canal independiente no afiliado a NASA."
        ),
    }


def validate_metadata(title: str, description: str) -> dict[str, str]:
    if not isinstance(title, str) or not isinstance(description, str):
        raise ValueError("El título y la descripción deben ser texto")
    title = title.strip()
    if not title or len(title) > 100:
        raise ValueError("El título debe tener entre 1 y 100 caracteres")
    try:
        size = len(description.encode("utf-8"))
        title.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("El texto contiene caracteres Unicode no válidos") from exc
    if size > 5000:
        raise ValueError("La descripción no puede superar 5000 bytes UTF-8")
    for text in (title, description):
        if "<" in text or ">" in text:
            raise ValueError("YouTube no permite los caracteres < y > en estos campos")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
            raise ValueError("El texto contiene caracteres de control no válidos")
    if "\n" in title or "\r" in title or "\t" in title:
        raise ValueError("El título debe estar en una sola línea")
    return {"title": title, "description": description}


class BroadcastMetadataStore:
    """Private persistent defaults; separate from publicly served status files."""

    def __init__(self, path: Path, source_label: str = "") -> None:
        self.path = path
        self._lock = threading.Lock()
        self._value = default_metadata(source_label)
        try:
            if path.is_file():
                if path.stat().st_size > 32768:
                    raise ValueError("Archivo demasiado grande")
                value = json.loads(path.read_text(encoding="utf-8"))
                self._value = validate_metadata(value["title"], value["description"])
        except (OSError, ValueError, KeyError, TypeError):
            # Never log the file contents; fall back without blocking the stream.
            LOG.warning("No se pudieron cargar los textos del directo; se usan los predeterminados")

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._value)

    def save(self, title: str, description: str) -> dict[str, str]:
        value = validate_metadata(title, description)
        with self._lock:
            if value == self._value and self.path.is_file():
                return dict(value)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".live-metadata-", suffix=".tmp", dir=self.path.parent
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    json.dump(value, output, ensure_ascii=False)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self._value = value
            return dict(value)
