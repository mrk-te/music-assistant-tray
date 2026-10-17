# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marc Teinturier <m@m-te.fr>

"""Glue between the client, the selected player and the front-ends (tray, CLI socket)."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

from .config import Config, load_config, load_state, save_config, save_state
from .connection import MAClient, Result, Status, player_name, selectable_players
from .i18n import _

LOGGER = logging.getLogger(__name__)


class Controller:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self._listeners: list[Callable[[], None]] = []
        self._selected: str | None = load_state().get("player_id")
        self.client = MAClient(self._notify)
        # One worker thread runs every blocking call issued by the UI, in order.
        self._jobs: queue.Queue[Callable[[], None]] = queue.Queue()
        threading.Thread(target=self._worker, name="ma-worker", daemon=True).start()

    # ------------------------------------------------------------ plumbing

    def add_listener(self, cb: Callable[[], None]) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in self._listeners:
            cb()

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception:  # noqa: BLE001 - never let the worker die
                LOGGER.exception("Background job failed")

    def submit(self, job: Callable[[], None]) -> None:
        self._jobs.put(job)

    # ---------------------------------------------------------- connection

    def connect(self) -> Result:
        """Blocking connect (start-up, 'Connect' button, settings saved)."""
        result = self.client.connect(self.config)
        if result.ok and not self.config.server_id:
            # Pin this server: a different machine at the same address won't get the token.
            self.config.server_id = result.value.get("server_id", "")
            save_config(self.config)
            LOGGER.info("Paired with server %s", self.config.server_id)
        return result

    def connect_async(self) -> None:
        self.submit(self.connect)

    def apply_config(self, new: Config) -> None:
        """Save new settings and reconnect if the connection parameters changed."""
        old = self.config
        if new.url != old.url:
            new.server_id = ""  # new address → pair again
        self.config = new
        save_config(new)
        if (new.url, new.token, new.server_id, new.timeout) != (old.url, old.token, old.server_id, old.timeout) \
                or not self.client.online:
            self.connect_async()
        else:
            self._notify()

    # ------------------------------------------------------------- players

    def players(self) -> list[dict]:
        return selectable_players(self.client.players())

    def selected_player(self) -> dict | None:
        players = self.players()
        if not players:
            return None
        by_id = {p["player_id"]: p for p in players}
        for wanted in (self._selected, self.config.default_player):
            if wanted and wanted in by_id:
                return by_id[wanted]
        for p in players:  # something already playing is the most likely target
            if p.get("playback_state") == "playing":
                return p
        return players[0]

    def select(self, player_id: str) -> None:
        self._selected = player_id
        save_state({"player_id": player_id})
        self._notify()

    # ------------------------------------------------------------- actions

    def act(self, action: str) -> Result:
        """Blocking: check the server, then run the action on the selected player."""
        if not self.client.online:
            if self.client.status is Status.CONNECTING:
                return Result(False, _("Connecting…"))
            return Result(False, _("Offline: use Connect in the menu"))
        player = self.selected_player()
        if player is None:
            return Result(False, _("No player available"))
        return self.client.player_action(player["player_id"], action, self.config.timeout)

    def act_async(self, action: str) -> None:
        self.submit(lambda: self.act(action))

    def status(self) -> dict:
        info: dict = {"status": self.client.status.value, "error": self.client.error}
        player = self.selected_player() if self.client.online else None
        if player:
            media = player.get("current_media") or {}
            info.update(
                player=player_name(player),
                player_id=player["player_id"],
                playback=player.get("playback_state"),
                volume=player.get("volume_level"),
                muted=player.get("volume_muted"),
                title=media.get("title"),
                artist=media.get("artist"),
            )
        return info
