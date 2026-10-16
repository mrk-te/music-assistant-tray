"""Top-bar indicator (AppIndicator / Ayatana) for GNOME on Ubuntu.

- Left click: menu
- Middle click: play/pause
- Scroll on the icon: volume up/down
"""

from __future__ import annotations

import logging
import signal
import time

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppIndicator
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .connection import Status, player_name  # noqa: E402
from .controller import Controller  # noqa: E402
from .i18n import _  # noqa: E402
from .settings import SettingsWindow  # noqa: E402

LOGGER = logging.getLogger(__name__)

# Four states. Speaker-like icons are avoided on purpose: they look exactly
# like GNOME's own volume indicator.
ICON_PLAYING = "media-playback-start-symbolic"   # playing
ICON_PAUSED = "media-playback-pause-symbolic"    # paused
ICON_STOPPED = "media-playback-stop-symbolic"    # online, idle/stopped/unknown, or no player
ICON_OFFLINE = "network-offline-symbolic"        # offline, connecting, not configured

SCROLL_MIN_INTERVAL = 0.15  # seconds: a touchpad swipe shouldn't send 20 steps


def _ellipsize(text: str, limit: int = 48) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TrayApp:
    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self._refresh_scheduled = False
        self._player_ids: list[tuple[str, str]] = []
        self._updating_radio = False
        self._last_scroll = 0.0
        self._settings: SettingsWindow | None = None

        self.indicator = AppIndicator.Indicator.new(
            "ma-tray", ICON_OFFLINE, AppIndicator.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_title("Music Assistant")
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.connect("scroll-event", self._on_scroll)
        self._build_menu()
        controller.add_listener(self._schedule_refresh)
        self._refresh()

    # --------------------------------------------------------------- menu

    def _build_menu(self) -> None:
        menu = Gtk.Menu()

        def item(label: str, callback=None, sensitive: bool = True) -> Gtk.MenuItem:
            mi = Gtk.MenuItem(label=label)
            if callback:
                mi.connect("activate", lambda *_a: callback())
            mi.set_sensitive(sensitive)
            menu.append(mi)
            return mi

        self.item_header = item("", sensitive=False)
        self.item_sub = item("", sensitive=False)
        menu.append(Gtk.SeparatorMenuItem())

        self.item_toggle = item(_("Play"), lambda: self.controller.act_async("toggle"))
        self.item_stop = item(_("Stop"), lambda: self.controller.act_async("stop"))
        self.item_up = item(_("Volume up"), lambda: self.controller.act_async("up"))
        self.item_down = item(_("Volume down"), lambda: self.controller.act_async("down"))
        self.item_next = item(_("Next track"), lambda: self.controller.act_async("next"))
        self.item_prev = item(_("Previous track"), lambda: self.controller.act_async("previous"))
        self.action_items = [self.item_toggle, self.item_stop, self.item_up,
                             self.item_down, self.item_next, self.item_prev]
        menu.append(Gtk.SeparatorMenuItem())

        self.item_players = item(_("Player"))
        self.players_menu = Gtk.Menu()
        self.item_players.set_submenu(self.players_menu)
        menu.append(Gtk.SeparatorMenuItem())

        self.item_connect = item(_("Connect"), self.controller.connect_async)
        item(_("Settings…"), self.open_settings)
        self.item_open = item(_("Open Music Assistant"), self._open_web)
        item(_("Quit"), self.quit)

        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_secondary_activate_target(self.item_toggle)  # middle click

    def _rebuild_players(self, players: list[dict], selected_id: str | None) -> None:
        ids = [(p["player_id"], player_name(p)) for p in players]
        self._updating_radio = True
        try:
            if ids != self._player_ids:
                for child in self.players_menu.get_children():
                    self.players_menu.remove(child)
                group = None
                for pid, name in ids:
                    radio = Gtk.RadioMenuItem.new_with_label_from_widget(group, name)
                    group = radio
                    radio.player_id = pid
                    radio.connect("toggled", self._on_player_toggled)
                    self.players_menu.append(radio)
                self.players_menu.show_all()
                self._player_ids = ids
            for child in self.players_menu.get_children():
                child.set_active(getattr(child, "player_id", None) == selected_id)
        finally:
            self._updating_radio = False

    def _on_player_toggled(self, radio: Gtk.RadioMenuItem) -> None:
        if not self._updating_radio and radio.get_active():
            self.controller.select(radio.player_id)

    # ------------------------------------------------------------ actions

    def _on_scroll(self, _indicator, _delta: int, direction: Gdk.ScrollDirection) -> None:
        now = time.monotonic()
        if now - self._last_scroll < SCROLL_MIN_INTERVAL:
            return
        self._last_scroll = now
        if direction == Gdk.ScrollDirection.UP:
            self.controller.act_async("up")
        elif direction == Gdk.ScrollDirection.DOWN:
            self.controller.act_async("down")

    def _open_web(self) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(self.controller.config.url, None)
        except GLib.Error as err:
            LOGGER.warning("Could not open browser: %s", err)

    def open_settings(self) -> None:
        if self._settings is not None:
            self._settings.present()
            return
        self._settings = SettingsWindow(self.controller)
        self._settings.connect("destroy", lambda *_a: setattr(self, "_settings", None))

    # ------------------------------------------------------------ refresh

    def _schedule_refresh(self) -> None:
        # Called from background threads: coalesce bursts of player events.
        if not self._refresh_scheduled:
            self._refresh_scheduled = True
            GLib.timeout_add(100, self._refresh)

    def _refresh(self) -> bool:
        self._refresh_scheduled = False
        cfg = self.controller.config
        client = self.controller.client
        status = client.status
        online = status is Status.ONLINE
        player = self.controller.selected_player() if online else None

        if online and player is not None:
            playback = player.get("playback_state")
            media = player.get("current_media") or {}
            volume, muted = player.get("volume_level"), player.get("volume_muted")
            icon = {"playing": ICON_PLAYING, "paused": ICON_PAUSED}.get(playback, ICON_STOPPED)
            self.indicator.set_icon_full(icon, f"Music Assistant: {playback}")
            title, artist = media.get("title"), media.get("artist")
            header = (f"{title} · {artist}" if artist else title) if title else _("Nothing playing")
            vol_txt = _("muted") if muted else (f"{volume}%" if volume is not None else "—")
            self.item_header.set_label(_ellipsize(header))
            self.item_sub.set_label(_ellipsize(f"{player_name(player)} · {_('volume')} {vol_txt}"))
            self.item_sub.show()
            self.item_toggle.set_label(_("Pause") if playback == "playing" else _("Play"))
            label = (_("muted") if muted else f"{volume}%") if cfg.show_volume_label and volume is not None else ""
            self.indicator.set_label(label, "100%")
            self._rebuild_players(self.controller.players(), player["player_id"])
        else:
            if online:
                header = _("No player available")
            elif status is Status.CONNECTING:
                header = _("Connecting…")
            elif not cfg.complete:
                header = _("Not configured")
            else:
                header = _("Offline")
            self.indicator.set_icon_full(ICON_STOPPED if online else ICON_OFFLINE, header)
            self.indicator.set_label("", "")
            self.item_toggle.set_label(_("Play"))
            self.item_header.set_label(header)
            self.item_sub.set_label(_ellipsize(client.error))
            self.item_sub.set_visible(bool(client.error) and not online)
            self._rebuild_players([], None)

        has_player = online and player is not None
        for mi in self.action_items:
            mi.set_sensitive(has_player)
        self.item_players.set_sensitive(has_player)
        self.item_connect.set_visible(not online)
        self.item_connect.set_sensitive(status is not Status.CONNECTING)
        self.item_open.set_sensitive(bool(cfg.url))
        return False

    # -------------------------------------------------------------- run

    def run(self) -> None:
        if self.controller.config.complete:
            self.controller.connect_async()     # test the server once at start-up
        else:
            GLib.idle_add(lambda: (self.open_settings(), False)[1])
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (self.quit(), False)[1])
        Gtk.main()

    def quit(self) -> None:
        self.controller.client.disconnect()
        Gtk.main_quit()
