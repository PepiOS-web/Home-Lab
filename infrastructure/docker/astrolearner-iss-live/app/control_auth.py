from __future__ import annotations

import secrets


class ControlAuthError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def authorize_control(origin: str | None, authorization: str, expected: str) -> None:
    if not expected:
        raise ControlAuthError(503, "Controles no configurados")
    if origin != "https://portal.home.arpa":
        raise ControlAuthError(403, "Origen no permitido")
    prefix = "Bearer "
    provided = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
    if not secrets.compare_digest(provided, expected):
        raise ControlAuthError(401, "Token de control incorrecto")
