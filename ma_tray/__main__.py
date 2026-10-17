# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marc Teinturier <m@m-te.fr>

"""Command line entry point.

  ma-tray [run]          run the top-bar app (default)
  ma-tray ctl ACTION     control the running app (for keyboard shortcuts)
  ma-tray check          test the saved settings once and list the players
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import shutil
import subprocess
import sys

from . import __version__
from .config import STATE_DIR, load_config
from .i18n import _


def _setup_logging(verbose: bool, to_file: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            STATE_DIR / "ma-tray.log", maxBytes=256_000, backupCount=1))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def _notify(body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Music Assistant", "-i", "audio-volume-muted-symbolic",
                        "-t", "2500", "-h", "string:x-canonical-private-synchronous:ma-tray",
                        "Music Assistant", body], check=False)


def cmd_run(_args: argparse.Namespace) -> int:
    from .control import ControlServer
    from .controller import Controller
    from .indicator import TrayApp

    controller = Controller()
    try:
        server = ControlServer(controller)
    except RuntimeError as err:
        logging.error("%s", err)
        return 1
    server.start()
    try:
        TrayApp(controller).run()
    finally:
        server.stop()
    return 0


def cmd_ctl(args: argparse.Namespace) -> int:
    from .control import EXIT_ERROR, EXIT_NO_DAEMON, EXIT_OFFLINE, EXIT_OK, VALID, normalize, send

    action = normalize(args.action)
    if action not in VALID:
        print(f"unknown action '{args.action}'. Valid: {', '.join(sorted(VALID))}", file=sys.stderr)
        return EXIT_ERROR
    reply = send(action, timeout=20 if action == "connect" else 10)
    if reply is None:
        print(_("ma-tray is not running"), file=sys.stderr)
        if args.notify:
            _notify(_("ma-tray is not running"))
        return EXIT_NO_DAEMON
    if args.json or action == "status":
        print(json.dumps(reply, ensure_ascii=False, indent=None if args.json else 2))
    if reply.get("ok"):
        return EXIT_OK
    message = reply.get("detail") or _("Command failed")
    if not args.json:
        print(message, file=sys.stderr)
    if args.notify:
        _notify(message)
    return EXIT_OFFLINE if reply.get("status") != "online" else EXIT_ERROR


def cmd_check(_args: argparse.Namespace) -> int:
    from .config import CONFIG_FILE
    from .connection import ConnectError, handshake, player_name, selectable_players

    config = load_config()
    print(f"Config  : {CONFIG_FILE}")
    print(f"Server  : {config.url or '-'}")
    try:
        ws, info, players = handshake(config)
        ws.close()
    except ConnectError as err:
        print(f"Result  : FAILED ({err})")
        return 1
    usable = selectable_players({p["player_id"]: p for p in players if "player_id" in p})
    print(f"Result  : OK, {info.get('name') or 'Music Assistant'} {info.get('server_version', '')} "
          f"(schema {info.get('schema_version')}, server_id {info.get('server_id')})")
    print(f"Players : {len(usable)}")
    for p in usable:
        print(f"  - {player_name(p)}  [{p['player_id']}]  {p.get('type')}  "
              f"{p.get('playback_state')}  volume={p.get('volume_level')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ma-tray", description="Music Assistant in the GNOME top bar")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="run the top-bar app (default)")
    ctl = sub.add_parser("ctl", help="control the running app")
    ctl.add_argument("action", help="up | down | play | pause | toggle | stop | next | previous | connect | status")
    ctl.add_argument("--notify", action="store_true", help="desktop notification on failure")
    ctl.add_argument("--json", action="store_true", help="print the raw JSON reply")
    sub.add_parser("check", help="test the saved settings and list players")

    args = parser.parse_args(argv)
    cmd = args.cmd or "run"
    _setup_logging(args.verbose, to_file=(cmd == "run"))
    if cmd != "run" and not args.verbose:
        logging.getLogger().setLevel(logging.WARNING)
    return {"run": cmd_run, "ctl": cmd_ctl, "check": cmd_check}[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
