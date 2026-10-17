# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marc Teinturier <m@m-te.fr>

"""Settings window (GTK 3)."""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .config import Config  # noqa: E402
from .connection import ConnectError, handshake, player_name, selectable_players  # noqa: E402
from .i18n import _  # noqa: E402

if TYPE_CHECKING:
    from .controller import Controller


class SettingsWindow(Gtk.Dialog):
    def __init__(self, controller: Controller) -> None:
        super().__init__(title=_("Music Assistant settings"))
        self.controller = controller
        cfg = controller.config
        self._server_id = cfg.server_id
        self._original_url = cfg.url
        self.set_default_size(460, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("audio-speakers")

        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        save = self.add_button(_("Save"), Gtk.ResponseType.OK)
        save.get_style_context().add_class("suggested-action")
        action_area = save.get_parent()
        action_area.set_margin_end(12)
        action_area.set_margin_bottom(12)
        self.set_default_response(Gtk.ResponseType.OK)
        self.connect("response", self._on_response)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=18)
        self.get_content_area().add(grid)
        row = 0

        def heading(text: str) -> None:
            nonlocal row
            label = Gtk.Label(xalign=0)
            label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
            grid.attach(label, 0, row, 2, 1)
            row += 1

        def field(text: str, widget: Gtk.Widget) -> None:
            nonlocal row
            grid.attach(Gtk.Label(label=text, xalign=0), 0, row, 1, 1)
            widget.set_hexpand(True)
            grid.attach(widget, 1, row, 1, 1)
            row += 1

        # --- Server
        heading(_("Server"))
        self.url = Gtk.Entry(text=cfg.url, placeholder_text="http://192.168.1.20:8095", activates_default=True)
        field(_("Server URL"), self.url)

        self.token = Gtk.Entry(text=cfg.token, visibility=False, activates_default=True)
        field(_("Token"), self.token)
        show = Gtk.CheckButton(label=_("Show token"))
        show.connect("toggled", lambda b: self.token.set_visibility(b.get_active()))
        grid.attach(show, 1, row, 1, 1)
        row += 1
        hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
        hint.set_markup(f"<small>{GLib.markup_escape_text(_('Create a long-lived token in the Music Assistant web UI (your profile).'))}</small>")
        grid.attach(hint, 1, row, 1, 1)
        row += 1

        self.timeout = Gtk.SpinButton.new_with_range(1, 15, 1)
        self.timeout.set_value(cfg.timeout)
        field(_("Timeout (s)"), self.timeout)

        pair_box = Gtk.Box(spacing=6)
        self.pair_label = Gtk.Label(xalign=0, wrap=True, max_width_chars=40)
        self.pair_label.get_style_context().add_class("dim-label")
        forget = Gtk.Button(label=_("Forget"))
        forget.connect("clicked", self._forget_pairing)
        pair_box.pack_start(self.pair_label, True, True, 0)
        pair_box.pack_end(forget, False, False, 0)
        grid.attach(pair_box, 1, row, 1, 1)
        row += 1
        self._update_pair_label()

        test_box = Gtk.Box(spacing=8)
        self.test_button = Gtk.Button(label=_("Test"))
        self.test_button.connect("clicked", self._run_test)
        self.test_result = Gtk.Label(xalign=0, wrap=True, max_width_chars=40)
        test_box.pack_start(self.test_button, False, False, 0)
        test_box.pack_start(self.test_result, True, True, 0)
        grid.attach(test_box, 1, row, 1, 1)
        row += 1

        # --- Behaviour
        grid.attach(Gtk.Separator(margin_top=6, margin_bottom=6), 0, row, 2, 1)
        row += 1
        heading(_("Behaviour"))
        self.player = Gtk.ComboBoxText()
        self._fill_players(selectable_players(controller.client.players()), cfg.default_player)
        field(_("Default player"), self.player)

        self.show_volume = Gtk.CheckButton(label=_("Show volume next to the icon"), active=cfg.show_volume_label)
        grid.attach(self.show_volume, 0, row, 2, 1)

        self.show_all()

    # ------------------------------------------------------------ helpers

    def _fill_players(self, players: list[dict], selected: str) -> None:
        self.player.remove_all()
        self.player.append("", _("Automatic"))
        ids = set()
        for p in players:
            self.player.append(p["player_id"], player_name(p))
            ids.add(p["player_id"])
        if selected and selected not in ids:
            self.player.append(selected, selected)  # keep a configured player that is offline
        self.player.set_active_id(selected or "")

    def _update_pair_label(self) -> None:
        if self._server_id:
            self.pair_label.set_text(_("Paired server: {id}", id=self._server_id[:12]))
        else:
            self.pair_label.set_text(_("Not paired yet (done at the first successful connection)"))

    def _forget_pairing(self, *_args) -> None:
        self._server_id = ""
        self._update_pair_label()

    def _current(self) -> Config:
        url = self.url.get_text().strip().rstrip("/")
        server_id = self._server_id if url == self._original_url else ""
        return replace(
            self.controller.config,
            url=url,
            token=self.token.get_text().strip(),
            timeout=float(self.timeout.get_value_as_int()),
            server_id=server_id,
            default_player=self.player.get_active_id() or "",
            show_volume_label=self.show_volume.get_active(),
        )

    # --------------------------------------------------------------- test

    def _run_test(self, *_args) -> None:
        config = self._current()
        self.test_button.set_sensitive(False)
        self.test_result.set_text(_("Testing…"))

        def work() -> None:
            try:
                ws, info, players = handshake(config)
                ws.close()
            except ConnectError as err:
                GLib.idle_add(self._test_done, False, str(err), None, [])
                return
            GLib.idle_add(self._test_done, True, info.get("name") or "Music Assistant", info, players)

        threading.Thread(target=work, daemon=True).start()

    def _test_done(self, ok: bool, message: str, info: dict | None, players: list[dict]) -> bool:
        self.test_button.set_sensitive(True)
        if ok:
            usable = selectable_players({p["player_id"]: p for p in players if "player_id" in p})
            self.test_result.set_markup(
                f"<span foreground='#2e7d32'>✔ {GLib.markup_escape_text(_('Connected to {name}: {count} player(s)', name=message, count=len(usable)))}</span>"
            )
            self._fill_players(usable, self.player.get_active_id() or "")
            if info and not self._server_id:
                self._server_id = info.get("server_id", "")
                self._original_url = self.url.get_text().strip().rstrip("/")
                self._update_pair_label()
        else:
            self.test_result.set_markup(f"<span foreground='#c62828'>✘ {GLib.markup_escape_text(message)}</span>")
        return False

    # ------------------------------------------------------------ closing

    def _on_response(self, _dialog, response: int) -> None:
        if response == Gtk.ResponseType.OK:
            self.controller.apply_config(self._current())
        self.destroy()
