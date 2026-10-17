#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marc Teinturier <m@m-te.fr>
# Add GNOME custom keyboard shortcuts that drive ma-tray.
#   ./setup-shortcuts.sh           add (or update) the shortcuts below
#   ./setup-shortcuts.sh --remove  remove them
# Existing custom shortcuts are preserved. Edit the bindings to taste;
# GNOME Settings → Keyboard → Custom Shortcuts shows them afterwards.
set -euo pipefail

BIN="$HOME/.local/bin/ma-tray"
SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
BASE="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

#        id            name                        action   binding
SHORTCUTS=(
  "ma-tray-up      |Music Assistant: volume up   |up      |<Control><Super>Up"
  "ma-tray-down    |Music Assistant: volume down |down    |<Control><Super>Down"
  "ma-tray-toggle  |Music Assistant: play/pause  |toggle  |<Control><Super>space"
  "ma-tray-stop    |Music Assistant: stop        |stop    |<Control><Super>End"
  "ma-tray-connect |Music Assistant: connect     |connect |<Control><Super>Home"
)

current=$(gsettings get "$SCHEMA" custom-keybindings)

# Rebuild the list: keep everything that isn't ours, then append ours.
new_list=$(python3 - "$current" "$BASE" "${1:-}" "${SHORTCUTS[@]}" <<'EOF'
import ast, sys
current, base, mode, *shortcuts = sys.argv[1:]
current = current.removeprefix("@as ")
paths = [p for p in ast.literal_eval(current) if "/ma-tray-" not in p]
if mode != "--remove":
    paths += [f"{base}/{s.split('|')[0].strip()}/" for s in shortcuts]
print(str(paths))
EOF
)

if [[ "${1:-}" == "--remove" ]]; then
    for s in "${SHORTCUTS[@]}"; do
        id=$(echo "${s%%|*}" | xargs)
        gsettings reset-recursively "$SCHEMA.custom-keybinding:$BASE/$id/" 2>/dev/null || true
    done
    gsettings set "$SCHEMA" custom-keybindings "$new_list"
    echo "ma-tray shortcuts removed."
    exit 0
fi

for s in "${SHORTCUTS[@]}"; do
    IFS='|' read -r id name action binding <<<"$s"
    id=$(echo "$id" | xargs); name=$(echo "$name" | xargs)
    action=$(echo "$action" | xargs); binding=$(echo "$binding" | xargs)
    path="$SCHEMA.custom-keybinding:$BASE/$id/"
    gsettings set "$path" name "$name"
    gsettings set "$path" command "$BIN ctl $action --notify"
    gsettings set "$path" binding "$binding"
    printf '  %-24s %s\n' "$binding" "$name"
done
gsettings set "$SCHEMA" custom-keybindings "$new_list"
echo "Shortcuts installed. If one doesn't fire, it probably clashes with an existing binding:"
echo "change it in GNOME Settings → Keyboard → View and Customise Shortcuts → Custom Shortcuts."
