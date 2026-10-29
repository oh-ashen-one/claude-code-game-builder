#!/bin/bash
# Installs the GPU health watchdog (tools/gpu/gpu_watchdog.py) as a user LaunchAgent. Idempotent.
#   tools/gpu/install_watchdog.sh
# 1. compiles tools/gpu/metal_probe.swift -> $DIR/bin/metal_probe (skipped if swiftc is missing: the watchdog
#    then runs without the probe and relies on the stuck-client rule);
# 2. copies gpu_watchdog.py -> $DIR/bin (it imports gpu_slot.py from there; install that with tools/gpu/install.sh);
# 3. renders ~/Library/LaunchAgents/com.ashen.gpu-watchdog.plist and reloads it (bootout, then bootstrap);
# 4. renders a LaunchDaemon variant to $DIR/com.ashen.gpu-watchdog.daemon.plist and PRINTS the sudo command
#    that swaps the agent for it (survives a GUI logout). It never runs sudo, never adds sudoers entries and
#    never creates REBOOT_OK: self-reboot stays off.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR=${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}
LABEL=com.ashen.gpu-watchdog
PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
DAEMON_SRC=$DIR/$LABEL.daemon.plist
mkdir -p "$DIR/bin" "$HOME/Library/LaunchAgents"

if command -v swiftc >/dev/null 2>&1; then
  if swiftc -O -o "$DIR/bin/metal_probe.new" "$HERE/metal_probe.swift"; then
    mv -f "$DIR/bin/metal_probe.new" "$DIR/bin/metal_probe"
    echo "metal_probe compiled -> $DIR/bin/metal_probe"
  else
    rm -f "$DIR/bin/metal_probe.new"
    echo "WARNING: swiftc failed; keeping any existing $DIR/bin/metal_probe (probe may be absent)" >&2
  fi
else
  echo "WARNING: swiftc not found; watchdog runs WITHOUT the Metal probe (stuck-client rule only)" >&2
fi
cp "$HERE/gpu_watchdog.py" "$DIR/bin/"; chmod +x "$DIR/bin/gpu_watchdog.py"
[ -f "$DIR/bin/gpu_slot.py" ] || echo "WARNING: $DIR/bin/gpu_slot.py missing (run tools/gpu/install.sh); client enumeration falls back to ps" >&2

render() { # $1 = agent|daemon
  python3 - "$HERE/$LABEL.plist.template" "$1" "$HOME" "$DIR" "$(id -un)" <<'PY'
import re, sys
tpl, mode, home, d, user = sys.argv[1:6]
s = open(tpl).read().replace("__HOME__", home).replace("__DIR__", d)
if mode == "daemon":
    s = re.sub(r"\s*<key>LimitLoadToSessionType</key><string>[^<]*</string>", "", s)
    s = s.replace("<key>Label</key><string>com.ashen.gpu-watchdog</string>",
                  "<key>Label</key><string>com.ashen.gpu-watchdog</string>\n  <key>UserName</key><string>%s</string>" % user)
sys.stdout.write(s)
PY
}
render agent > "$PLIST"; plutil -lint "$PLIST" >/dev/null
render daemon > "$DAEMON_SRC"; plutil -lint "$DAEMON_SRC" >/dev/null

# LimitLoadToSessionType=Background agents live in the user/<uid> domain (a gui/<uid> bootstrap rejects them).
UIDN=$(id -u)
if [ -f "/Library/LaunchDaemons/$LABEL.plist" ]; then
  echo "LaunchDaemon /Library/LaunchDaemons/$LABEL.plist present: updated $DIR/bin only, agent NOT loaded (one watchdog)."
  echo "restart it with: sudo launchctl kickstart -k system/$LABEL"
  exit 0
fi
launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
launchctl bootout "user/$UIDN/$LABEL" 2>/dev/null || true
launchctl bootstrap "user/$UIDN" "$PLIST"
echo "installed -> $DIR/bin/gpu_watchdog.py ; LaunchAgent $LABEL (user/$UIDN, RunAtLoad+KeepAlive, every 15 s)"
echo "log: $DIR/gpu_watchdog.log   state: $DIR/bin/gpu_watchdog.py status   self-reboot: OFF"
echo
echo "To survive a GUI logout, swap the agent for a LaunchDaemon (owner runs this; the installer does not):"
echo "  launchctl bootout user/$UIDN/$LABEL; rm -f '$PLIST'; sudo install -o root -g wheel -m 644 '$DAEMON_SRC' /Library/LaunchDaemons/$LABEL.plist && sudo launchctl bootstrap system /Library/LaunchDaemons/$LABEL.plist"
