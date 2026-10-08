from __future__ import annotations

import logging
import threading
import time

from .config import Settings
from .db import Database
from .pipeline import generate_job, render_job

LOGGER = logging.getLogger(__name__)


class SerialWorker:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="astrolearner-worker",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        LOGGER.info("Worker secuencial iniciado")
        while not self._stop.is_set():
            claimed = self.database.claim_next_job()
            if claimed is None:
                self._stop.wait(2.0)
                continue
            job, action = claimed
            try:
                if action == "generate":
                    generate_job(job, self.database, self.settings)
                elif action == "render":
                    render_job(job, self.database, self.settings)
                else:
                    raise ValueError(f"Acción desconocida: {action}")
            except Exception as exc:
                LOGGER.exception("Falló %s para el trabajo %s", action, job.id)
                self.database.fail_job(job.id, str(exc))
            time.sleep(0.2)
