#!/bin/bash
# Installs the stream guard: copies stream_guard.py next to the gpu_slot tools and loads a user LaunchAgent
# that runs the daily stream window (default 10:55 -> 13:05 local time; owner streams 11-13 ET).
#   tools/stream/install.sh [START_HH:MM] [END_HH:MM]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
START=${1:-10:55}; END=${2:-13:05}
DEST=${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/bin
LOGF=${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/stream_guard.launchd.log
PLIST=$HOME/Library/LaunchAgents/com.ashen.stream-guard.plist
mkdir -p "$DEST" "$HOME/Library/LaunchAgents" "$HOME/.local/bin"
cp "$HERE/stream_guard.py" "$DEST/"; chmod +x "$DEST/stream_guard.py"
ln -sf "$DEST/stream_guard.py" "$HOME/.local/bin/stream-guard"
sed -e "s|__BIN__|$DEST|g" -e "s|__END__|$END|g" -e "s|__LOG__|$LOGF|g" \
    -e "s|__START_H__|$((10#${START%%:*}))|g" -e "s|__START_M__|$((10#${START##*:}))|g" \
    "$HERE/com.ashen.stream-guard.plist.template" > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/com.ashen.stream-guard" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed -> $DEST/stream_guard.py ; LaunchAgent com.ashen.stream-guard fires daily at $START, ends $END"
echo "manual: stream-guard on | off | status"
