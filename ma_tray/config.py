# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marc Teinturier <m@m-te.fr>

"""Configuration: ~/.config/ma-tray/config.toml, edited through the settings window."""

from __future__ import annotations

import json
import logging
import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ma-tray"
CONFIG_FILE = CONFIG_DIR / "config.toml"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "ma-tray"
STATE_FILE = STATE_DIR / "state.json"


def runtime_socket_path() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/ma-tray-{os.getuid()}"
    return Path(base) / "ma-tray.sock"


@dataclass
class Config:
    url: str = ""
    token: str = ""
    default_player: str = ""        # player_id, "" = automatic
    show_volume_label: bool = True
    timeout: float = 3.0            # seconds, for connecting and for the pre-command check
    server_id: str = ""             # pinned at the first successful connection

    @property
    def complete(self) -> bool:
        return self.url.startswith(("http://", "https://")) and bool(self.token)


def load_config(path: Path = CONFIG_FILE) -> Config:
    """Load the config; a missing file gives an empty (incomplete) config."""
    if not path.exists():
        return Config()
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as err:
        LOGGER.error("Cannot read %s: %s", path, err)
        return Config()

    server, ui = raw.get("server", {}), raw.get("ui", {})
    return Config(
        url=str(server.get("url", "")).strip().rstrip("/"),
        token=str(server.get("token", "")).strip(),
        server_id=str(server.get("server_id", "")),
        timeout=float(server.get("timeout", 3.0)),
        default_player=str(ui.get("default_player", "")),
        show_volume_label=bool(ui.get("show_volume_label", True)),
    )


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(str(value), ensure_ascii=False)  # JSON strings are valid TOML basic strings


def save_config(config: Config, path: Path = CONFIG_FILE) -> None:
    data = asdict(config)
    sections = {
        "server": ["url", "token", "timeout", "server_id"],
        "ui": ["default_player", "show_volume_label"],
    }
    lines = ["# ma-tray configuration. Edited by the settings window; safe to edit by hand.", ""]
    for section, keys in sections.items():
        lines.append(f"[{section}]")
        lines += [f"{key} = {_toml_value(data[key])}" for key in keys]
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # contains the token
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines))
    os.replace(tmp, path)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state))
    except OSError as err:
        LOGGER.warning("Could not save state: %s", err)
