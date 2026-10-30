#!/bin/bash
# Homage fan game tooling. Not an official Marvel, Sony or Insomniac project; no affiliation.
# Self-contained test of gpu_slot.sh. Starts NO Unreal instance: "Unreal capture processes" are faked
# with a tagged python sleeper, GPU utilization is mocked through GPU_SLOT_MOCK_UTIL_FILE, and the
# lock state lives in a private dir, so the real state in ${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot} is untouched.
#   tools/gpu/test_gpu_slot.sh [--save <dir>]      exit 0 = all passed
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
GS="$HERE/gpu_slot.sh"
SAVE=""
[ "${1:-}" = "--save" ] && SAVE="$2"
TOKEN="GPUSLOTTEST$$_$RANDOM"
T="${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/test-$TOKEN"
case "$T" in ${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/test-GPUSLOTTEST*) ;; *) echo "bad test dir"; exit 1;; esac
mkdir -p "$T"
export GPU_SLOT_DIR="$T/state" GPU_SLOT_LOG="$T/gpu_slot.log" GPU_SLOT_QUIET=1
export GPU_SLOT_POLL=0.1 GPU_SLOT_CALM_SECONDS=1.0 GPU_SLOT_SAMPLE_INTERVAL=0.2 GPU_SLOT_WAIT_LOG_EVERY=1
export GPU_SLOT_MOCK_UTIL_FILE="$T/util"
export GPU_SLOT_UNREAL_PATTERN="FAKEUE_$TOKEN" GPU_SLOT_CAPTURE_PATTERN='-game'
export GPU_SLOT_LABEL=test
# isolation from the live machine: only processes carrying this run's token can count as GPU clients
export GPU_SLOT_GPU_IGNORE_PATTERN="^(?!.*$TOKEN)"
# capture launch gate at test speed (defaults: util < 85 for 10 s, 20 s cooldown, 180 s settle budget)
export GPU_SLOT_CAPTURE_CALM_SECONDS=0.2 GPU_SLOT_LAUNCH_COOLDOWN=0.01 GPU_SLOT_CAPTURE_SETTLE_TIMEOUT=30
unset GPU_SLOT_HELD GPU_SLOT_JSON GPU_SLOT_MOCK_STUCK_FILE GPU_SLOT_ML_PATTERN GPU_SLOT_GPU_PATTERN
unset GPU_SLOT_CAPTURE_UTIL_MAX GPU_SLOT_CAPTURE_SLOTS GPU_SLOT_WATCHDOG_STALE_S
# GPU watchdog tripwire reads a private fake (never the live gpu_watchdog.json)
export GPU_SLOT_WATCHDOG_JSON="$T/wd.json"
wd() {  # wd healthy | warn | strike | stuck | trip | old   (updated = now, or 600 s ago for old)
  python3 - "$GPU_SLOT_WATCHDOG_JSON" "$1" <<'PY'
import datetime, json, sys
p, m = sys.argv[1], sys.argv[2]
now = datetime.datetime.now().astimezone()
d = {"schema": "gpu_watchdog/1", "hang_strikes": 0, "stuck_since": {}, "warn": None, "trip": None, "last_trip": None,
     "tripped": False, "updated": (now - datetime.timedelta(seconds=600 if m == "old" else 0)).isoformat(timespec="milliseconds")}
if m == "warn": d["warn"] = {"type": "unregistered-load", "util": 99}
if m == "strike": d["hang_strikes"] = 1
if m == "stuck": d["stuck_since"] = {"4242": 1793300000}
if m == "trip": d.update(trip={"type": "wedge", "reason": "probe-hang x3"}, tripped=True)
json.dump(d, open(p, "w"))
PY
}
wd healthy
# sections (a)-(i) test the lock mechanics at the pre-2026-10-29 cap of 2; (j) tests the default 3 + tripwire clamp
export GPU_SLOT_CAPTURE_SLOTS=2

cat > "$T/job.py" <<'PY'
import sys, time
d, name, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
rc = int(sys.argv[4]) if len(sys.argv) > 4 else 0
open("%s/%s.start" % (d, name), "w").write("%.3f" % time.time())
time.sleep(secs)
open("%s/%s.end" % (d, name), "w").write("%.3f" % time.time())
sys.exit(rc)
PY
JOB="python3 $T/job.py $T"
setutil() { echo "$1" > "$T/util"; }
now() { python3 -c 'import time;print("%.3f"%time.time())'; }
waitf() { local i; for ((i = 0; i < ${2:-15} * 20; i++)); do [ -e "$1" ] && return 0; sleep 0.05; done; return 1; }
val() { cat "$T/$1" 2>/dev/null || echo 0; }
ge() { python3 -c "import sys;sys.exit(0 if float('$1') >= float('$2') else 1)"; }
fake_ue() { python3 -c 'import time,sys;time.sleep(float(sys.argv[1]))' "$1" "FAKEUE_$TOKEN" -game & FAKE_PID=$!; }
PASS=0; FAIL=0
check() { # desc, then a command that must succeed
  local d="$1"; shift
  if "$@"; then PASS=$((PASS + 1)); echo "  PASS  $d"; else FAIL=$((FAIL + 1)); echo "  FAIL  $d"; fi
}
cleanup() {
  pkill -9 -f "$TOKEN" 2>/dev/null
  wait 2>/dev/null
  if [ -n "$SAVE" ]; then
    mkdir -p "$SAVE"; cp "$GPU_SLOT_LOG" "$SAVE/gpu_slot.test.log" 2>/dev/null
    cp "$GPU_SLOT_DIR/runs.jsonl" "$SAVE/runs.test.jsonl" 2>/dev/null
    cp "$T/perf_b.json" "$SAVE/perf_result_example.json" 2>/dev/null
  fi
  case "$T" in ${GPU_LOCK_DIR:-$HOME/.cache/gpu-slot}/test-GPUSLOTTEST*) rm -rf "$T";; esac
}
trap cleanup EXIT

echo "== (a) two captures overlap, a third waits =="
setutil 50   # capture slots must not care about utilization
$GS capture --label A -- $JOB A 2.5 & PA=$!
$GS capture --label B -- $JOB B 2.5 & PB=$!
waitf "$T/A.start"; waitf "$T/B.start"
sleep 0.3
$GS capture --label C -- $JOB C 0.4 & PC=$!
sleep 0.8
check "third capture has NOT started while both slots are held" test ! -e "$T/C.start"
wait $PA $PB $PC
check "A and B overlapped (each started before the other ended)" \
  python3 -c "import sys;sys.exit(0 if $(val B.start) < $(val A.end) and $(val A.start) < $(val B.end) else 1)"
check "C started only after a slot was released (>= first end - 0.05)" \
  ge "$(val C.start)" "$(python3 -c "print(min($(val A.end),$(val B.end)) - 0.05)")"
check "at most 2 captures ran at once" python3 - "$T" <<'PY'
import sys
d = sys.argv[1]
iv = []
for n in "ABC":
    iv.append((float(open("%s/%s.start" % (d, n)).read()), float(open("%s/%s.end" % (d, n)).read())))
ev = sorted([(s, 1) for s, e in iv] + [(e, -1) for s, e in iv])
cur = mx = 0
for t, dlt in ev:
    cur += dlt; mx = max(mx, cur)
sys.exit(0 if mx <= 2 else 1)
PY
check "log has acquire/release/wait lines with utilization" \
  bash -c "grep -q 'event=wait' '$GPU_SLOT_LOG' && grep -q 'event=acquire' '$GPU_SLOT_LOG' && grep -q 'event=release' '$GPU_SLOT_LOG' && grep -q 'util=50' '$GPU_SLOT_LOG'"
$GS capture -- sh -c 'exit 7'; check "exit code of the command is propagated (capture, 7)" test $? -eq 7

echo "== (b) perf: exclusive, waits for captures + fake capture process + utilization < threshold for CALM =="
setutil 50
fake_ue 3.0; FAKE=$FAKE_PID
$GS capture --label A2 -- $JOB A2 1.5 & P1=$!
$GS capture --label B2 -- $JOB B2 1.5 & P2=$!
waitf "$T/A2.start"; waitf "$T/B2.start"
$GS perf --label P --json "$T/perf_b.json" -- $JOB P 0.6 & PP=$!
sleep 0.3
$GS capture --label D -- $JOB D 0.3 & PD=$!          # queued after perf: must wait for it
waitf "$T/A2.end"; waitf "$T/B2.end"
sleep 0.3
check "perf not started while the fake -game process is still alive" test ! -e "$T/P.start"
while kill -0 $FAKE 2>/dev/null; do sleep 0.05; done
T_FAKE_END="$(now)"
sleep 1.5
check "perf still waiting after captures + fake process ended because util=50 >= 15" test ! -e "$T/P.start"
setutil 5; T_LOW1="$(now)"
sleep 0.5
setutil 40                      # blip shorter than CALM total: streak must reset
sleep 0.6
check "perf did not start on the interrupted low-util streak" test ! -e "$T/P.start"
setutil 5; T_LOW2="$(now)"
waitf "$T/P.start" 10
check "perf start >= end of A2/B2/fake process" \
  ge "$(val P.start)" "$(python3 -c "print(max($(val A2.end),$(val B2.end),$T_FAKE_END) - 0.05)")"
check "perf start >= (last low-util onset + CALM 1.0 s) - 0.1" \
  ge "$(val P.start)" "$(python3 -c "print($T_LOW2 + 1.0 - 0.1)")"
wait $PP $PD $P1 $P2 2>/dev/null
check "capture queued after perf ran only after perf finished (exclusive)" \
  ge "$(val D.start)" "$(python3 -c "print($(val P.end) - 0.05)")"
check "perf sidecar json: exclusive, not contaminated, util_before < 15, wait/instances recorded" python3 - "$T/perf_b.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
ok = (r["class"] == "perf" and r["exclusive"] is True and r["contaminated"] is False and r["perf_valid"] is True
      and r["util_before"] < 15 and r["wait_s"] > 3 and "instances_before" in r and "instances_max_during" in r
      and r["util_during"]["n"] >= 1 and r["exit_code"] == 0 and r["settle"]["samples"] >= 5)
print("   ", {k: r[k] for k in ("wait_s", "util_before", "util_after", "instances_before", "instances_max_during", "contaminated")})
sys.exit(0 if ok else 1)
PY

echo "-- (b2) foreign capture process alone blocks perf even at low util"
setutil 5
fake_ue 2.0; FAKE=$FAKE_PID
$GS perf --label P2 -- $JOB PF 0.2 & PP=$!
while kill -0 $FAKE 2>/dev/null; do sleep 0.05; done
T_FAKE_END="$(now)"
wait $PP
check "perf start >= fake process end + CALM(1.0) - 0.1" \
  ge "$(val PF.start)" "$(python3 -c "print($T_FAKE_END + 1.0 - 0.1)")"

echo "-- (b3) foreign capture appearing DURING a perf run marks the result contaminated"
# a stranger = not a descendant of the perf wrapper
setutil 5
$GS perf --label P3 --json "$T/perf_b3.json" -- $JOB P3 1.5 & PP=$!
waitf "$T/P3.start"; fake_ue 1.0; wait $PP; wait $FAKE_PID 2>/dev/null
check "stranger capture process during perf => contaminated, perf_valid=false" python3 - "$T/perf_b3.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
sys.exit(0 if r["contaminated"] and not r["perf_valid"] and "foreign-capture-process-during-run" in r["contaminated_reasons"] else 1)
PY

echo "-- (b4) max hold kills the command (exit 124), wait timeout does not run it (exit 75), exit codes"
setutil 5
GPU_SLOT_PERF_MAX_HOLD=1.2 $GS perf --json "$T/perf_b4.json" -- $JOB HOLD 30; RC=$?
check "perf max hold exceeded => exit 124 and command was killed early" test $RC -eq 124 -a ! -e "$T/HOLD.end"
check "  ... result json flags max-hold + contaminated" python3 - "$T/perf_b4.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1])); sys.exit(0 if r["outcome"] == "max-hold-killed" and r["contaminated"] else 1)
PY
setutil 60
$GS perf --timeout 1.5 -- $JOB NOTRUN 0.1; RC=$?
check "perf wait timeout (util 60) => exit 75 and command NOT run" test $RC -eq 75 -a ! -e "$T/NOTRUN.start"
setutil 5
$GS perf -- sh -c 'exit 3'; RC=$?; check "perf exit code propagated (3)" test $RC -eq 3
$GS capture -- /nonexistent/cmd_$TOKEN; RC=$?; check "command not found => 127" test $RC -eq 127
$GS capture -- $GS capture --label inner -- $JOB NEST 0.1; RC=$?
check "nested capture inside a held capture passes through (no deadlock), exit 0" test $RC -eq 0 -a -e "$T/NEST.end"
$GS capture -- $GS perf -- true 2>/dev/null; RC=$?
check "perf nested inside a capture slot is refused (exit 2) instead of deadlocking" test $RC -eq 2

echo "== (c) stale lock recovery =="
setutil 50
echo "-- (c1) both capture holders killed -9: slots free again, stale records recovered"
$GS capture --label H1 -- $JOB H1 60 & W1=$!
$GS capture --label H2 -- $JOB H2 60 & W2=$!
waitf "$T/H1.start"; waitf "$T/H2.start"
"$HERE/gpu_status.sh" | grep -E 'Capture slots|Holders' | sed 's/^/     before kill: /'
kill -9 $W1 $W2; wait $W1 $W2 2>/dev/null
T0="$(now)"
$GS capture --label X -- $JOB X 0.2; RC=$?
T1="$(val X.start)"
check "new capture acquires immediately after holders were killed (start - kill < 2 s), exit 0" \
  python3 -c "import sys;sys.exit(0 if $RC == 0 and float('$T1') - float('$T0') < 2.0 else 1)"
check "log records 'stale-recovered' for both dead holders" \
  test "$(grep -c 'event=stale-recovered.*kind=holder' "$GPU_SLOT_LOG")" -ge 2
check "status shows no live holders after recovery" bash -c "'$HERE/gpu_status.sh' | grep -q 'Holders (0)'"
pkill -9 -f "$T/job.py $T H[12]" 2>/dev/null     # orphaned children of the killed wrappers (ours, tagged by test dir)

echo "-- (c2) dead waiter at the head of the queue does not block the next waiter"
$GS capture --label F1 -- $JOB F1 60 & W1=$!
$GS capture --label F2 -- $JOB F2 60 & W2=$!
waitf "$T/F1.start"; waitf "$T/F2.start"
$GS capture --label Q1 -- $JOB Q1 0.2 & QW1=$!
sleep 0.4
$GS capture --label Q2 -- $JOB Q2 0.2 & QW2=$!
sleep 0.4
kill -9 $QW1; wait $QW1 2>/dev/null
kill -TERM $W1; wait $W1 2>/dev/null           # frees a slot; Q2 is behind the dead Q1
waitf "$T/Q2.end" 8
check "Q2 ran although dead Q1 was ahead of it (waiter record recovered)" test -e "$T/Q2.end" -a ! -e "$T/Q1.start"
check "log records 'stale-recovered' kind=waiter" grep -q 'event=stale-recovered.*kind=waiter' "$GPU_SLOT_LOG"
kill -TERM $W2 2>/dev/null; wait $W2 2>/dev/null; pkill -9 -f "$T/job.py $T F[12]" 2>/dev/null

echo "-- (c3) perf holder killed -9 while settling: perf.lock is freed by the kernel"
setutil 50
$GS perf --label PS -- $JOB PS 5 & PSW=$!
sleep 0.8
"$HERE/gpu_status.sh" | grep -E 'Perf lock' | sed 's/^/     before kill: /'
check "perf holder is in settling state (holding the lock, waiting for calm)" bash -c "'$HERE/gpu_status.sh' | grep -q 'Perf lock:.*HELD.*state=settling'"
kill -9 $PSW; wait $PSW 2>/dev/null
T0="$(now)"
$GS capture --label Y -- $JOB Y 0.2; RC=$?
check "capture runs promptly after perf holder died (< 2 s), and the dead perf never ran its command" \
  python3 -c "import sys,os;sys.exit(0 if $RC == 0 and float('$(val Y.start)') - float('$T0') < 2.0 and not os.path.exists('$T/PS.start') else 1)"
check "log records 'stale-recovered' for the dead perf holder" grep -q 'event=stale-recovered.*dead_class=perf' "$GPU_SLOT_LOG"

echo "-- (c4) PID-reuse defence: a live PID with the wrong start time is treated as stale"
python3 - "$GPU_SLOT_DIR/queue" $$ <<'PY'
import json, sys
d, pid = sys.argv[1], int(sys.argv[2])
json.dump({"pid": pid, "start": "Mon Jan  1 00:00:00 1990", "class": "perf", "label": "impostor",
           "since": "x", "since_epoch": 0, "ticket": "00000000000000000001-%d" % pid, "cmd": "x"},
          open("%s/00000000000000000001-%d.json" % (d, pid), "w"))
PY
$GS capture --label Z -- $JOB Z 0.1; RC=$?
check "capture not blocked by a queue record whose PID was reused (start time differs)" test $RC -eq 0 -a -e "$T/Z.end"
check "  ... and it was logged as stale-recovered dead_label=impostor" grep -q 'stale-recovered.*dead_label=impostor' "$GPU_SLOT_LOG"

echo "== (h) frame cap injection + STREAMING flag =="
setutil 5
mkdir -p "$T/Fake.app/Contents/MacOS" "$T/Fake.app/Contents/Resources" "$T/UE/Binaries/Mac"
touch "$T/Fake.app/Contents/Resources/game.pck"
cat > "$T/Fake.app/Contents/MacOS/game" <<SH
#!/bin/bash
echo "\$@" > "$T/godot.args"; echo "cap=\$GPU_SLOT_FPS_CAP streaming=\$GPU_SLOT_STREAMING" > "$T/godot.env"
SH
cp "$T/Fake.app/Contents/MacOS/game" "$T/UE/Binaries/Mac/FakeGame"
sed -i '' "s|godot\.|ue.|g" "$T/UE/Binaries/Mac/FakeGame"
chmod +x "$T/Fake.app/Contents/MacOS/game" "$T/UE/Binaries/Mac/FakeGame"
rm -f "$GPU_SLOT_DIR/STREAMING"
$GS capture --label G -- "$T/Fake.app/Contents/MacOS/game" --foo >/dev/null 2>&1
check "godot launch gets --max-fps 60 appended (default cap)" grep -q -- '--foo --max-fps 60' "$T/godot.args"
check "child sees GPU_SLOT_FPS_CAP=60 streaming=0" grep -q 'cap=60 streaming=0' "$T/godot.env"
$GS capture --label U -- "$T/UE/Binaries/Mac/FakeGame" -game -dpcvars=r.ScreenPercentage=50 >/dev/null 2>&1
check "unreal launch merges t.MaxFPS=60 into existing -dpcvars" grep -q -- '-dpcvars=r.ScreenPercentage=50,t.MaxFPS=60' "$T/ue.args"
$GS capture --label G2 -- "$T/Fake.app/Contents/MacOS/game" --max-fps 120 >/dev/null 2>&1
check "an explicit --max-fps is left alone" bash -c "grep -q -- '--max-fps 120' '$T/godot.args' && ! grep -q -- '--max-fps 60' '$T/godot.args'"
GPU_SLOT_FPS_CAP=0 $GS capture --label G3 -- "$T/Fake.app/Contents/MacOS/game" --bar >/dev/null 2>&1
check "GPU_SLOT_FPS_CAP=0 injects nothing" bash -c "! grep -q -- '--max-fps' '$T/godot.args'"
echo '{"mode":"test"}' > "$GPU_SLOT_DIR/STREAMING"
GPU_SLOT_STREAMING_SLOTS=1 $GS capture --label GS -- "$T/Fake.app/Contents/MacOS/game" >/dev/null 2>&1
check "while STREAMING flag exists the cap is 30 (explicit 1-slot exception)" grep -q -- '--max-fps 30' "$T/godot.args"
check "child sees streaming=1" grep -q 'streaming=1' "$T/godot.env"
check "status reports the STREAMING flag with 0 slots" bash -c "'$HERE/gpu_status.sh' | grep -q 'STREAMING flag set -> 0 slot'"
$GS capture --label SW -- $JOB SW 0.3 & PSW=$!
sleep 1.2
check "a capture does NOT start at all while streaming (0 slots): it waits" test ! -e "$T/SW.start"
check "the waiter logs streaming=true" grep -q 'event=wait.*streaming=true' "$GPU_SLOT_LOG"
rm -f "$GPU_SLOT_DIR/STREAMING"
wait $PSW; RC=$?
check "the waiting capture runs as soon as the flag is removed, exit 0" test $RC -eq 0 -a -e "$T/SW.end"
check "capture result JSON records the applied cap and the streaming state" bash -c "grep -q '\"fps_cap_engine\": \"godot\".*\"fps_cap_applied\": true' '$GPU_SLOT_DIR/runs.jsonl' && grep -q '\"streaming\": true, \"fps_cap\": 30' '$GPU_SLOT_DIR/runs.jsonl'"

echo "== (i) GPU client cap, capture util gate, cooldown, PAUSED, stuck engines =="
fake_gpu() { python3 -c 'import time,sys;time.sleep(float(sys.argv[1]))' "$1" "$2_$TOKEN" & FAKE_PID=$!; }
export GPU_SLOT_ML_PATTERN="FAKEML_$TOKEN" GPU_SLOT_GPU_PATTERN="FAKEGPU_$TOKEN"
setutil 20
echo "-- (i1) two foreign GPU clients (ml + other) hold a capture at cap-full; it runs when one exits"
fake_gpu 60 FAKEML; ML=$FAKE_PID
fake_gpu 60 FAKEGPU; OG=$FAKE_PID
sleep 0.3
check "status --json classifies the fake trainer as ml and the pattern client as other" python3 - "$HERE" "$ML" "$OG" <<'PY'
import json, subprocess, sys
here, ml, og = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
s = json.loads(subprocess.run([here + "/gpu_status.sh", "--json"], capture_output=True, text=True).stdout)
k = {c["pid"]: c["kind"] for c in s["gpu_clients"]}
print("    ", k, s["gpu_clients_by_kind"])
sys.exit(0 if k.get(ml) == "ml" and k.get(og) == "other" and s["gpu_client_cap"] == 2 else 1)
PY
$GS capture --label CF --json "$T/cf.json" -- sh -c 'echo "$GPU_SLOT_INSTANCES_BEFORE" > "$0/cf.inst"; exec '"$JOB"' CF 0.2' "$T" & PCF=$!
sleep 1.2
check "capture does NOT launch while 2 foreign GPU clients run (cap 2)" test ! -e "$T/CF.start"
check "log: wait phase=cap-full clients=<pid:kind,...> naming both" \
  bash -c "grep 'label=CF' '$GPU_SLOT_LOG' | grep 'event=wait' | grep 'phase=cap-full' | grep -q 'clients=.*$ML:ml.*$OG:other'"
check "status shows the waiting capture holding its slot in state gating" bash -c "'$HERE/gpu_status.sh' | grep -q 'label=CF.*state=gating'"
kill $ML; wait $ML 2>/dev/null; T_ML_END="$(now)"
wait $PCF; RC=$?
check "capture runs once one foreign client exits (exit 0, start >= exit time)" \
  bash -c "test $RC -eq 0 && python3 -c 'import sys;sys.exit(0 if $(val CF.start) >= $T_ML_END - 0.05 else 1)'"
check "GPU_SLOT_INSTANCES_BEFORE = total GPU clients (1 foreign left)" test "$(val cf.inst)" = 1
check "result json: gpu_clients_before total+by_kind, gpu_clients_max_during" python3 - "$T/cf.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
g = r["gpu_clients_before"]
print("    ", g, "max_during=%s" % r["gpu_clients_max_during"])
sys.exit(0 if g["total"] == 1 and g["by_kind"] == {"other": 1} and r["gpu_clients_max_during"] >= 1 else 1)
PY
check "release log line carries gpu_clients_before / by_kind / max_during" \
  bash -c "grep 'label=CF' '$GPU_SLOT_LOG' | grep 'event=release' | grep -q 'gpu_clients_before=1 .*gpu_clients_by_kind=other:1 .*gpu_clients_max_during='"
fake_gpu 60 FAKEML; ML=$FAKE_PID
GPU_SLOT_CAPTURE_SLOTS=1 $GS capture --label CF3 --timeout 1.0 --json "$T/cf3.json" -- $JOB CF3 0.1; RC=$?
check "cap-full past the wait timeout => exit 75, outcome cap-full-timeout, command not run" \
  bash -c "test $RC -eq 75 -a ! -e '$T/CF3.start' && grep -q '\"outcome\": \"cap-full-timeout\"' '$T/cf3.json'"
kill $ML $OG 2>/dev/null; wait $ML $OG 2>/dev/null

echo "-- (i2) capture util gate: util 100 holds the slot without running, util 20 lets it run"
setutil 100
$GS capture --label UB -- $JOB UB 0.2 & PUB=$!
sleep 1.2
check "capture at util 100 has NOT started" test ! -e "$T/UB.start"
check "log: wait phase=settle with util=100" bash -c "grep 'label=UB' '$GPU_SLOT_LOG' | grep 'event=wait' | grep 'phase=settle' | grep -q 'util=100'"
setutil 20; T_LOW="$(now)"
wait $PUB; RC=$?
check "capture runs after util drops (exit 0, start >= drop + calm 0.2 - 0.05)" \
  bash -c "test $RC -eq 0 && python3 -c 'import sys;sys.exit(0 if $(val UB.start) >= $T_LOW + 0.15 else 1)'"

echo "-- (i3) settle budget expires: exit 75, skipped-busy, command never started"
setutil 100
GPU_SLOT_CAPTURE_SETTLE_TIMEOUT=1 $GS capture --label ST --json "$T/st.json" -- $JOB ST 0.1; RC=$?
check "settle timeout => exit 75 and the command was never started" test $RC -eq 75 -a ! -e "$T/ST.start"
check "  ... outcome skipped-busy, contaminated, log has settle-timeout" bash -c "python3 -c \"import json,sys;r=json.load(open('$T/st.json'));sys.exit(0 if r['outcome']=='skipped-busy' and r['contaminated'] and r['exit_code']==75 else 1)\" && grep 'label=ST' '$GPU_SLOT_LOG' | grep -q 'event=settle-timeout'"
setutil 20

echo "-- (i4) launch cooldown after a release"
GPU_SLOT_LAUNCH_COOLDOWN=0.01 $GS capture --label CD1 -- $JOB CD1 0.1
REL="$(cat "$GPU_SLOT_DIR/last_release")"
GPU_SLOT_LAUNCH_COOLDOWN=1.5 $GS capture --label CD2 -- $JOB CD2 0.1; RC=$?
check "last_release written at release (>= end of CD1)" ge "$REL" "$(python3 -c "print($(val CD1.end) - 0.05)")"
check "next capture launched >= last release + cooldown 1.5 s" \
  bash -c "test $RC -eq 0 && python3 -c 'import sys;sys.exit(0 if $(val CD2.start) >= $REL + 1.5 - 0.05 else 1)'"
check "log: settle wait reports cooldown_left_s" bash -c "grep 'label=CD2' '$GPU_SLOT_LOG' | grep 'phase=settle' | grep -q 'cooldown_left_s=1'"

echo "-- (i5) PAUSED switch: pause blocks every class, resume unblocks"
$GS pause test pause from $TOKEN >/dev/null
check "PAUSED JSON has since/by/reason/boottime" python3 - "$GPU_SLOT_DIR/PAUSED" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
print("    ", {k: r.get(k) for k in ("since", "by", "reason", "boottime")})
sys.exit(0 if isinstance(r["since"], float) and r["by"] and r["reason"].startswith("test pause") and isinstance(r["boottime"], int) else 1)
PY
check "status shows PAUSED and its reason" bash -c "'$HERE/gpu_status.sh' | grep -q 'PAUSED:  *YES.*reason=\"test pause'"
$GS capture --label PZ -- $JOB PZ 0.1 & PPZ=$!
sleep 1.0
check "capture does not run while PAUSED" test ! -e "$T/PZ.start"
check "log: event=paused reason=..." bash -c "grep 'label=PZ' '$GPU_SLOT_LOG' | grep 'event=paused' | grep -q 'reason=\"test pause'"
$GS perf --label PZP --timeout 0.8 --json "$T/pzp.json" -- $JOB PZP 0.1; RC=$?
check "perf while PAUSED => exit 75, outcome paused, not run" \
  bash -c "test $RC -eq 75 -a ! -e '$T/PZP.start' && grep -q '\"outcome\": \"paused\"' '$T/pzp.json'"
$GS resume >/dev/null
wait $PPZ; RC=$?
check "resume unblocks the waiting capture (exit 0) and logs event=resume" \
  bash -c "test $RC -eq 0 -a -e '$T/PZ.end' -a ! -e '$GPU_SLOT_DIR/PAUSED' && grep -q 'event=resume' '$GPU_SLOT_LOG'"

echo "-- (i6) stuck engine (state E) blocks acquisition"
echo "99999 E unreal-editor" > "$T/stuck"
GPU_SLOT_MOCK_STUCK_FILE="$T/stuck" $GS capture --label SK --timeout 1.0 --json "$T/sk.json" -- $JOB SK 0.1; RC=$?
check "stuck engine => exit 75, outcome stuck-engine, not run" \
  bash -c "test $RC -eq 75 -a ! -e '$T/SK.start' && grep -q '\"outcome\": \"stuck-engine\"' '$T/sk.json'"
check "log: stuck-engine pid=99999 stat=E kind=unreal-editor" \
  bash -c "grep 'label=SK' '$GPU_SLOT_LOG' | grep 'event=stuck-engine' | grep -q 'pid=99999 stat=E kind=unreal-editor'"
GPU_SLOT_MOCK_STUCK_FILE="$T/stuck" $GS capture --label SK2 -- $JOB SK2 0.1 & PSK=$!
sleep 0.8
check "capture keeps waiting while the engine is stuck" test ! -e "$T/SK2.start"
rm -f "$T/stuck"
wait $PSK; RC=$?
check "capture runs once the stuck engine is gone (exit 0)" test $RC -eq 0 -a -e "$T/SK2.end"

echo "-- (i7) explicit owner exceptions: util max 0 / cooldown 0 disable the gate (logged gate=disabled)"
setutil 100
GPU_SLOT_CAPTURE_UTIL_MAX=0 GPU_SLOT_LAUNCH_COOLDOWN=0 $GS capture --label GD -- $JOB GD 0.1; RC=$?
check "capture runs at util 100 with both gates disabled (exit 0)" test $RC -eq 0 -a -e "$T/GD.end"
check "log: gate=disabled for util and for cooldown" \
  bash -c "grep 'label=GD' '$GPU_SLOT_LOG' | grep -q 'gate=disabled which=util' && grep 'label=GD' '$GPU_SLOT_LOG' | grep -q 'gate=disabled which=cooldown'"
setutil 20
unset GPU_SLOT_ML_PATTERN GPU_SLOT_GPU_PATTERN

echo "-- (i8) GPU client classification on a synthetic process table (no live processes involved)"
mkdir -p "$T/apps/G.app/Contents/MacOS" "$T/apps/G.app/Contents/Resources" "$T/apps/U.app/Contents/Resources/Data" \
         "$T/apps/V.app/Contents/UE" "$T/apps/U.app/Contents/MacOS" "$T/apps/V.app/Contents/MacOS"
touch "$T/apps/G.app/Contents/Resources/game.pck"
check "gpu_procs kinds, exclusions, dedupe, wrapped, stuck; unreal_procs keeps its shape" \
  env -u GPU_SLOT_UNREAL_PATTERN -u GPU_SLOT_GPU_IGNORE_PATTERN -u GPU_SLOT_CAPTURE_PATTERN python3 - "$HERE" "$T/apps" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import gpu_slot as g
A = sys.argv[2]
UE = "/Users/x/UE_5.8/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor"
rows = [  # pid, ppid, stat, comm, cmd, expected kind (None = not a GPU client)
 (100, 1, "S", "/bin/zsh", "zsh", None),
 (101, 100, "S", "/usr/bin/python3", "python3 /x/tools/gpu/gpu_slot.py capture --label c -- " + UE, None),
 (102, 101, "S", UE, UE + " /p/unreal/WebHomage/WebHomage.uproject -game -WHShotDir=/tmp", "unreal-editor"),
 (103, 1, "S", UE, UE + " /p/unreal/WebHomage/WebHomage.uproject", "unreal-editor"),
 (104, 1, "S", "/tmp/b/Veyr-Mac-Shipping.app/Contents/MacOS/Veyr-Mac-Shipping", "/tmp/b/Veyr-Mac-Shipping.app/Contents/MacOS/Veyr-Mac-Shipping -windowed", "unreal-game"),
 (105, 1, "S", A + "/V.app/Contents/MacOS/V", A + "/V.app/Contents/MacOS/V", "unreal-game"),
 (106, 103, "S", "/Users/x/UE_5.8/Engine/Binaries/Mac/ShaderCompileWorker", "ShaderCompileWorker x", None),
 (107, 1, "S", "/Users/x/UE_5.8/Engine/Binaries/Mac/CrashReportClient.app/Contents/MacOS/CrashReportClient", "CrashReportClient", None),
 (108, 1, "S", "/Applications/Godot.app/Contents/MacOS/Godot", "/Applications/Godot.app/Contents/MacOS/Godot --path /w/game", "godot"),
 (109, 1, "S", A + "/G.app/Contents/MacOS/G", A + "/G.app/Contents/MacOS/G", "godot"),
 (110, 1, "S", "/usr/local/bin/godot", "godot --headless --script x.gd", None),
 (111, 1, "S", "/Applications/Unity/Hub/Editor/6000/Unity.app/Contents/MacOS/Unity", "Unity -projectPath /w", "unity"),
 (112, 111, "S", "/Applications/Unity/Hub/Editor/6000/Unity.app/Contents/MacOS/Unity", "Unity -batchMode -name AssetImportWorker0", None),
 (113, 1, "S", A + "/U.app/Contents/MacOS/U", A + "/U.app/Contents/MacOS/U", "unity"),
 (114, 1, "S", "/Applications/Blender.app/Contents/MacOS/Blender", "Blender -b x.blend", "blender"),
 (115, 1, "S", "/Users/x/.cache/uv/a/bin/python", "/Users/x/.cache/uv/a/bin/python /Users/x/.cache/uv/a/bin/blender-mcp", None),
 (116, 1, "S", "node", "node /Users/x/.npm/_npx/1/node_modules/.bin/godot-mcp", None),
 (117, 1, "S", "/opt/homebrew/bin/uv", "/opt/homebrew/bin/uv tool uvx blender-mcp", None),
 (118, 1, "S", "/opt/homebrew/bin/uv", "uv run python -m video2rig.train --cfg a", "ml"),
 (119, 118, "S", "/w/.venv/bin/python", "/w/.venv/bin/python -m video2rig.train --cfg a", None),  # folded into 118
 (120, 1, "S", "/w/.venv/bin/python3", "python3 train.py --epochs 3", "ml"),
 (121, 1, "S", "/w/.venv/bin/python3", "python3 -m pip install torch", None),
 (122, 1, "S", "/Library/Application Support/com.elgato.StreamDeck/NodeJS/20/node", "node --no-global-search-paths plugin.js", None),
 (123, 1, "S", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "Google Chrome", None),
 (124, 1, "S", "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/1/Helpers/Google Chrome Helper (GPU).app/Contents/MacOS/Google Chrome Helper (GPU)", "Google Chrome Helper (GPU) --type=gpu-process", None),
 (125, 1, "S", "/Applications/Steam.app/Contents/MacOS/steam_osx", "steam_osx", None),
 (126, 1, "Ss", "C:\\windows\\system32\\winedevice.exe", "C:\\windows\\system32\\winedevice.exe", None),
 (127, 1, "S", "/usr/bin/python3", "python3 /x/tools/gpu/gpu_watchdog.py --loop", None),
 (128, 1, "E", UE, UE + " /p/unreal/WebHomage/WebHomage.uproject -game", "unreal-editor"),
 (129, 1, "Z", "(Godot)", "<defunct>", "godot"),
 (130, 1, "S", "/Applications/Epic Games Launcher.app/Contents/MacOS/EpicGamesLauncher", "EpicGamesLauncher", None),
 (131, 1, "S", "/Users/x/UE_5.8/Engine/Binaries/Mac/UnrealEditor-Cmd", "UnrealEditor-Cmd p.uproject -run=x -nullrhi", None),
]
table = {r[0]: {"pid": r[0], "ppid": r[1], "stat": r[2], "etime": "01:00", "comm": r[3], "cmd": r[4]} for r in rows}
cfg = g.Cfg()
got = {p["pid"]: p for p in g.gpu_procs(cfg, table)}
bad = [(r[0], r[5], got.get(r[0], {}).get("kind")) for r in rows if got.get(r[0], {}).get("kind") != r[5]]
if bad:
    print("     mismatches (pid, want, got):", bad)
ok = not bad
ok &= got[102]["wrapped"] is True and got[103]["wrapped"] is False and got[102]["role"] == "capture"
ok &= got[102]["project"] == "p" and got[118]["project"].startswith("video2rig")
st = sorted((p["pid"], p["stat"][0]) for p in g.stuck_clients(cfg, table))
ok &= st == [(128, "E"), (129, "Z")]
ue = g.unreal_procs(cfg, table)
ok &= [(p["pid"], p["kind"]) for p in ue] == [(102, "capture"), (103, "editor"), (128, "capture")]
ok &= all(set(p) >= {"pid", "ppid", "etime", "cmd", "comm", "kind", "project"} for p in ue)
fg = g.foreign_gpu_clients(cfg, table, 101)
ok &= 102 not in {p["pid"] for p in fg} and 103 in {p["pid"] for p in fg}
print("     kinds:", g.by_kind(got.values()), "stuck:", st)
sys.exit(0 if ok else 1)
PY

echo "== (j) default 3 slots / GPU clients, clamped by the GPU watchdog tripwire (owner 2026-10-29) =="
unset GPU_SLOT_CAPTURE_SLOTS
export GPU_SLOT_ML_PATTERN="FAKEML_$TOKEN" GPU_SLOT_GPU_PATTERN="FAKEGPU_$TOKEN"
setutil 20
capof() { "$GS" cap | head -1; }
maxconc() {  # maxconc [=] N name... : at most (exactly with =) N of the named jobs ran at once
  python3 - "$T" "$@" <<'PY'
import sys
d, a = sys.argv[1], sys.argv[2:]
exact = a[0] == "="
if exact: a = a[1:]
n, names = int(a[0]), a[1:]
iv = [(float(open("%s/%s.start" % (d, x)).read()), float(open("%s/%s.end" % (d, x)).read())) for x in names]
ev = sorted([(s, 1) for s, e in iv] + [(e, -1) for s, e in iv])
cur = mx = 0
for t, dl in ev:
    cur += dl; mx = max(mx, cur)
print("      max concurrent: %d" % mx)
sys.exit(0 if (mx == n if exact else mx <= n) else 1)
PY
}
wd healthy; check "cap: healthy watchdog -> cap 3 (default GPU_SLOT_CAPTURE_SLOTS)" test "$(capof)" = "cap 3"
for m in warn strike stuck old; do wd $m; check "cap: watchdog $m -> cap 2" test "$(capof)" = "cap 2"; done
rm -f "$GPU_SLOT_WATCHDOG_JSON"; check "cap: watchdog file missing (stale) -> cap 2" test "$(capof)" = "cap 2"
echo '{nope' > "$GPU_SLOT_WATCHDOG_JSON"; check "cap: watchdog file unreadable (stale) -> cap 2" test "$(capof)" = "cap 2"
wd trip; "$GS" cap > "$T/cap.out"; RC=$?
check "cap: trip -> cap 0, exit 3, reason names the TRIP" bash -c "test $RC -eq 3 && grep -q '^cap 0' '$T/cap.out' && grep -q 'watchdog TRIP' '$T/cap.out'"
wd healthy; check "cap: GPU_SLOT_CAPTURE_SLOTS=1 still overrides (healthy -> 1)" test "$(GPU_SLOT_CAPTURE_SLOTS=1 capof)" = "cap 1"
check "status --json: effective_slots 3, gpu_client_cap 3, cap_why empty" python3 - "$HERE" <<'PY'
import json, subprocess, sys
s = json.loads(subprocess.run([sys.argv[1] + "/gpu_status.sh", "--json"], capture_output=True, text=True).stdout)
sys.exit(0 if s["effective_slots"] == 3 and s["gpu_client_cap"] == 3 and s["cap_why"] == [] and s["slots"] == 3 else 1)
PY
$GS capture --label J1 -- $JOB J1 2.0 & Q1=$!
$GS capture --label J2 -- $JOB J2 2.0 & Q2=$!
$GS capture --label J3 -- $JOB J3 2.0 & Q3=$!
wait $Q1 $Q2 $Q3
check "healthy: three captures ran at once" maxconc = 3 J1 J2 J3
wd warn
$GS capture --label K1 -- $JOB K1 2.0 & Q1=$!
$GS capture --label K2 -- $JOB K2 2.0 & Q2=$!
waitf "$T/K1.start"; waitf "$T/K2.start"; sleep 0.3
$GS capture --label K3 -- $JOB K3 0.3 & Q3=$!
sleep 0.8
check "watchdog warn: third capture has NOT started while two slots are held" test ! -e "$T/K3.start"
wait $Q1 $Q2 $Q3
check "watchdog warn: at most 2 ran at once" maxconc 2 K1 K2 K3
check "  ... the queue wait log names the clamp (cap=2, watchdog warn)" bash -c "grep 'label=K3' '$GPU_SLOT_LOG' | grep 'event=wait' | grep -q 'cap=2 .*watchdog warn'"
wd healthy
$GS capture --label L1 -- $JOB L1 0.8 & Q1=$!
$GS capture --label L2 -- $JOB L2 2.5 & Q2=$!
$GS capture --label L3 -- $JOB L3 2.5 & Q3=$!
waitf "$T/L1.start"; waitf "$T/L2.start"; waitf "$T/L3.start"
wd strike
$GS capture --label L4 -- $JOB L4 0.2 & Q4=$!
wait $Q1 $Q2 $Q3 $Q4
check "demoted while 3 run: a new capture waits until fewer than 2 slots are held (after the 2nd release)" \
  ge "$(val L4.start)" "$(python3 -c "print(min($(val L2.end),$(val L3.end)) - 0.05)")"
wd healthy
fake_gpu 60 FAKEML; ML=$FAKE_PID
fake_gpu 60 FAKEGPU; OG=$FAKE_PID
sleep 0.3
$GS capture --label M1 -- $JOB M1 0.1; RC=$?
check "healthy: 2 foreign GPU clients (trainer + other) -> capture launches (client cap 3)" test $RC -eq 0 -a -e "$T/M1.end"
wd warn
$GS capture --label M2 --timeout 1.5 --json "$T/m2.json" -- $JOB M2 0.1; RC=$?
check "watchdog warn: 2 foreign GPU clients -> cap-full at cap 2, exit 75, command not run" \
  bash -c "test $RC -eq 75 -a ! -e '$T/M2.start' && grep -q '\"outcome\": \"cap-full-timeout\"' '$T/m2.json'"
check "  ... cap-full log carries cap=2 and the watchdog reason" bash -c "grep 'label=M2' '$GPU_SLOT_LOG' | grep 'phase=cap-full' | grep -q 'cap=2 .*watchdog warn'"
kill $ML $OG 2>/dev/null; wait $ML $OG 2>/dev/null
wd trip
$GS capture --label TRIP --timeout 1.0 --json "$T/trip.json" -- $JOB TRIP 0.1; RC=$?
check "watchdog trip: capture never acquires, exit 75, command NOT run" test $RC -eq 75 -a ! -e "$T/TRIP.start"
check "  ... wait-timeout log line carries cap=0 and the TRIP reason" bash -c "grep 'label=TRIP' '$GPU_SLOT_LOG' | grep 'event=wait-timeout' | grep -q 'cap=0 .*watchdog TRIP'"
wd healthy

echo
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
