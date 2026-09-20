"""Origin checks, security headers, and the session-token dependency."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from pgproof.local_api.security import (
    SECURITY_HEADERS,
    OriginCheckMiddleware,
    SecurityHeadersMiddleware,
    require_session_token,
)

_ORIGIN = "http://127.0.0.1:54321"


def _app() -> FastAPI:
    app = FastAPI()
    app.state.session_token = "the-real-token"
    app.add_middleware(OriginCheckMiddleware, allowed_origin=_ORIGIN)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/open")
    def open_route() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/protected", dependencies=[Depends(require_session_token)])
    def protected_route() -> dict[str, bool]:
        return {"ok": True}

    return app


# --------------------------------------------------------------------------- #
# Security headers
# --------------------------------------------------------------------------- #
def test_every_response_carries_the_security_headers() -> None:
    client = TestClient(_app())
    response = client.get("/open")
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_a_rejected_response_still_carries_the_security_headers() -> None:
    client = TestClient(_app())
    response = client.get("/open", headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.headers["X-Frame-Options"] == "DENY"


# --------------------------------------------------------------------------- #
# Origin check
# --------------------------------------------------------------------------- #
def test_a_request_with_no_origin_header_is_allowed() -> None:
    client = TestClient(_app())
    assert client.get("/open").status_code == 200


def test_a_request_from_the_allowed_origin_is_allowed() -> None:
    client = TestClient(_app())
    response = client.get("/open", headers={"origin": _ORIGIN})
    assert response.status_code == 200


def test_a_request_from_a_different_origin_is_rejected() -> None:
    client = TestClient(_app())
    response = client.get("/open", headers={"origin": "https://evil.example"})
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Session token
# --------------------------------------------------------------------------- #
def test_the_correct_token_as_a_header_is_accepted() -> None:
    client = TestClient(_app())
    response = client.get("/protected", headers={"x-pgproof-session-token": "the-real-token"})
    assert response.status_code == 200


def test_the_correct_token_as_a_query_parameter_is_accepted() -> None:
    client = TestClient(_app())
    response = client.get("/protected", params={"token": "the-real-token"})
    assert response.status_code == 200


def test_a_missing_token_is_rejected() -> None:
    client = TestClient(_app())
    assert client.get("/protected").status_code == 401


def test_a_wrong_token_is_rejected() -> None:
    client = TestClient(_app())
    response = client.get("/protected", params={"token": "guess"})
    assert response.status_code == 401
