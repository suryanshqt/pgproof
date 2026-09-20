"""Loopback server lifecycle: socket binding and serving.

`docs/ARCHITECTURE.md` section 9 forbids "binding beyond loopback." That is
structural here, not a runtime check: the bind call names `127.0.0.1`
directly, with no host parameter for a caller to override. The OS chooses a
free ephemeral port, so two concurrent `pgproof ui` invocations cannot
collide.

Shutdown follows `docs/ARCHITECTURE.md` section 31 for free: uvicorn's
default signal handling treats the first `SIGINT`/`SIGTERM` as a graceful
stop (finish in-flight requests, then exit) and a second as an immediate one.
"""

from __future__ import annotations

import socket
from typing import Final

import uvicorn
from fastapi import FastAPI

LOOPBACK_HOST: Final = "127.0.0.1"


def bind_loopback_socket() -> socket.socket:
    """A listening socket on `127.0.0.1`, port chosen by the OS."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((LOOPBACK_HOST, 0))
    sock.listen()
    return sock


def bound_port(sock: socket.socket) -> int:
    return int(sock.getsockname()[1])


def serve(app: FastAPI, sock: socket.socket) -> None:
    """Blocks until the server stops."""
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    server.run(sockets=[sock])
