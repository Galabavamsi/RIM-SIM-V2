"""ZeroMQ transport layer for the RIS emulator IPC.

Provides a clean request/response abstraction over ZeroMQ REQ/REP sockets.
All messages are JSON-serialized for readability; IQ arrays are embedded
as lists of [I, Q] pairs. For high-throughput use, a binary framing layer
(msgpack or protobuf) can replace JSON in the future.

Server side — :class:`SimulationServer`:
    Binds a REP socket and processes incoming TX/RX requests between
    simulation ticks via non-blocking poll.

Client side — :func:`send_request`:
    Connects to the server, sends a JSON command, waits for a JSON response.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import zmq

DEFAULT_SERVER_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5556"
REQUEST_TIMEOUT_MS = 30_000  # 30 seconds


class TransportError(Exception):
    """Communication error between client and emulation server."""


def pack_message(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, default=str).encode("utf-8")


def unpack_message(data: bytes) -> dict[str, Any]:
    return json.loads(data.decode("utf-8"))


class ServerTransport:
    """ZeroMQ REP socket wrapper used by :class:`SimulationServer`."""

    def __init__(self, bind_addr: str = DEFAULT_SERVER_ADDR, *, context: zmq.Context | None = None):
        self.ctx = context or zmq.Context.instance()
        self.socket: zmq.Socket = self.ctx.socket(zmq.REP)
        self.socket.bind(bind_addr)
        self.bind_addr = bind_addr

    def poll(self, timeout_ms: int = 0) -> dict[str, Any] | None:
        """Non-blocking check for an incoming request. Returns parsed dict or None."""
        try:
            if self.socket.poll(timeout_ms, zmq.POLLIN):
                raw = self.socket.recv(zmq.NOBLOCK)
                return unpack_message(raw)
        except zmq.ZMQError:
            pass
        return None

    def send_response(self, payload: dict[str, Any]) -> None:
        self.socket.send(pack_message(payload))

    def close(self) -> None:
        self.socket.close(linger=0)


class ClientTransport:
    """ZeroMQ REQ socket wrapper for client-side API calls."""

    def __init__(self, server_addr: str = DEFAULT_SERVER_ADDR, *, context: zmq.Context | None = None):
        self.ctx = context or zmq.Context.instance()
        self.server_addr = server_addr
        self._socket: zmq.Socket | None = None
        self._lock = threading.Lock()

    def _ensure_connected(self) -> zmq.Socket:
        if self._socket is None:
            self._socket = self.ctx.socket(zmq.REQ)
            self._socket.connect(self.server_addr)
        return self._socket

    def request(self, payload: dict[str, Any], timeout_ms: int = REQUEST_TIMEOUT_MS) -> dict[str, Any]:
        """Send a request and block until a response arrives."""
        with self._lock:
            sock = self._ensure_connected()
            sock.send(pack_message(payload))
            if sock.poll(timeout_ms, zmq.POLLIN):
                return unpack_message(sock.recv())
            raise TransportError(
                f"No response from server within {timeout_ms / 1000:.0f}s"
            )

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                self._socket.close(linger=0)
                self._socket = None
