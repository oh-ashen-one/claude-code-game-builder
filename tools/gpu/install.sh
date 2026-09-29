#!/bin/bash
# Homage fan game tooling. Not an official Marvel, Sony or Insomniac project; no affiliation.
# Copies the lock tool to a stable path every builder can call before they have merged night1/gpulock:
#   ${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/bin/{gpu_slot.sh,gpu_slot.py,gpu_status.sh}
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST=${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/bin
mkdir -p "$DEST"
cp "$HERE/gpu_slot.sh" "$HERE/gpu_slot.py" "$HERE/gpu_status.sh" "$DEST/"
chmod +x "$DEST"/*
echo "installed -> $DEST"
