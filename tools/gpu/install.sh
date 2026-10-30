#!/bin/bash
# Homage fan game tooling. Not an official Marvel, Sony or Insomniac project; no affiliation.
# Copies the lock tool to a stable path every builder can call before they have merged night1/gpulock:
#   ${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/bin/{gpu_slot.sh,gpu_slot.py,gpu_status.sh}
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST=${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/bin
mkdir -p "$DEST"
# atomic per file (copy to a temp name in DEST, chmod, rename): a session that execs gpu_slot.sh during the
# install reads either the old or the new file, never a half-written one; running processes keep the code they loaded
put() { local tmp="$DEST/.$(basename "$1").new.$$"; cp "$1" "$tmp" && chmod +x "$tmp" && mv -f "$tmp" "$DEST/$(basename "$1")"; }
for f in "$HERE/gpu_slot.sh" "$HERE/gpu_slot.py" "$HERE/gpu_status.sh"; do put "$f"; done
[ -f "$HERE/../stream/stream_guard.py" ] && put "$HERE/../stream/stream_guard.py"
echo "installed -> $DEST"
