#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marc Teinturier <m@m-te.fr>
# Install ma-tray for the current user (Ubuntu 24.04 / 26.04, GNOME).
#   ./install.sh            install / update
#   ./install.sh --uninstall
set -euo pipefail

APP_DIR="$HOME/.local/share/ma-tray"
BIN="$HOME/.local/bin/ma-tray"
AUTOSTART="$HOME/.config/autostart/ma-tray.desktop"
CONF_DIR="$HOME/.config/ma-tray"
SRC="$(cd "$(dirname "$0")" && pwd)"

if [[ "${1:-}" == "--uninstall" ]]; then
    pkill -u "$(id -u)" -f "python3 -m ma_tray( run)?$" || true
    rm -rf "$APP_DIR" "$BIN" "$AUTOSTART"
    echo "Removed. Config kept in $CONF_DIR (delete it yourself if you want)."
    echo "Keyboard shortcuts, if set up: ./setup-shortcuts.sh --remove"
    exit 0
fi

PKGS=(python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 python3-websocket libnotify-bin)
missing=()
for p in "${PKGS[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
done
if ((${#missing[@]})); then
    echo "Installing: ${missing[*]}"
    sudo apt-get install -y "${missing[@]}"
fi

mkdir -p "$APP_DIR" "$(dirname "$BIN")" "$(dirname "$AUTOSTART")"
rm -rf "$APP_DIR/ma_tray"
cp -r "$SRC/ma_tray" "$APP_DIR/"
find "$APP_DIR" -name __pycache__ -prune -exec rm -rf {} +

cat > "$BIN" <<EOF
#!/bin/sh
PYTHONPATH="$APP_DIR" exec /usr/bin/python3 -m ma_tray "\$@"
EOF
chmod 755 "$BIN"

cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Music Assistant tray
Comment=Control Music Assistant from the top bar
Exec=$BIN run
Icon=audio-speakers-symbolic
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
NoDisplay=true
EOF

if ! gnome-extensions list --enabled 2>/dev/null | grep -qi appindicator; then
    echo
    echo "Note: the AppIndicator GNOME extension doesn't look enabled."
    echo "      Ubuntu ships it as 'ubuntu-appindicators@ubuntu.com':"
    echo "      gnome-extensions enable ubuntu-appindicators@ubuntu.com"
fi

echo
echo "Installed ma-tray to $APP_DIR"
echo
echo "Start it now:   setsid -f $BIN >/dev/null 2>&1"
echo "(It also starts at every login. On first launch the settings window opens:"
echo " enter your server URL and token, click Test, then Save.)"
echo "Optional:       ./setup-shortcuts.sh"
