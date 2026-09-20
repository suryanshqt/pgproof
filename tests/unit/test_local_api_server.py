"""Loopback socket binding: always `127.0.0.1`, never a configurable host."""

import socket

import pytest

from pgproof.local_api.server import LOOPBACK_HOST, bind_loopback_socket, bound_port, serve


def test_the_bound_socket_is_loopback_only() -> None:
    sock = bind_loopback_socket()
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
        assert LOOPBACK_HOST == "127.0.0.1"
    finally:
        sock.close()


def test_the_os_assigns_a_nonzero_port() -> None:
    sock = bind_loopback_socket()
    try:
        assert bound_port(sock) > 0
    finally:
        sock.close()


def test_two_concurrent_sockets_get_different_ports() -> None:
    first = bind_loopback_socket()
    second = bind_loopback_socket()
    try:
        assert bound_port(first) != bound_port(second)
    finally:
        first.close()
        second.close()


def test_serve_runs_uvicorn_against_the_given_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, list[socket.socket]]] = []

    class _FakeServer:
        def __init__(self, config: object) -> None:
            self._config = config

        def run(self, sockets: list[socket.socket]) -> None:
            calls.append((self._config, sockets))

    monkeypatch.setattr("pgproof.local_api.server.uvicorn.Server", _FakeServer)
    sock = bind_loopback_socket()
    try:
        serve(app=object(), sock=sock)  # type: ignore[arg-type]
    finally:
        sock.close()
    assert calls == [(calls[0][0], [sock])]
