# ma-tray

Control a standalone [Music Assistant](https://www.music-assistant.io/) server from the GNOME top bar on Ubuntu: play/pause, stop, volume, next/previous track and player selection. Keyboard shortcuts are optional.

## Features

- **Top-bar icon** with four states, plus the volume next to it (e.g. `35%`):
  - ▶ playing;
  - ⏸ paused;
  - ⏹ stopped or idle. Note that Music Assistant moves a paused player to idle after a while;
  - network-offline icon: offline, connecting or not configured.
  - Left click opens the menu: current track, player and volume, Play/Pause, Stop, Volume +/−, Next/Previous, player picker, Connect, Settings…
  - Scroll on the icon changes the volume.
  - Middle click toggles play/pause.
- **Predictable online/offline behaviour:**
  - At start-up, ma-tray tests the server once.
  - Before every command, it checks that the server answers (WebSocket ping, *timeout* seconds). If it doesn't, the command is not sent.
  - If the server is unreachable, ma-tray goes **offline** and stays offline. There are no background retries. Click **Connect** in the menu when the server is available again.
- **Settings window** for the server URL, token, timeout, default player and volume label. A **Test** button checks the settings before you save them.
- **Server pairing.** The first successful connection records the server's ID. If a different machine later answers at the same address (another network, another device), ma-tray refuses to send it your token. Use **Forget** in the settings after reinstalling Music Assistant.
- **CLI and keyboard shortcuts.** `ma-tray ctl up` and friends drive the running app through a private Unix socket and reuse its connection.
- English or French interface, depending on the desktop language.

## Requirements

- Ubuntu 24.04 or 26.04 with the default GNOME session. Other distributions with GNOME + AppIndicator support should work too.
- A standalone Music Assistant server reachable over HTTP/WebSocket, usually on port `8095`. Token authentication (Music Assistant 2.7+) is expected.
- The **AppIndicator** GNOME extension. Ubuntu ships and enables it by default (`ubuntu-appindicators@ubuntu.com`).
- System packages only, no pip or virtualenv:

| Package | Why |
|---|---|
| `python3` (3.12+) | Runtime. 24.04 ships 3.12, 26.04 a newer one |
| `python3-gi`, `gir1.2-gtk-3.0` | GTK 3 bindings (menu, settings window) |
| `gir1.2-ayatanaappindicator3-0.1` | Top-bar indicator |
| `python3-websocket` | WebSocket client for the Music Assistant API |
| `libnotify-bin` | `notify-send`, used by keyboard shortcuts to report errors |

`install.sh` installs any missing package with `apt` (it asks for your sudo password if needed).

## Installation

```bash
tar xzf ma-tray-*.tar.gz
cd ma-tray
./install.sh
setsid -f ma-tray >/dev/null 2>&1
```

`setsid -f` starts the app detached from the terminal. With a plain `ma-tray &`, it would stop when you close the terminal. You only need this once: from then on it starts automatically at login.

The installer:
- copies the app to `~/.local/share/ma-tray`;
- creates the `~/.local/bin/ma-tray` launcher;
- adds `~/.config/autostart/ma-tray.desktop` so the app starts at login.

If `~/.local/bin` isn't on your `PATH` yet, log out and back in, or use the full path.

### Updating

Run `./install.sh` again from the new version, then restart the app:

```bash
pkill -f 'python3 -m ma_tray'; setsid -f ma-tray >/dev/null 2>&1
```

### Uninstalling

```bash
./install.sh --uninstall
./setup-shortcuts.sh --remove   # if you installed the shortcuts
rm -r ~/.config/ma-tray         # optional: settings and token
```

## Configuration

On first launch the settings window opens automatically. Later you can open it from the menu with **Settings…**.

1. **Server URL**: the address of the Music Assistant web UI, e.g. `http://192.168.1.20:8095`.
2. **Token**: create a long-lived token in the Music Assistant web UI (your user profile) and paste it.
3. **Timeout**: how long to wait when connecting and for the check before each command. The default of 3 s suits a LAN.
4. Click **Test**. It should report `Connected to <server>: N player(s)` and pair the server.
5. Optionally pick a **Default player** (otherwise the first playing player, or the first one alphabetically, is used). Choosing a player from the menu overrides it and is remembered.
6. Click **Save**. ma-tray reconnects with the new settings.

Settings are stored in `~/.config/ma-tray/config.toml` (mode `600`, since it contains the token). The file can also be edited by hand while the app is stopped:

```toml
[server]
url = "http://192.168.1.20:8095"
token = "eyJ..."
timeout = 3.0
server_id = ""          # filled in automatically at the first successful connection

[ui]
default_player = ""     # player_id, empty = automatic
show_volume_label = true
```

To check the configuration from a terminal:

```bash
ma-tray check
```

## Keyboard shortcuts (optional)

```bash
./setup-shortcuts.sh
```

This adds GNOME custom shortcuts and keeps your existing ones:

| Shortcut | Action |
|---|---|
| `Ctrl+Super+↑` / `Ctrl+Super+↓` | Volume up / down |
| `Ctrl+Super+Space` | Play/Pause |
| `Ctrl+Super+End` | Stop |
| `Ctrl+Super+Home` | Connect |

If a shortcut clashes with an existing one, change it in *Settings → Keyboard → View and Customise Shortcuts → Custom Shortcuts*, or edit the list at the top of the script and run it again. When a command fails (offline, server not answering), a desktop notification says why.

## Command line

```
ma-tray [run]              start the top-bar app (default)
ma-tray ctl ACTION         up | down | play | pause | toggle | stop | next | previous | connect | status
            [--notify]     desktop notification on failure
            [--json]       raw JSON reply
ma-tray check              test the saved settings and list the players
ma-tray -v ...             debug logging
```

`ctl` exit codes: `0` ok, `1` error, `2` offline (use `connect`), `3` app not running.

## Troubleshooting

- **Is it running?** Check with `pgrep -af ma_tray`. The process shows up as `python3 -m ma_tray`, with an underscore.
- **No icon in the top bar**: check that the AppIndicator extension is enabled: `gnome-extensions enable ubuntu-appindicators@ubuntu.com`, then log out and back in.
- **"Server unreachable"**: wrong URL or port, server down, or you're not on the network where the server lives. Fix it, then click **Connect**.
- **"Invalid token"**: the token was revoked or mistyped. Create a new one in the Music Assistant UI.
- **"Different server at this address: token not sent"**: the machine answering at this URL isn't the paired server. If you reinstalled Music Assistant, open **Settings…**, click **Forget**, then **Test** and **Save**.
- **A shortcut does nothing**: run its command in a terminal (`ma-tray ctl up`) to see the error.
- **Logs**: `~/.local/state/ma-tray/ma-tray.log`.

## How it works

ma-tray keeps one WebSocket connection to the Music Assistant API (`/ws`):
1. It authenticates with the token (`auth`).
2. It loads the players (`players/all`).
3. It receives `player_updated` events to keep the menu and the volume label live.

Commands use the standard player API: `players/cmd/play_pause`, `stop`, `volume_up`, `volume_down`, and so on. Group players use `group_volume_up/down`. The volume step is the server's own setting (*Settings → Players*).

While idle, a keepalive ping every 30 s also detects a dead connection. The app then goes offline, exactly as if a command had failed.

```
ma_tray/connection.py   WebSocket client: handshake, check (ping/pong), commands, events
ma_tray/controller.py   selected player, actions, settings persistence, server pairing
ma_tray/indicator.py    top-bar indicator and menu
ma_tray/settings.py     settings window
ma_tray/control.py      Unix socket used by `ma-tray ctl`
ma_tray/config.py       config.toml read/write
ma_tray/i18n.py         English/French strings
```
