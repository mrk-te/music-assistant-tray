"""Music Assistant WebSocket client.

Deliberately simple model:
- connect() is called at start-up and when the user clicks "Connect".
  If it fails, the client is OFFLINE and stays offline: no automatic retries.
- Before every command, check() sends a WebSocket ping and waits for the pong
  (`timeout` seconds). No pong → OFFLINE, command not sent.
- While online, a background reader keeps the player state live (events) and
  pings every 30 s, so a dead link also turns the app OFFLINE when idle.
- The server_id is pinned at the first successful connection: if another
  machine answers at that address later, the token is not sent.
"""

from __future__ import annotations

import enum
import json
import logging
import select
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import websocket  # Ubuntu package python3-websocket (websocket-client)

from .config import Config
from .i18n import _

LOGGER = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 30.0
IDLE_DEADLINE = 45.0

ACTIONS = {
    "play": "players/cmd/play",
    "pause": "players/cmd/pause",
    "toggle": "players/cmd/play_pause",
    "stop": "players/cmd/stop",
    "next": "players/cmd/next",
    "previous": "players/cmd/previous",
    "up": "players/cmd/volume_up",
    "down": "players/cmd/volume_down",
}
GROUP_VOLUME = {"up": "players/cmd/group_volume_up", "down": "players/cmd/group_volume_down"}
USER_PLAYER_TYPES = {"player", "stereo_pair", "group"}


class Status(enum.Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"


class ConnectError(Exception):
    """Handshake failed; the message is user-facing."""


@dataclass
class Result:
    ok: bool
    detail: str = ""
    value: Any = None


def ws_url(http_url: str) -> str:
    url = http_url.rstrip("/")
    url = "ws" + url[4:] if url.startswith("http") else url
    return url if url.endswith("/ws") else url + "/ws"


def _call_sync(ws: websocket.WebSocket, command: str, **args: Any) -> Any:
    """Command/response on a connection that has no reader thread yet."""
    msg_id = uuid.uuid4().hex
    ws.send(json.dumps({"message_id": msg_id, "command": command, "args": args}))
    partial: list | None = None
    while True:
        msg = json.loads(ws.recv())
        if msg.get("message_id") != msg_id:
            continue  # events arriving during the handshake
        if "error_code" in msg:
            raise ConnectError(msg.get("details") or f"error {msg['error_code']}")
        if msg.get("partial"):
            partial = (partial or []) + list(msg.get("result") or [])
            continue
        if partial is not None:
            return partial + list(msg.get("result") or [])
        return msg.get("result")


def handshake(config: Config) -> tuple[websocket.WebSocket, dict, list[dict]]:
    """Open, authenticate and fetch players. Raises ConnectError with a readable message."""
    if not config.complete:
        raise ConnectError(_("URL and token are required"))
    try:
        ws = websocket.create_connection(
            ws_url(config.url), timeout=config.timeout, enable_multithread=True
        )
    except (OSError, websocket.WebSocketException) as err:
        LOGGER.info("Connect failed: %s", err)
        raise ConnectError(_("Server unreachable")) from err
    try:
        info = json.loads(ws.recv())
        if config.server_id and info.get("server_id") != config.server_id:
            raise ConnectError(_("Different server at this address: token not sent"))
        if int(info.get("schema_version", 0)) >= 28:
            try:
                ok = _call_sync(ws, "auth", token=config.token)
            except ConnectError as err:
                LOGGER.info("Auth rejected: %s", err)
                raise ConnectError(_("Invalid token")) from err
            if not ok:
                raise ConnectError(_("Invalid token"))
        players = _call_sync(ws, "players/all") or []
        return ws, info, players
    except ConnectError:
        ws.close()
        raise
    except (OSError, ValueError, websocket.WebSocketException) as err:
        ws.close()
        LOGGER.info("Handshake failed: %s", err)
        raise ConnectError(_("Server not answering")) from err


class _Pending:
    __slots__ = ("event", "value", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: Any = None
        self.error: str | None = None


class _Session:
    """One live connection. A new connect() creates a new session, so a stale
    reader thread can never take down a newer connection."""

    def __init__(self, ws: websocket.WebSocket) -> None:
        self.ws = ws
        self.closed = threading.Event()
        self.pong = threading.Event()
        self.send_lock = threading.Lock()
        self.check_lock = threading.Lock()


class MAClient:
    def __init__(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change
        self._lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._session: _Session | None = None
        self._pending: dict[str, _Pending] = {}
        self._players: dict[str, dict] = {}
        self.status = Status.OFFLINE
        self.error = ""
        self.server_info: dict = {}

    # ---------------------------------------------------------------- state

    @property
    def online(self) -> bool:
        return self.status is Status.ONLINE

    def players(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._players)

    def _set_status(self, status: Status, error: str = "") -> None:
        self.status, self.error = status, error
        LOGGER.info("Status: %s%s", status.value, f" ({error})" if error else "")
        self._on_change()

    # ------------------------------------------------------------ lifecycle

    def connect(self, config: Config) -> Result:
        """Blocking: run it off the UI thread."""
        with self._connect_lock:
            self.disconnect()
            self._set_status(Status.CONNECTING)
            try:
                ws, info, players = handshake(config)
            except ConnectError as err:
                self._set_status(Status.OFFLINE, str(err))
                return Result(False, str(err))
            session = _Session(ws)
            with self._lock:
                self._session = session
                self._players = {p["player_id"]: p for p in players if "player_id" in p}
            self.server_info = info
            threading.Thread(target=self._reader, args=(session,), name="ma-reader", daemon=True).start()
            self._set_status(Status.ONLINE)
            return Result(True, info.get("name") or "Music Assistant", info)

    def disconnect(self, reason: str = "") -> None:
        with self._lock:
            session = self._session
        if session is not None:
            self._close_session(session, reason)

    def _close_session(self, session: _Session, reason: str) -> None:
        with self._lock:
            if session.closed.is_set():
                return
            session.closed.set()
            if self._session is session:
                self._session = None
            self._players = {}
            pending, self._pending = self._pending, {}
        try:
            session.ws.close(timeout=1)
        except Exception:  # noqa: BLE001 - best effort
            pass
        for item in pending.values():
            item.error = reason or _("Offline")
            item.event.set()
        self._set_status(Status.OFFLINE, reason)

    # ------------------------------------------------------------- commands

    def check(self, timeout: float) -> bool:
        """Is the server answering right now? (WebSocket ping → pong)"""
        session = self._session
        if session is None or not self.online:
            return False
        with session.check_lock:
            session.pong.clear()
            try:
                with session.send_lock:
                    session.ws.ping(b"check")
            except (OSError, websocket.WebSocketException):
                self._close_session(session, _("Server unreachable"))
                return False
            if session.pong.wait(timeout):
                return True
        self._close_session(session, _("Server not answering"))
        return False

    def command(self, command: str, timeout: float, **args: Any) -> Result:
        """Check the server, then send the command and wait for its result."""
        if not self.online:
            return Result(False, _("Offline: use Connect in the menu"))
        if not self.check(timeout):
            return Result(False, self.error or _("Server unreachable"))
        session = self._session
        if session is None:
            return Result(False, _("Offline"))
        msg_id = uuid.uuid4().hex
        pending = _Pending()
        with self._lock:
            self._pending[msg_id] = pending
        try:
            with session.send_lock:
                session.ws.send(json.dumps({"message_id": msg_id, "command": command, "args": args}))
        except (OSError, websocket.WebSocketException):
            self._close_session(session, _("Server unreachable"))
            return Result(False, _("Server unreachable"))
        if not pending.event.wait(timeout):
            with self._lock:
                self._pending.pop(msg_id, None)
            return Result(False, _("Server not answering"))
        if pending.error is not None:
            return Result(False, pending.error)
        return Result(True, "ok", pending.value)

    def player_action(self, player_id: str, action: str, timeout: float) -> Result:
        command = ACTIONS.get(action)
        if command is None:
            return Result(False, f"unknown action '{action}'")
        player = self.players().get(player_id)
        if player and action in GROUP_VOLUME and player.get("type") == "group":
            command = GROUP_VOLUME[action]
        return self.command(command, timeout, player_id=player_id)

    # --------------------------------------------------------------- reader

    def _reader(self, session: _Session) -> None:
        ws = session.ws
        last_rx = last_ping = time.monotonic()
        reason = ""
        try:
            while not session.closed.is_set():
                sock = ws.sock
                if sock is None:
                    reason = _("Server unreachable")
                    break
                ready = getattr(sock, "pending", lambda: 0)() or select.select([sock], [], [], 1.0)[0]
                now = time.monotonic()
                if ready:
                    opcode, frame = ws.recv_data_frame(True)
                    last_rx = now
                    if opcode == websocket.ABNF.OPCODE_CLOSE:
                        reason = _("Server unreachable")
                        break
                    if opcode == websocket.ABNF.OPCODE_PONG:
                        session.pong.set()
                    elif opcode == websocket.ABNF.OPCODE_TEXT:
                        data = frame.data.decode() if isinstance(frame.data, bytes) else frame.data
                        self._handle(json.loads(data))
                if now - last_ping >= KEEPALIVE_INTERVAL:
                    with session.send_lock:
                        ws.ping(b"keepalive")
                    last_ping = now
                if now - last_rx >= IDLE_DEADLINE:
                    reason = _("Server not answering")
                    break
        except (OSError, ValueError, websocket.WebSocketException) as err:
            if not session.closed.is_set():
                LOGGER.info("Connection lost: %s", err)
            reason = _("Server unreachable")
        self._close_session(session, reason)

    def _handle(self, msg: dict) -> None:
        if "event" in msg:
            event, oid, data = msg["event"], msg.get("object_id"), msg.get("data")
            if event in ("player_added", "player_updated") and oid and isinstance(data, dict):
                with self._lock:
                    self._players[oid] = data
                self._on_change()
            elif event == "player_removed" and oid:
                with self._lock:
                    self._players.pop(oid, None)
                self._on_change()
            return
        msg_id = msg.get("message_id")
        with self._lock:
            pending = self._pending.get(msg_id) if msg_id else None
            if pending is None:
                return
            if msg.get("partial"):
                pending.value = (pending.value or []) + list(msg.get("result") or [])
                return
            del self._pending[msg_id]
        if "error_code" in msg:
            pending.error = msg.get("details") or _("Command failed")
        elif isinstance(pending.value, list):
            pending.value += list(msg.get("result") or [])
        else:
            pending.value = msg.get("result")
        pending.event.set()


def selectable_players(players: dict[str, dict]) -> list[dict]:
    """Players worth offering in the UI, sorted by name."""
    result = [
        p for p in players.values()
        if p.get("available", True) and p.get("enabled", True)
        and not p.get("hide_in_ui") and not p.get("synced_to")
        and p.get("type", "player") in USER_PLAYER_TYPES
    ]
    return sorted(result, key=lambda p: player_name(p).lower())


def player_name(player: dict) -> str:
    return player.get("display_name") or player.get("name") or player.get("player_id", "?")
