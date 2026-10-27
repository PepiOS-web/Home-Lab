from __future__ import annotations

import secrets


class ControlAuthError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def authorize_control(
    origin: str | None, authorization: str, expected: str, *,
    allow_missing_origin: bool = False,
    session_authorized: bool = False,
) -> None:
    if not expected:
        raise ControlAuthError(503, "Controles no configurados")
    # Same-origin browser GETs omit Origin. Only authenticated read-only routes
    # may accept its absence; every state-changing route still requires it.
    if origin != "https://portal.home.arpa" and not (allow_missing_origin and origin is None):
        raise ControlAuthError(403, "Origen no permitido")
    if session_authorized and not authorization:
        return
    prefix = "Bearer "
    provided = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
    if not secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise ControlAuthError(401, "Token de control incorrecto")
