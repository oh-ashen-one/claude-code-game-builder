#!/bin/bash
# Homage fan game tooling. Not an official Marvel, Sony or Insomniac project; no affiliation.
# Prints PAUSED, lock holders, waiters, GPU utilization, every GPU client by kind and stuck engines. `--json` for machines.
PY="$(command -v python3 || echo /usr/bin/python3)"
exec "$PY" "$(cd "$(dirname "$0")" && pwd)/gpu_slot.py" status "$@"
