"""Local control socket, so keyboard shortcuts can drive the running daemon.

Protocol: one line per request ("up", "down", "play", "pause", "toggle",
"stop", "next", "previous", "status", "connect"), one JSON line back.
The socket lives in $XDG_RUNTIME_DIR (private to the user, mode 0700).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import threading
from pathlib import Path

from .config import runtime_socket_path
from .controller import Controller

LOGGER = logging.getLogger(__name__)

ALIASES = {
    "vol+": "up", "volup": "up", "volume_up": "up", "+": "up",
    "vol-": "down", "voldown": "down", "volume_down": "down", "-": "down",
    "play_pause": "toggle", "playpause": "toggle",
    "prev": "previous",
}
VALID = {"up", "down", "play", "pause", "toggle", "stop", "next", "previous", "status", "connect"}

# Exit codes for the CLI
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_OFFLINE = 2        # daemon running, but offline (server not reachable)
EXIT_NO_DAEMON = 3


def normalize(action: str) -> str:
    action = action.strip().lower()
    return ALIASES.get(action, action)


class _Handler(socketserver.StreamRequestHandler):
    controller: Controller

    def handle(self) -> None:
        line = self.rfile.readline(256).decode("utf-8", "replace")
        action = normalize(line)
        if action not in VALID:
            reply = {"ok": False, "detail": f"unknown action '{action}'"}
        elif action == "status":
            reply = {"ok": True, **self.controller.status()}
        else:
            res = self.controller.connect() if action == "connect" else self.controller.act(action)
            reply = {"ok": res.ok, "detail": res.detail, "status": self.controller.client.status.value}
        self.wfile.write((json.dumps(reply) + "\n").encode())


class ControlServer:
    def __init__(self, controller: Controller, path: Path | None = None) -> None:
        self.path = path or runtime_socket_path()
        handler = type("Handler", (_Handler,), {"controller": controller})
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.exists():
            if _probe(self.path):
                raise RuntimeError(f"ma-tray is already running ({self.path})")
            self.path.unlink()
        old_umask = os.umask(0o177)
        try:
            self._server = socketserver.ThreadingUnixStreamServer(str(self.path), handler)
        finally:
            os.umask(old_umask)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="ma-control", daemon=True)

    def start(self) -> None:
        self._thread.start()
        LOGGER.info("Control socket at %s", self.path)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        try:
            self.path.unlink()
        except OSError:
            pass


def _probe(path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(str(path))
            return True
    except OSError:
        return False


def send(action: str, path: Path | None = None, timeout: float = 5.0) -> dict | None:
    """Send one request to the daemon. Returns None if the daemon isn't running."""
    path = path or runtime_socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(path))
            sock.sendall((action + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
    except (FileNotFoundError, ConnectionRefusedError):
        return None
    except OSError as err:
        return {"ok": False, "detail": str(err)}
    try:
        return json.loads(data)
    except ValueError:
        return {"ok": False, "detail": "invalid reply from daemon"}
