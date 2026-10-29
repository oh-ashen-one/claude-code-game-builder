#!/bin/bash
# Self-contained test of gpu_watchdog.py. Touches no GPU state: the Metal probe is a fake script, ioreg is
# mocked (GPU_WATCHDOG_MOCK_IOREG_FILE), stuck clients are mocked (GPU_WATCHDOG_MOCK_STUCK_FILE), boottime is
# mocked, notifications go to a file (GPU_WATCHDOG_NOTIFY_CMD) or an osascript stub, and `sudo` is a stub that
# only records its argv. Everything lives in a private temp dir; the real ~/.cache/gpu-slot is never used.
#   tools/gpu/test_gpu_watchdog.sh [--keep]      exit 0 = all passed
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
WD="$HERE/gpu_watchdog.py"
KEEP=""; [ "${1:-}" = "--keep" ] && KEEP=1
T="$(mktemp -d "${TMPDIR:-/tmp}/gpuwd-test.XXXXXX")"
case "$T" in */gpuwd-test.*) ;; *) echo "bad test dir"; exit 1;; esac
REAL="$HOME/.cache/gpu-slot"
S="$T/state"; mkdir -p "$S/holders"
unset GPU_WATCHDOG_REBOOT GPU_SLOT_DIR GPU_SLOT_LOG
export GPU_LOCK_DIR="$S"
export GPU_WATCHDOG_INTERVAL=0.1 GPU_WATCHDOG_PROBE_TIMEOUT=0.3 GPU_WATCHDOG_STUCK_SECONDS=1
export GPU_WATCHDOG_PIN_SECONDS=0.5 GPU_WATCHDOG_RENOTIFY=2 GPU_WATCHDOG_REBOOT_GRACE=1
export GPU_WATCHDOG_MOCK_IOREG_FILE="$T/ioreg.txt" GPU_WATCHDOG_MOCK_STUCK_FILE="$T/stuck.txt"
export GPU_WATCHDOG_MOCK_BOOTTIME=1000
export GPU_WATCHDOG_NOTIFY_CMD="$T/notify.sh" GPU_WATCHDOG_SUDO="$T/sudo_stub" GPU_WATCHDOG_OSASCRIPT="$T/osascript_stub"

cat > "$T/probe_ok.sh" <<EOF
#!/bin/bash
echo launched >> "$T/probe.launches"
echo "ok 3"
EOF
cat > "$T/probe_hang.sh" <<EOF
#!/bin/bash
echo launched >> "$T/probe.launches"
sleep 30
EOF
cat > "$T/notify.sh" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >> "$T/notify.txt"
EOF
cat > "$T/sudo_stub" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >> "$T/sudo.calls"
EOF
cat > "$T/osascript_stub" <<EOF
#!/bin/bash
printf '%s\n----\n' "\$*" >> "$T/osascript.calls"
EOF
chmod +x "$T"/*.sh "$T/sudo_stub" "$T/osascript_stub"
ioreg_set() { printf '"PerformanceStatistics" = {"Device Utilization %%"=%s,"recoveryCount"=%s}\n' "$1" "$2" > "$T/ioreg.txt"; }
ioreg_set 5 0; : > "$T/stuck.txt"

PASS=0; FAIL=0
check() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); echo "  ok   $d"; else FAIL=$((FAIL+1)); echo "  FAIL $d"; fi; }
once() { GPU_WATCHDOG_PROBE="$T/probe_$1.sh" python3 "$WD" --once > "$T/last.json" 2>>"$T/stderr.txt"; }
ok() { once ok; }
hang() { once hang; }
st() { python3 -c "import json,sys;d=json.load(open('$S/gpu_watchdog.json'));print(eval(sys.argv[1]))" "$1"; }
paused_by() { python3 -c "import json;print(json.load(open('$S/PAUSED')).get('$1'))"; }
lines() { [ -f "$1" ] && wc -l < "$1" | tr -d ' ' || echo 0; }
alive() { kill -0 "$1" 2>/dev/null; }
gone_within() { local i; for ((i = 0; i < ${2:-30}; i++)); do alive "$1" || return 0; sleep 0.1; done; return 1; }
spawn_child() { python3 -c 'import subprocess,sys; print(subprocess.Popen([sys.executable,"-c","import time; time.sleep(300)"], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid)'; }
holder() { # class child_pid run_since_epoch
  printf '{"pid": %d, "class": "%s", "label": "test-%s", "child_pid": %d, "run_since_epoch": %s}\n' "$$" "$1" "$1" "$2" "$3" > "$S/holders/$1-$2.json"; }
reset() { rm -f "$S/gpu_watchdog.json" "$S/PAUSED" "$S/ALERT.txt" "$S/REBOOT_OK" "$T/notify.txt" "$T/sudo.calls"; unset GPU_WATCHDOG_REBOOT; ioreg_set 5 0; : > "$T/stuck.txt"; }
T0=$(date +%s)
REAL_BEFORE="$(ls -la "$REAL"/gpu_watchdog* "$REAL"/PAUSED "$REAL"/ALERT.txt "$REAL"/REBOOT_OK 2>&1 | md5)"

echo "1. healthy sample"
ok; RC=$?
check "healthy --once exits 0" test "$RC" = 0
check "no PAUSED after healthy sample" test ! -e "$S/PAUSED"
check "state JSON probe=ok" test "$(st 'd["probe"]["result"]')" = ok
check "sample line logged in key=value form" grep -q 'event=sample probe=ok probe_ms=3 util=5 recovery=0' "$S/gpu_watchdog.log"
check "status subcommand prints state" sh -c "python3 '$WD' status | grep -q gpu_watchdog/1"

echo "2. three probe hangs trip a wedge"
CAP=$(spawn_child); PERF=$(spawn_child); OLDCAP=$(spawn_child)
NOW=$(date +%s)
holder capture "$OLDCAP" $((NOW - 100)); holder capture "$CAP" "$NOW"; holder perf "$PERF" $((NOW + 5))
hang; R1=$?; hang; R2=$?
check "hang x1, x2 exit 0 (not tripped yet)" test "$R1$R2" = 00
check "no PAUSED before 3rd hang" test ! -e "$S/PAUSED"
check "strikes counted across --once runs" test "$(st 'd["hang_strikes"]')" = 2
hang; R3=$?
check "3rd hang exits 3 (tripped)" test "$R3" = 3
check "PAUSED written by gpu_watchdog" test "$(paused_by by)" = gpu_watchdog
check "PAUSED carries boottime" test "$(paused_by boottime)" = 1000
check "PAUSED has since/reason/details" python3 -c "import json;d=json.load(open('$S/PAUSED'));assert d['since'] and 'probe-hang' in d['reason'] and isinstance(d['details'],dict)"
check "newest capture child got SIGTERM and exited" gone_within "$CAP" 30
check "older capture child untouched" alive "$OLDCAP"
check "perf holder child never signalled" alive "$PERF"
check "sigterm logged" grep -q "action=sigterm-capture result=sent .*child_pid=$CAP target=group" "$S/gpu_watchdog.log"
check "notify cmd got the message" grep -q "GPU WEDGE" "$T/notify.txt"
check "exactly one notification" test "$(lines "$T/notify.txt")" = 1
check "ALERT.txt written" grep -q "GPU WEDGE" "$S/ALERT.txt"
check "reboot=disabled logged at trip" grep -q "event=reboot reboot=disabled" "$S/gpu_watchdog.log"
check "notification says self-reboot disabled" grep -q "Self-reboot disabled" "$T/notify.txt"

echo "3. re-notify rate limit"
hang; hang
check "no re-notify inside GPU_WATCHDOG_RENOTIFY" test "$(lines "$T/notify.txt")" = 1
check "trip actions not repeated (one sigterm)" test "$(grep -c 'action=sigterm-capture' "$S/gpu_watchdog.log")" = 1
sleep 2.1; hang
check "re-notify after GPU_WATCHDOG_RENOTIFY" test "$(lines "$T/notify.txt")" = 2
check "repeat notification is marked" grep -q "^\[repeat 1\]" "$T/notify.txt"

echo "4. flags off: never reboots"
check "grace elapsed and logged as would-reboot-if-enabled" grep -q "decision=would-reboot-now-if-enabled" "$S/gpu_watchdog.log"
check "sudo/shutdown never invoked" test ! -e "$T/sudo.calls"

echo "5. recovery keeps PAUSED"
ok; ok; R=$?
check "2 passes: still tripped" test "$R" = 3
ok; R=$?
check "3 passes: recovered, exit 0" test "$R" = 0
check "recovered logged" grep -q "event=recovered" "$S/gpu_watchdog.log"
check "PAUSED NOT removed (never auto-resume)" test -e "$S/PAUSED"
ok; ok; ok
check "PAUSED still present after more healthy samples (same boot)" test -e "$S/PAUSED"

echo "6. reboot needs BOTH opt-ins"
reset; export GPU_WATCHDOG_REBOOT=1
hang; hang; hang; sleep 1.2; hang; hang
check "env only (no REBOOT_OK): shutdown not called" test ! -e "$T/sudo.calls"
check "env only: logged why disabled" grep -q "why=REBOOT_OK-missing" "$S/gpu_watchdog.log"
reset; touch "$S/REBOOT_OK"
hang; hang; hang; sleep 1.2; hang
check "REBOOT_OK only (env unset): shutdown not called" test ! -e "$T/sudo.calls"
reset; export GPU_WATCHDOG_REBOOT=1; touch "$S/REBOOT_OK"
GPU_WATCHDOG_REBOOT_GRACE=2; export GPU_WATCHDOG_REBOOT_GRACE
hang; hang; hang
check "armed: first notification announces the reboot" grep -q "Self-reboot ARMED" "$T/notify.txt"
hang
check "armed: no reboot inside the grace period" test ! -e "$T/sudo.calls"
sleep 2.1; hang
check "armed + grace elapsed + probe hanging: sudo -n /sbin/shutdown -r now" grep -qx -- "-n /sbin/shutdown -r now" "$T/sudo.calls"
hang
check "reboot attempted only once per trip" test "$(lines "$T/sudo.calls")" = 1
reset; export GPU_WATCHDOG_REBOOT=1; touch "$S/REBOOT_OK"
hang; hang; hang; ioreg_set 5 1; sleep 2.1; hang; hang
check "armed but recoveryCount moved and no stuck client: no reboot" test ! -e "$T/sudo.calls"
reset; export GPU_WATCHDOG_REBOOT=1; touch "$S/REBOOT_OK"
hang; hang; hang; ok; sleep 2.1; ok
check "armed but probe passing again: no reboot" test ! -e "$T/sudo.calls"
GPU_WATCHDOG_REBOOT_GRACE=1; export GPU_WATCHDOG_REBOOT_GRACE

echo "7. stuck GPU client trips a wedge"
reset
echo "4242 E capture" > "$T/stuck.txt"
ok; R=$?
check "stuck client younger than STUCK_SECONDS: not tripped" test "$R" = 0
sleep 1.1; ok; R=$?
check "stuck client >= STUCK_SECONDS: tripped" test "$R" = 3
check "PAUSED reason names the stuck client" sh -c "python3 -c \"import json;print(json.load(open('$S/PAUSED'))['reason'])\" | grep -q 'stuck-client pid=4242 stat=E'"
ok; ok; R=$?
check "probe passing but client still stuck: stays tripped" test "$R" = 3
: > "$T/stuck.txt"; ok; ok; ok; R=$?
check "stuck client gone + 3 passes: recovered" test "$R" = 0
echo "4243 Z engine" > "$T/stuck.txt"; ok; sleep 1.1; ok; R=$?
check "zombie GPU client also counts as stuck" test "$R" = 3
: > "$T/stuck.txt"; ok; ok; ok

echo "8. PAUSED cleared only after a reboot"
check "precondition: our PAUSED from boot 1000 present" test "$(paused_by boottime)" = 1000
export GPU_WATCHDOG_MOCK_BOOTTIME=2000
ok; ok
check "new boot, 2 passes: PAUSED kept" test -e "$S/PAUSED"
check "new boot resets the trip state" test "$(st 'd["boottime"]')" = 2000
ok
check "new boot, 3 passes: PAUSED removed" test ! -e "$S/PAUSED"
check "paused-cleared-after-reboot logged" grep -q "event=paused-cleared-after-reboot paused_boot=1000 boot=2000" "$S/gpu_watchdog.log"
printf '{"since":"x","by":"owner","reason":"manual","boottime":1000}\n' > "$S/PAUSED"
ok; ok; ok; ok
check "owner's PAUSED from an old boot is never removed" grep -q '"owner"' "$S/PAUSED"
rm -f "$S/PAUSED"
export GPU_WATCHDOG_MOCK_BOOTTIME=1000

echo "9. unregistered load warning"
reset; rm -f "$S"/holders/*.json; ioreg_set 100 0
ok; sleep 0.6; ok; R=$?
check "pinned util with no holders: warn in state" test "$(st 'd["warn"]["type"]')" = unregistered-load
check "warn logged" grep -q "event=warn type=unregistered-load" "$S/gpu_watchdog.log"
check "warn does not trip or pause" sh -c "test $R = 0 && test ! -e '$S/PAUSED'"
NOW=$(date +%s); holder capture "$OLDCAP" "$NOW"; ok
check "warn clears once a holder exists" test "$(st 'd["warn"]')" = None

echo "10. stuck probe is never stacked"
reset; rm -f "$T/probe.launches"; STUCKP=$(spawn_child)
ok
python3 - "$S/gpu_watchdog.json" "$STUCKP" <<'PY'
import json, sys
p, pid = sys.argv[1], int(sys.argv[2])
d = json.load(open(p)); d["stuck_probe_pids"] = [pid]; json.dump(d, open(p, "w"))
PY
rm -f "$T/probe.launches"; ok
check "earlier probe still alive: sample is a hang" test "$(st 'd["probe"]["result"]')" = hang
check "earlier probe still alive: no new probe launched" test ! -e "$T/probe.launches"
check "why=previous-probe-alive recorded" sh -c "grep -q 'previous-probe-alive:$STUCKP' '$S/gpu_watchdog.json'"
kill "$STUCKP" 2>/dev/null; gone_within "$STUCKP" 30; rm -f "$T/probe.launches"; hang
check "once that probe is gone, probing resumes" test -e "$T/probe.launches"

echo "11. iMessage path (osascript stub, nothing sent)"
reset; rm -f "$T/osascript.calls"; NC="$GPU_WATCHDOG_NOTIFY_CMD"; unset GPU_WATCHDOG_NOTIFY_CMD
hang; hang; hang
check "osascript called with the clipfarm AppleScript pattern" grep -q 'set svc to 1st account whose service type = iMessage' "$T/osascript.calls"
check "default recipient 7088608874" grep -q 'to participant "7088608874" of svc' "$T/osascript.calls"
check "notify logged as sent" grep -q "action=notify result=imessage-sent" "$S/gpu_watchdog.log"
printf '#!/bin/bash\nexit 1\n' > "$T/osascript_fail"; chmod +x "$T/osascript_fail"
reset; GPU_WATCHDOG_OSASCRIPT="$T/osascript_fail" bash -c "for i in 1 2 3; do GPU_WATCHDOG_PROBE='$T/probe_hang.sh' python3 '$WD' --once >/dev/null 2>&1; done; exit 0"
check "notification failure is logged, not fatal (PAUSED still written)" sh -c "grep -q 'result=imessage-failed' '$S/gpu_watchdog.log' && test -e '$S/PAUSED'"
export GPU_WATCHDOG_NOTIFY_CMD="$NC"

echo "12. dry-run writes and sends nothing"
reset; NOW=$(date +%s); CAP2=$(spawn_child); holder capture "$CAP2" "$NOW"
rm -f "$S/gpu_watchdog.log"; BEFORE="$(ls -lR "$S"; cat "$S"/holders/*.json)"
GPU_WATCHDOG_PROBE="$T/probe_hang.sh" python3 "$WD" --once --dry-run > "$T/dry_once.json" 2>"$T/dry_once.err"; R=$?
check "--once --dry-run exit 0 after one hang" test "$R" = 0
check "--once --dry-run prints state JSON" python3 -c "import json;json.load(open('$T/dry_once.json'))"
check "--once --dry-run wrote nothing to the dir" test "$BEFORE" = "$(ls -lR "$S"; cat "$S"/holders/*.json)"
GPU_WATCHDOG_PROBE="$T/probe_hang.sh" python3 "$WD" --dry-run 2>"$T/dry_loop.err" & DL=$!
for i in $(seq 1 60); do grep -q "action=notify result=would-send" "$T/dry_loop.err" 2>/dev/null && break; sleep 0.1; done
kill -TERM "$DL"; wait "$DL"; R=$?
check "dry-run loop logs would-write PAUSED" grep -q "action=paused result=would-write" "$T/dry_loop.err"
check "dry-run loop logs would-send SIGTERM" grep -q "action=sigterm-capture result=would-send" "$T/dry_loop.err"
check "dry-run loop logs would-send notify" grep -q "action=notify result=would-send" "$T/dry_loop.err"
check "dry-run loop: no PAUSED/state/log/ALERT written" sh -c "test ! -e '$S/PAUSED' -a ! -e '$S/gpu_watchdog.json' -a ! -e '$S/gpu_watchdog.log' -a ! -e '$S/ALERT.txt'"
check "dry-run loop: capture child not signalled" alive "$CAP2"
check "dry-run loop: nothing notified" test ! -e "$T/notify.txt"
check "dry-run loop exits 0 on SIGTERM" test "$R" = 0

echo "13. loop mode trips and exits cleanly on SIGTERM"
reset
GPU_WATCHDOG_PROBE="$T/probe_hang.sh" python3 "$WD" 2>"$T/loop.err" & LP=$!
for i in $(seq 1 60); do [ -e "$S/PAUSED" ] && break; sleep 0.1; done
check "loop wrote PAUSED after 3 hangs" test "$(paused_by by)" = gpu_watchdog
check "loop SIGTERMed the capture holder child" gone_within "$CAP2" 30
kill -TERM "$LP"; wait "$LP"; R=$?
check "loop exits 0 on SIGTERM" test "$R" = 0
check "loop logged stop" grep -q "event=stop" "$S/gpu_watchdog.log"
check "loop never stacked probes (no leftover probe_hang)" sh -c "! pgrep -f '$T/probe_hang.sh'"

kill "$PERF" "$OLDCAP" "$CAP" "$CAP2" "$STUCKP" 2>/dev/null
check "real state dir untouched" test "$REAL_BEFORE" = "$(ls -la "$REAL"/gpu_watchdog* "$REAL"/PAUSED "$REAL"/ALERT.txt "$REAL"/REBOOT_OK 2>&1 | md5)"
echo
echo "gpu_watchdog tests: $PASS passed, $FAIL failed in $(( $(date +%s) - T0 )) s   (dir $T)"
[ -z "$KEEP" ] && [ "$FAIL" = 0 ] && rm -rf "$T"
[ "$FAIL" = 0 ]
