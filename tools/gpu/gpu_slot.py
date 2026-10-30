#!/usr/bin/env python3
# Homage fan game tooling. Not an official Marvel, Sony or Insomniac project; no affiliation.
"""gpu_slot: machine-wide GPU launch guard for agent-launched engines, renderers and GPU trainers.

  gpu_slot.sh capture [opts] -- CMD...   hold one of N (default 3, clamped by the GPU watchdog tripwire)
                                         shared capture slots; before launching
                                         CMD pass the capture gate: fewer than N foreign GPU clients,
                                         GPU "Device Utilization %" < 85 for 10 consecutive s, and >= 20 s
                                         since the last release (cold-launch cooldown)
  gpu_slot.sh perf    [opts] -- CMD...   EXCLUSIVE: waits for no capture slot held, no other Unreal
                                         capture process, and GPU "Device Utilization %" < 15 for 10
                                         consecutive seconds; then runs CMD (max hold 15 min)
  gpu_slot.sh status [--json]            holders, waiters, utilization, every GPU client by kind, PAUSED
  gpu_slot.sh cap                        effective capture-slot / GPU-client cap and why (exit 3 on a trip)
  gpu_slot.sh util                       print the current GPU utilization (integer percent)
  gpu_slot.sh summary FILE.json          one-line "GPU-LOCK: ..." summary of a --json sidecar (paste next to perf numbers)
  gpu_slot.sh pause [reason words...]    create <state dir>/PAUSED: no class launches anything until `resume`
  gpu_slot.sh resume                     remove PAUSED (never automatic; the log records who resumed)

opts: --label NAME  --json FILE (result sidecar)  --timeout SECS (max wait to acquire)
Exit code = CMD's exit code.  Wrapper-only codes: 2 usage, 70 internal error, 75 CMD NOT run (outcome
wait-timeout | cap-full-timeout | skipped-busy | stuck-engine | paused), 124 max hold exceeded (CMD
killed), 127 CMD not found, 128+N killed by signal N.

Locking = kernel flock(2) via python fcntl on files in the state dir (default
$GPU_LOCK_DIR, default ~/.cache/gpu-slot). flock is released by the kernel when the holder dies, so a
crashed / kill -9'd holder can never wedge the lock; stale holder/queue records (dead PID, or PID
reused: start time differs) are detected, logged as "stale-recovered" and removed by any waiter.
Fairness: strict FIFO ticket queue, only the head waiter may try to acquire.

GPU clients (gpu_procs()): every process that renders or computes on the GPU, not only UnrealEditor:
  unreal-editor  .../MacOS/UnrealEditor (role capture|editor), UnrealEditor-Cmd without -nullrhi
  unreal-game    packaged games: *-Mac-(Shipping|Development|Test|Debug|DebugGame), an .app with
                 Contents/UE, or a binary under /Binaries/Mac/ (tool binaries such as
                 ShaderCompileWorker / CrashReportClient / UnrealTraceServer / Epic* excluded)
  godot          basename godot*/Godot*, an .app with Contents/Resources/*.pck, or --main-pack
                 (--headless runs use the dummy renderer and are not counted)
  unity          Unity editor (/Unity.app/ or /Unity/Hub/ .../MacOS/Unity) or a player .app with
                 Contents/Resources/Data (AssetImportWorker and -nographics runs not counted)
  blender        Blender.app/Contents/MacOS/Blender or basename blender (never blender-mcp)
  ml             python/uv/uvx processes whose command line matches GPU_SLOT_ML_PATTERN (default
                 DEFAULT_ML_PAT below: -m video2rig|torch|mlx, video2rig, torch, mlx, mlx_lm, train.py,
                 /reader/, trainer; pip and *-mcp commands excluded). A forked child of an ml process
                 with the same kind (dataloader workers, uv -> python) is folded into its parent.
  other          anything matching GPU_SLOT_GPU_PATTERN
  Never counted: gpu_slot / gpu_status / gpu_watchdog wrappers, *-mcp servers, Steam / Wine / CrossOver
  launchers and helpers, crash reporters, and anything matching GPU_SLOT_GPU_IGNORE_PATTERN.
  A trainer that wants its GPU use counted and its launch gated runs as
      gpu_slot.sh capture --label trainer -- python train.py

Guards (owner rules, agents-md PR #33, after the 2026-10-29 03:23-10:17 seven-hour GPU driver wedge):
  * cap 3 + watchdog tripwire (owner decision 2026-10-29 23:20, "do the maximum amount that is safe at
    the same time"; evidence: 98 gated launches and 2841 watchdog samples after the 10:17 reboot with zero
    warnings/trips; cap 4 + tripwire ran 10-02..10-28; the wedge came from 5+ clients incl. uncounted MPS
    trainers and 15 gapless cold launches at 100 % util). The effective cap = min(GPU_SLOT_CAPTURE_SLOTS
    (default 3), watchdog cap), re-read from <state dir>/gpu_watchdog.json (GPU_SLOT_WATCHDOG_JSON) at every
    acquire attempt and every gate poll:
        trip set (or tripped true)                               -> 0: nothing acquires or launches
        warn non-null, hang_strikes > 0, any stuck_since entry   -> 2
        file missing / unreadable / updated > GPU_SLOT_WATCHDOG_STALE_S (120) s ago -> 2 ("watchdog stale")
    A capture acquires only while fewer capture slots are held (all of capture.N.lock counted) than the
    effective cap (and than GPU_SLOT_STREAMING_SLOTS while STREAMING). MPS trainers stay serialized with
    engine launches by the capture util gate below.
  * client cap: a capture holding a slot does not launch while >= <effective cap> foreign GPU
    clients run (foreign = not a descendant of this wrapper); log "wait phase=cap-full clients=pid:kind,..";
    after the class wait timeout: exit 75, outcome cap-full-timeout (a trip waits here too, logged cap=0).
  * capture util gate + cooldown: utilization < GPU_SLOT_CAPTURE_UTIL_MAX for GPU_SLOT_CAPTURE_CALM_SECONDS
    consecutive s AND >= GPU_SLOT_LAUNCH_COOLDOWN s since <state dir>/last_release (epoch, written at every
    capture launch and every release). Budget GPU_SLOT_CAPTURE_SETTLE_TIMEOUT s: then "settle-timeout", CMD NOT run, exit 75,
    outcome skipped-busy (contaminated). Setting the util max or the cooldown to 0 disables that gate
    (explicit owner exception, logged gate=disabled).
  * stuck-engine preflight: while any GPU client is in ps state E (exiting) or Z (zombie), no class
    acquires or launches; log "stuck-engine pid= stat= kind="; wait timeout: exit 75, outcome stuck-engine.
  * PAUSED switch: while <state dir>/PAUSED exists no class acquires or launches; log "paused reason=..";
    wait timeout: exit 75, outcome paused. PAUSED is JSON {since (epoch), since_iso, by, reason, boottime
    (kern.boottime epoch)}; `pause` writes by="<parent pid> <parent cmd>", gpu_watchdog writes
    by="gpu_watchdog". A plain-text PAUSED file also pauses (first line = reason). Never auto-resumed.

Environment (all optional; tests shrink the timings):
  GPU_SLOT_DIR, GPU_SLOT_LOG, GPU_SLOT_POLL=1, GPU_SLOT_UTIL_MAX=15, GPU_SLOT_CALM_SECONDS=10,
  GPU_SLOT_CAPTURE_SLOTS=3 (also the foreign GPU client cap; clamped by the watchdog tripwire),
  GPU_SLOT_WATCHDOG_JSON=<state dir>/gpu_watchdog.json, GPU_SLOT_WATCHDOG_STALE_S=120, GPU_SLOT_PERF_MAX_HOLD=900,
  GPU_SLOT_CAPTURE_MAX_HOLD=2400, GPU_SLOT_PERF_WAIT_TIMEOUT=1800, GPU_SLOT_CAPTURE_WAIT_TIMEOUT=3600,
  GPU_SLOT_SAMPLE_INTERVAL=2, GPU_SLOT_WAIT_LOG_EVERY=30, GPU_SLOT_LABEL, GPU_SLOT_QUIET=1,
  GPU_SLOT_CAPTURE_UTIL_MAX=85 (0 disables), GPU_SLOT_CAPTURE_CALM_SECONDS=10,
  GPU_SLOT_LAUNCH_COOLDOWN=20 (0 disables), GPU_SLOT_CAPTURE_SETTLE_TIMEOUT=180,
  GPU_SLOT_ML_PATTERN=<regex>, GPU_SLOT_GPU_PATTERN=<regex: extra processes that count, kind other>,
  GPU_SLOT_GPU_IGNORE_PATTERN=<regex: never count>,
  GPU_SLOT_MOCK_UTIL=<int> | GPU_SLOT_MOCK_UTIL_FILE=<file holding an int>   (replaces ioreg),
  GPU_SLOT_MOCK_STUCK_FILE=<file: lines "pid stat kind", each treated as a stuck GPU client>,
  GPU_SLOT_UNREAL_PATTERN=<regex on the command line> (replaces "executable is UnrealEditor"),
  GPU_SLOT_CAPTURE_PATTERN=<regex> (which Unreal instances count as capture processes),
  GPU_SLOT_FPS_CAP=60 (frame cap injected into every wrapped engine launch; 0 disables),
  GPU_SLOT_FPS_CAP_STREAMING=30 (cap while the STREAMING flag file exists in the state dir),
  GPU_SLOT_STREAMING_SLOTS=0 (capture slots open while STREAMING: 0 = agent captures WAIT until the
  owner is off stream; set 1 only as an explicit owner exception).
The wrapped CMD sees GPU_SLOT_HELD, GPU_SLOT_LABEL, GPU_SLOT_WAIT_S, GPU_SLOT_UTIL_BEFORE,
GPU_SLOT_INSTANCES_BEFORE (= total GPU clients before launch), GPU_SLOT_EXCLUSIVE, GPU_SLOT_FPS_CAP,
GPU_SLOT_STREAMING. Result JSON / release log carry gpu_clients_before (total + by kind) and
gpu_clients_max_during.
Frame cap (owner rule 2026-10-28): every agent-launched game/engine runs capped. Godot gets
`--max-fps N`, Unreal `-dpcvars=t.MaxFPS=N`; Unity players have no CLI knob (the build must set
Application.targetFrameRate, the cap is exported as $GPU_SLOT_FPS_CAP). While <state dir>/STREAMING
exists (stream_guard.py, stream window / live detection) the cap drops to 30 and NO capture slot is open:
agent captures queue until the flag is gone (owner decision 2026-10-28: one agent render next to a
streamed game still pinned the GPU and glitched the stream).

Library use (gpu_watchdog.py imports this module): Cfg, proc_table, gpu_procs, unreal_procs,
foreign_gpu_clients, foreign_captures, stuck_clients, read_paused, write_paused, pause_record,
read_util, read_last_release.
"""
import errno
import glob
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

DEFAULT_DIR = os.environ.get("GPU_LOCK_DIR", os.path.expanduser("~/.cache/gpu-slot"))
DEFAULT_CAPTURE_PAT = r"(^|\s)-game(\s|$)|-WHShotDir=|-WHPerfFrom="
DEFAULT_ML_PAT = (r"(-m\s+(video2rig|torch|mlx)\b|\bvideo2rig\b|\btorch\b|\bmlx(_lm|_vlm)?\b|train\.py"
                  r"|/reader/|trainer)")
GPU_KINDS = ("unreal-editor", "unreal-game", "godot", "unity", "blender", "ml", "other")
EX_TIMEOUT = 75
EX_MAXHOLD = 124


def _re(name):
    v = os.environ.get(name)
    if not v:
        return None
    try:
        return re.compile(v)
    except re.error as ex:
        sys.stderr.write("gpu_slot: bad regex %s=%r: %s\n" % (name, v, ex))
        sys.exit(2)


def _f(name, default):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        sys.stderr.write("gpu_slot: bad %s=%r\n" % (name, v))
        sys.exit(2)


class Cfg:
    def __init__(self):
        e = os.environ
        self.dir = e.get("GPU_SLOT_DIR") or DEFAULT_DIR
        self.log = e.get("GPU_SLOT_LOG") or os.path.join(self.dir, "gpu_slot.log")
        self.poll = _f("GPU_SLOT_POLL", 1.0)
        self.util_max = _f("GPU_SLOT_UTIL_MAX", 15.0)
        self.calm = _f("GPU_SLOT_CALM_SECONDS", 10.0)
        self.slots = int(_f("GPU_SLOT_CAPTURE_SLOTS", 3))
        self.max_hold = {"perf": _f("GPU_SLOT_PERF_MAX_HOLD", 900.0),
                         "capture": _f("GPU_SLOT_CAPTURE_MAX_HOLD", 2400.0)}
        self.wait_timeout = {"perf": _f("GPU_SLOT_PERF_WAIT_TIMEOUT", 1800.0),
                             "capture": _f("GPU_SLOT_CAPTURE_WAIT_TIMEOUT", 3600.0)}
        self.sample = _f("GPU_SLOT_SAMPLE_INTERVAL", 2.0)
        self.wait_log_every = _f("GPU_SLOT_WAIT_LOG_EVERY", 30.0)
        self.quiet = e.get("GPU_SLOT_QUIET") == "1"
        self.unreal_pat = e.get("GPU_SLOT_UNREAL_PATTERN") or None
        self.capture_pat = re.compile(e.get("GPU_SLOT_CAPTURE_PATTERN") or DEFAULT_CAPTURE_PAT)
        self.fps_cap = int(_f("GPU_SLOT_FPS_CAP", 60))
        self.fps_cap_streaming = int(_f("GPU_SLOT_FPS_CAP_STREAMING", 30))
        self.streaming_slots = int(_f("GPU_SLOT_STREAMING_SLOTS", 0))
        self.mock_util = e.get("GPU_SLOT_MOCK_UTIL")
        self.mock_util_file = e.get("GPU_SLOT_MOCK_UTIL_FILE")
        self.mock_stuck_file = e.get("GPU_SLOT_MOCK_STUCK_FILE") or None
        self.capture_util_max = _f("GPU_SLOT_CAPTURE_UTIL_MAX", 85.0)
        self.capture_calm = _f("GPU_SLOT_CAPTURE_CALM_SECONDS", 10.0)
        self.cooldown = _f("GPU_SLOT_LAUNCH_COOLDOWN", 20.0)
        self.capture_settle_timeout = _f("GPU_SLOT_CAPTURE_SETTLE_TIMEOUT", 180.0)
        self.ml_pat = _re("GPU_SLOT_ML_PATTERN") or re.compile(DEFAULT_ML_PAT)
        self.gpu_pat = _re("GPU_SLOT_GPU_PATTERN")
        self.gpu_ignore_pat = _re("GPU_SLOT_GPU_IGNORE_PATTERN")
        self.holders = os.path.join(self.dir, "holders")
        self.queue = os.path.join(self.dir, "queue")
        self.locks = os.path.join(self.dir, "locks")
        self.perf_lock = os.path.join(self.locks, "perf.lock")
        self.streaming_flag = os.path.join(self.dir, "STREAMING")
        self.paused_flag = os.path.join(self.dir, "PAUSED")
        self.last_release = os.path.join(self.dir, "last_release")
        self.watchdog_json = e.get("GPU_SLOT_WATCHDOG_JSON") or os.path.join(self.dir, "gpu_watchdog.json")
        self.watchdog_stale = _f("GPU_SLOT_WATCHDOG_STALE_S", 120.0)

    def ensure_dirs(self):
        for d in (self.dir, self.holders, self.queue, self.locks, os.path.dirname(self.log)):
            os.makedirs(d, mode=0o777, exist_ok=True)


# ---------------------------------------------------------------- small helpers

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _run(argv, timeout=10):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def read_util(cfg):
    """GPU 'Device Utilization %' (max over accelerators) as float, or None if unreadable."""
    if cfg.mock_util_file:
        try:
            with open(cfg.mock_util_file) as fh:
                return float(fh.read().strip())
        except Exception:
            return None
    if cfg.mock_util is not None:
        try:
            return float(cfg.mock_util)
        except ValueError:
            return None
    out = _run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"])
    vals = [int(x) for x in re.findall(r'"Device Utilization %"\s*=\s*(\d+)', out)]
    return float(max(vals)) if vals else None


def fmt_util(u):
    return "?" if u is None else ("%d" % u if float(u).is_integer() else "%.1f" % u)


def streaming(cfg):
    """True while the owner's stream window flag exists (written by tools/stream/stream_guard.py)."""
    return os.path.exists(cfg.streaming_flag)


def engine_kind(cmd):
    """Best-effort engine detection from the wrapped command: 'godot' | 'unreal' | 'unity' | None."""
    if not cmd:
        return None
    exe = cmd[0]
    base = os.path.basename(exe)
    joined = " ".join(cmd)
    app = None
    m = re.match(r"(.*\.app)/Contents/MacOS/", exe)
    if m:
        app = m.group(1)
    if re.search(r"godot", base, re.I) or "--main-pack" in cmd:
        return "godot"
    if app and glob.glob(os.path.join(app, "Contents", "Resources", "*.pck")):
        return "godot"
    if os.path.exists(exe + ".pck") or os.path.exists(os.path.splitext(exe)[0] + ".pck"):
        return "godot"
    if re.search(r"UnrealEditor|UE4Editor|/Binaries/Mac/|\.uproject(\s|$)", joined) or re.search(r"(^|\s)-game(\s|$)", joined):
        return "unreal"
    if app and os.path.isdir(os.path.join(app, "Contents", "Resources", "Data")):
        return "unity"
    if re.search(r"/Unity\.app/|/Unity/Hub/", joined):
        return "unity"
    return None


def apply_fps_cap(cmd, cap, kind):
    """Return (cmd, applied: bool). Never overrides a cap the caller already passed."""
    if not cap or cap <= 0 or not kind:
        return list(cmd), False
    cmd = list(cmd)
    if kind == "godot":
        if "--max-fps" in cmd or any(a.startswith("--max-fps=") for a in cmd):
            return cmd, False
        return cmd + ["--max-fps", str(cap)], True
    if kind == "unreal":
        if any("t.MaxFPS" in a for a in cmd):
            return cmd, False
        for i, a in enumerate(cmd):
            if a.lower().startswith("-dpcvars="):
                cmd[i] = a + (",t.MaxFPS=%d" % cap)
                return cmd, True
        return cmd + ["-dpcvars=t.MaxFPS=%d" % cap], True
    return cmd, False   # unity: no CLI knob; exported via $GPU_SLOT_FPS_CAP


def proc_start(pid):
    """(state, lstart) for a pid, or ('', '') if it does not exist."""
    out = _run(["ps", "-o", "stat=,lstart=", "-p", str(pid)], 5).strip()
    if not out:
        return "", ""
    parts = out.split(None, 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


def pid_alive(pid, start):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except Exception:
        return False
    stat, lstart = proc_start(pid)
    if not stat or stat.startswith("Z"):
        return False
    return (not start) or lstart == start


def proc_table(cfg):
    """All processes: {pid: dict(pid, ppid, stat, etime, cmd, comm)}."""
    out1 = _run(["ps", "-axww", "-o", "pid=,ppid=,stat=,etime=,command="])
    out2 = _run(["ps", "-axww", "-o", "pid=,comm="])
    comm = {}
    for line in out2.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)$", line)
        if m:
            comm[int(m.group(1))] = m.group(2).strip()
    table = {}
    for line in out1.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s*(.*)$", line)
        if not m:
            continue
        pid = int(m.group(1))
        table[pid] = {"pid": pid, "ppid": int(m.group(2)), "stat": m.group(3), "etime": m.group(4),
                      "cmd": m.group(5), "comm": comm.get(pid, "")}
    return table


_WRAPPER_RE = re.compile(r"gpu_slot\.(py|sh)|gpu_status|gpu_watchdog")
_WRAPPER_HOLD_RE = re.compile(r"gpu_slot\.py\s+(capture|perf)\b")
_PY_BASE_RE = re.compile(r"^(python[0-9.]*w?|Python|uv|uvx)$")
_EXCL_BASE_RE = re.compile(r"(?i)(^steam|steamwebhelper|^ipcserver|^wine|^crossover|crash|mcp)")
_MCP_CMD_RE = re.compile(r"(?i)(\w-mcp\b|mcp[-_]server|\bmcp\b)")
_PIP_RE = re.compile(r"(^|\s|/)pip[0-9.]*(\s|$)|-m\s+pip\b")
_UE_GAME_RE = re.compile(r"-Mac-(Shipping|Development|Test|Debug|DebugGame)$")
_UE_TOOL_RE = re.compile(r"(?i)(ShaderCompileWorker|CrashReport|UnrealTraceServer|^Epic|UnrealBuildTool|UnrealPak|"
                         r"LiveCodingConsole|UnrealCEFSubProcess|UnrealInsights|UnrealFrontend|ZenServer|^zen$|"
                         r"dotnet|^mono|Lightmass|Interchange|Switchboard|UbaAgent|Worker$|Server$|Helper$)")
_UNITY_SKIP_RE = re.compile(r"(?i)AssetImportWorker|(^|\s)-nographics(\s|$)")
_FS_CACHE = {}


def _fs(kind, path):
    """Cached filesystem probe ('isdir' | 'exists' | 'glob'); app bundles do not change shape while running."""
    key = (kind, path)
    if key not in _FS_CACHE:
        if len(_FS_CACHE) > 4096:
            _FS_CACHE.clear()
        if kind == "isdir":
            _FS_CACHE[key] = os.path.isdir(path)
        elif kind == "exists":
            _FS_CACHE[key] = os.path.exists(path)
        else:
            _FS_CACHE[key] = bool(glob.glob(path))
    return _FS_CACHE[key]


def _exe_of(p):
    comm = (p.get("comm") or "").strip()
    if comm.startswith("(") and comm.endswith(")"):
        comm = comm[1:-1]
    if comm.startswith("/"):
        return comm
    toks = (p.get("cmd") or "").split()
    if toks and toks[0].startswith("/"):
        return toks[0]
    return comm or (toks[0] if toks else "")


def _flag(cmd, *names):
    return re.search(r"(^|\s)(%s)(=\S*)?(\s|$)" % "|".join(re.escape(n) for n in names), cmd) is not None


def _classify(cfg, p):
    """(kind, role) when the process is a GPU client, else None."""
    cmd = p.get("cmd") or ""
    if cfg.gpu_ignore_pat is not None and cfg.gpu_ignore_pat.search(cmd):
        return None
    if _WRAPPER_RE.search(cmd):
        return None
    exe = _exe_of(p)
    base = os.path.basename(exe)
    low = cmd.lower()
    zombie = (p.get("stat") or "").startswith("Z")
    if cfg.unreal_pat:
        is_ed = re.search(cfg.unreal_pat, cmd) is not None
    else:
        is_ed = (exe.endswith("/MacOS/UnrealEditor") or (zombie and base == "UnrealEditor")
                 or (base == "UnrealEditor-Cmd" and "-nullrhi" not in low))
    if is_ed:
        return "unreal-editor", ("capture" if cfg.capture_pat.search(cmd) else "editor")
    if "\\" in exe or "/Steam.app/" in exe or _EXCL_BASE_RE.search(base):
        return None
    m = re.match(r"(.*\.app)/Contents/MacOS/[^/]+$", exe)
    app = m.group(1) if m else None
    if (_UE_GAME_RE.search(base) or (app and not _UE_TOOL_RE.search(base) and _fs("isdir", app + "/Contents/UE"))
            or ("/Binaries/Mac/" in exe and not base.startswith("UnrealEditor") and not _UE_TOOL_RE.search(base))):
        return (None if "-nullrhi" in low else ("unreal-game", "game"))
    if (re.match(r"(?i)godot", base) or _flag(cmd, "--main-pack")
            or (app and _fs("glob", glob.escape(app) + "/Contents/Resources/*.pck"))
            or (exe.startswith("/") and not app and _fs("exists", exe + ".pck"))):
        if _flag(cmd, "--headless"):
            return None
        return "godot", ("editor" if _flag(cmd, "-e", "--editor") else "game")
    if ((base == "Unity" and re.search(r"/Unity\.app/|/Unity/Hub/", exe)) or (zombie and base == "Unity")
            or (app and not app.endswith("/Unity.app") and _fs("isdir", app + "/Contents/Resources/Data"))):
        if _UNITY_SKIP_RE.search(cmd):
            return None
        return "unity", ("editor" if base == "Unity" else "player")
    if exe.endswith("Blender.app/Contents/MacOS/Blender") or base.lower() == "blender":
        return "blender", ("background" if _flag(cmd, "-b", "--background") else "ui")
    if (_PY_BASE_RE.match(base) and cfg.ml_pat.search(cmd) and not _MCP_CMD_RE.search(cmd)
            and not _PIP_RE.search(cmd)):
        return "ml", "trainer"
    if cfg.gpu_pat is not None and cfg.gpu_pat.search(cmd) and not _MCP_CMD_RE.search(cmd):
        return "other", "custom"
    return None


def _project(q):
    cmd, kind = q["cmd"], q["kind"]
    if kind.startswith("unreal"):
        m = re.search(r"(/\S+?)/unreal/WebHomage/WebHomage\.uproject", cmd) or \
            re.search(r"(/\S*?)/[^/ ]*\.uproject", cmd)
        if m:
            return os.path.basename(m.group(1))
    if kind == "godot":
        m = re.search(r"--path[= ](\S+)", cmd)
        if m:
            return os.path.basename(m.group(1).rstrip("/"))
    if kind == "ml":
        m = re.search(r"-m\s+(\S+)", cmd) or re.search(r"(\S+\.py)\b", cmd)
        if m:
            return os.path.basename(m.group(1))
    m = re.search(r"([^/]+)\.app/Contents/MacOS/", _exe_of(q))
    return m.group(1) if m else ""


def _all_gpu_clients(cfg, table):
    """Every classified GPU client incl. folded children (dup_of = pid of the same-kind ancestor)."""
    res = {}
    for p in table.values():
        c = _classify(cfg, p)
        if c is None:
            continue
        q = dict(p)
        q.setdefault("stat", "")
        q["kind"], q["role"] = c
        q["project"] = _project(q)
        res[p["pid"]] = q
    wrappers = {pid for pid, p in table.items() if _WRAPPER_HOLD_RE.search(p.get("cmd") or "")}
    for q in res.values():
        q["wrapped"], q["dup_of"] = False, None
        x, seen = q["ppid"], set()
        while x and x in table and x not in seen and len(seen) < 64:
            seen.add(x)
            if x in wrappers:
                q["wrapped"] = True
            a = res.get(x)
            if q["dup_of"] is None and a is not None and a["kind"] == q["kind"] and q["kind"] in ("ml", "other"):
                q["dup_of"] = x
            x = table[x]["ppid"]
    return sorted(res.values(), key=lambda x: x["pid"])


def gpu_procs(cfg, table=None):
    """Every GPU-client process: list of dicts {pid, ppid, stat, etime, cmd, comm, kind, role, project,
    wrapped} with kind in GPU_KINDS; wrapped = runs under a live gpu_slot capture/perf wrapper."""
    table = table if table is not None else proc_table(cfg)
    return [q for q in _all_gpu_clients(cfg, table) if q["dup_of"] is None]


def unreal_procs(cfg, table=None):
    """Unreal editor/game instances (not gpu_slot wrappers): list of dicts with kind capture|editor."""
    table = table if table is not None else proc_table(cfg)
    res = []
    for q in gpu_procs(cfg, table):
        if q["kind"] != "unreal-editor":
            continue
        p = {k: q[k] for k in ("pid", "ppid", "stat", "etime", "cmd", "comm", "project")}
        p["kind"] = q["role"]
        res.append(p)
    return res


def by_kind(clients):
    out = {}
    for p in clients:
        out[p["kind"]] = out.get(p["kind"], 0) + 1
    return out


def fmt_kinds(d):
    return ",".join("%s:%d" % (k, d[k]) for k in sorted(d)) or "none"


def fmt_clients(clients):
    return ",".join("%s:%s" % (p["pid"], p["kind"]) for p in clients)


def descendants(table, root):
    kids = {}
    for p in table.values():
        kids.setdefault(p["ppid"], []).append(p["pid"])
    seen, stack = set(), [root]
    while stack:
        x = stack.pop()
        for k in kids.get(x, []):
            if k not in seen:
                seen.add(k)
                stack.append(k)
    return seen


def foreign_captures(cfg, root_pid=None):
    """Unreal capture processes not descended from root_pid (default: this process)."""
    table = proc_table(cfg)
    mine = descendants(table, root_pid or os.getpid())
    return [p for p in unreal_procs(cfg, table) if p["kind"] == "capture" and p["pid"] not in mine]


def foreign_gpu_clients(cfg, table=None, root_pid=None):
    """GPU clients not descended from root_pid (default: this process); wrappers are never clients."""
    table = table if table is not None else proc_table(cfg)
    mine = descendants(table, root_pid or os.getpid())
    return [p for p in gpu_procs(cfg, table) if p["pid"] not in mine]


def stuck_clients(cfg, table=None):
    """GPU clients in ps state E (exiting) or Z (zombie), plus GPU_SLOT_MOCK_STUCK_FILE entries."""
    table = table if table is not None else proc_table(cfg)
    res = [q for q in _all_gpu_clients(cfg, table) if (q.get("stat") or "")[:1] in ("E", "Z")]
    if cfg.mock_stuck_file:
        try:
            with open(cfg.mock_stuck_file) as fh:
                lines = fh.read().splitlines()
        except OSError:
            lines = []
        for ln in lines:
            f = ln.split()
            if len(f) >= 2 and f[0].isdigit():
                res.append({"pid": int(f[0]), "ppid": 0, "stat": f[1], "etime": "", "cmd": "(mock)", "comm": "",
                            "kind": f[2] if len(f) > 2 else "other", "role": "mock", "project": "",
                            "wrapped": False, "dup_of": None, "mock": True})
    return res


def read_paused(cfg):
    """None while not paused, else a dict with at least 'reason' (JSON PAUSED file, or first text line)."""
    try:
        with open(cfg.paused_flag) as fh:
            txt = fh.read()
    except FileNotFoundError:
        return None
    except OSError as ex:
        return {"reason": "PAUSED file unreadable: %s" % ex}
    try:
        d = json.loads(txt)
        if isinstance(d, dict):
            d["reason"] = str(d.get("reason") or "")
            return d
    except ValueError:
        pass
    lines = txt.strip().splitlines()
    return {"reason": lines[0].strip() if lines else ""}


def boottime():
    m = re.search(r"sec\s*=\s*(\d+)", _run(["sysctl", "-n", "kern.boottime"], 5))
    return int(m.group(1)) if m else None


def pause_record(reason, by):
    """The PAUSED JSON written by `gpu_slot pause` and by gpu_watchdog (by="gpu_watchdog")."""
    return {"since": round(time.time(), 3), "since_iso": now_iso(), "by": by, "reason": reason,
            "boottime": boottime()}


def write_paused(cfg, reason, by):
    """Create <state dir>/PAUSED unless it exists. Returns (created: bool, record in force)."""
    cfg.ensure_dirs()
    cur = read_paused(cfg)
    if cur is not None:
        return False, cur
    rec = pause_record(reason, by)
    _atomic_write(cfg.paused_flag, rec)
    return True, rec


def hold_reason(cfg, table=None):
    """('paused', record) | ('stuck-engine', [clients]) | None. Nothing acquires or launches while set."""
    pz = read_paused(cfg)
    if pz is not None:
        return "paused", pz
    st = stuck_clients(cfg, table)
    if st:
        return "stuck-engine", st
    return None


DEMOTED_CAP = 2


def watchdog_cap(cfg):
    """(cap, reasons) allowed by the GPU watchdog tripwire right now: cfg.slots when healthy, 2 when demoted
    (warn / hang strike / stuck_since / missing or stale file), 0 on a trip. Reasons empty = full cap."""
    demoted = min(cfg.slots, DEMOTED_CAP)
    try:
        with open(cfg.watchdog_json) as fh:
            wd = json.load(fh)
        if not isinstance(wd, dict):
            raise ValueError("not a JSON object")
    except FileNotFoundError:
        return demoted, ["watchdog stale: %s missing -> cap %d" % (cfg.watchdog_json, demoted)]
    except Exception as ex:
        return demoted, ["watchdog stale: %s unreadable: %s -> cap %d" % (cfg.watchdog_json, str(ex)[:120], demoted)]
    if wd.get("trip") or wd.get("tripped") is True:   # refuses even when stale: the last word was "stop"
        return 0, ["watchdog TRIP %s (last_trip %s): every launch refused until the owner clears it"
                   % (json.dumps(wd.get("trip"), default=str)[:160], json.dumps(wd.get("last_trip"), default=str)[:80])]
    why = []
    try:
        age = time.time() - datetime.fromisoformat(str(wd["updated"])).timestamp()
    except Exception:
        try:
            age = time.time() - os.path.getmtime(cfg.watchdog_json)
        except OSError:
            age = None
    if age is None or age > cfg.watchdog_stale:
        why.append("watchdog stale: updated %s (> %g s)" % ("?" if age is None else "%.0f s ago" % age, cfg.watchdog_stale))
    if wd.get("warn") is not None:
        why.append("watchdog warn: %s" % json.dumps(wd.get("warn"), default=str)[:160])
    hs = wd.get("hang_strikes")
    try:
        hs_n = float(hs or 0)
    except (TypeError, ValueError):
        hs_n = 1.0
    if hs_n > 0:
        why.append("watchdog hang_strikes=%s" % hs)
    if wd.get("stuck_since"):
        why.append("watchdog stuck_since: %s" % json.dumps(wd.get("stuck_since"), default=str)[:160])
    if why:
        return demoted, [w + " -> cap %d" % demoted for w in why]
    return cfg.slots, []


def read_last_release(cfg):
    """Epoch of the last release recorded in <state dir>/last_release (0.0 if none)."""
    try:
        with open(cfg.last_release) as fh:
            return float(fh.read().split()[0])
    except Exception:
        return 0.0


def write_last_release(cfg):
    try:
        _atomic_write(cfg.last_release, round(time.time(), 3))
    except OSError:
        pass


class Throttle:
    """due(key) is True on the first call per key, then once every `every` seconds."""
    def __init__(self, every):
        self.every, self.last = every, {}

    def due(self, key):
        t = time.monotonic()
        prev = self.last.get(key)
        if prev is None or t - prev >= self.every:
            self.last[key] = t
            return True
        return False


def log_hold(log, thr, hold, **kv):
    what, info = hold
    if what == "paused":
        if thr.due("paused"):
            log("paused", reason=info.get("reason", ""), by=info.get("by", ""), echo=True, **kv)
    elif thr.due("stuck-engine"):
        for c in info:
            log("stuck-engine", pid=c["pid"], stat=c["stat"], kind=c["kind"], echo=True, **kv)


def capture_gate(cfg, log, me, m_enq, wait_timeout):
    """Capture launch gate, run while holding the slot. Returns (None, info) when clear to launch, else
    (outcome, info) with outcome paused | stuck-engine | cap-full-timeout | skipped-busy (CMD not run)."""
    util_on, cool_on = cfg.capture_util_max > 0, cfg.cooldown > 0
    if not util_on:
        log("capture-gate", gate="disabled", which="util", why="GPU_SLOT_CAPTURE_UTIL_MAX=0 explicit owner exception",
            echo=True)
    if not cool_on:
        log("capture-gate", gate="disabled", which="cooldown", why="GPU_SLOT_LAUNCH_COOLDOWN=0 explicit owner exception",
            echo=True)
    thr = Throttle(cfg.wait_log_every)
    m_gate = last_m = time.monotonic()
    streak0, samples, settle_spent = None, [], 0.0
    info = {"util_max": cfg.capture_util_max, "calm_s": cfg.capture_calm, "cooldown_s": cfg.cooldown,
            "settle_timeout_s": cfg.capture_settle_timeout, "client_cap": cfg.slots}
    while True:
        nowm = time.monotonic()
        dt, last_m = nowm - last_m, nowm
        table = proc_table(cfg)
        hold = hold_reason(cfg, table)
        foreign = foreign_gpu_clients(cfg, table, me) if hold is None else []
        cap, cap_why = watchdog_cap(cfg)
        info["client_cap"] = cap
        if cap_why:
            info["cap_why"] = "; ".join(cap_why)[:300]
        else:
            info.pop("cap_why", None)
        cap_full = hold is None and len(foreign) >= cap
        u = read_util(cfg)
        if not util_on:
            util_ok = True
        elif u is not None and u < cfg.capture_util_max:
            if streak0 is None:
                streak0, samples = nowm, []
            samples.append(u)
            util_ok = nowm - streak0 >= cfg.capture_calm
        else:
            streak0, samples, util_ok = None, [], False
        cool_left = max(0.0, cfg.cooldown - (time.time() - read_last_release(cfg))) if cool_on else 0.0
        streak_s = 0 if streak0 is None else round(nowm - streak0, 1)
        info.update(gate_wait_s=round(nowm - m_gate, 2), settle_s=round(settle_spent, 2),
                    foreign_clients=fmt_clients(foreign))
        if hold is None and not cap_full and util_ok and cool_left <= 0:
            info.update(samples=len(samples), util_min=min(samples) if samples else None,
                        util_max_seen=max(samples) if samples else None)
            return None, info
        if hold is not None or cap_full:
            waited = nowm - m_enq
            if wait_timeout > 0 and waited > wait_timeout:
                outcome = hold[0] if hold is not None else "cap-full-timeout"
                extra = {"cap": cap, "cap_why": info["cap_why"]} if cap_why and hold is None else {}
                log("wait-timeout", phase="gate", outcome=outcome, waited_s=round(waited, 1),
                    clients=fmt_clients(foreign), echo=True, **extra)
                return outcome, info
            if hold is not None:
                log_hold(log, thr, hold, phase="gate")
            elif thr.due("cap-full"):
                extra = {"cap_why": info["cap_why"]} if cap_why else {}
                log("wait", phase="cap-full", clients=fmt_clients(foreign), cap=cap,
                    waited_s=round(waited, 1), echo=True, **extra)
        else:
            settle_spent += dt
            if cfg.capture_settle_timeout > 0 and settle_spent > cfg.capture_settle_timeout:
                log("settle-timeout", util=u, need_util_lt=cfg.capture_util_max, streak_s=streak_s,
                    cooldown_left_s=round(cool_left, 1), settle_s=round(settle_spent, 1), outcome="skipped-busy",
                    echo=True)
                return "skipped-busy", info
            if thr.due("settle"):
                log("wait", phase="settle", util=u, need_util_lt=cfg.capture_util_max if util_on else "off",
                    calm_s=cfg.capture_calm, streak_s=streak_s, cooldown_left_s=round(cool_left, 1),
                    settle_s=round(settle_spent, 1), echo=True)
        time.sleep(cfg.poll)


def piece_from_cwd():
    m = re.match(re.escape(os.environ.get("LOOP_DIR", "/nonexistent")) + r"/([^/]+)", os.getcwd())
    if m:
        return m.group(1)
    m = re.match(r"$HOME/(spider-man-2[^/]*)", os.getcwd())
    return m.group(1) if m else os.path.basename(os.getcwd())


# ---------------------------------------------------------------- logging

class Logger:
    def __init__(self, cfg, cls, label):
        self.cfg, self.cls, self.label = cfg, cls, label

    def __call__(self, event, util="auto", echo=False, **kv):
        cfg = self.cfg
        if util == "auto":
            util = read_util(cfg)
        parts = [now_iso(), "pid=%d" % os.getpid(), "class=%s" % self.cls,
                 "label=%s" % self.label, "event=%s" % event, "util=%s" % fmt_util(util)]
        for k, v in kv.items():
            s = str(v)
            if re.search(r"[\s\"]", s) or s == "":
                s = json.dumps(s)
            parts.append("%s=%s" % (k, s))
        line = " ".join(parts) + "\n"
        try:
            fd = os.open(cfg.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
            try:
                os.write(fd, line.encode())
            finally:
                os.close(fd)
        except OSError:
            pass
        if echo and not cfg.quiet:
            sys.stderr.write("gpu_slot[%s/%s]: %s %s\n" % (self.cls, self.label, event,
                             " ".join("%s=%s" % (k, v) for k, v in kv.items())))
            sys.stderr.flush()


# ---------------------------------------------------------------- state records

def _atomic_write(path, obj):
    tmp = "%s.tmp%d" % (path, os.getpid())
    with open(tmp, "w") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def list_records(d):
    recs = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return recs
    for n in names:
        if not n.endswith(".json"):
            continue
        r = _read_json(os.path.join(d, n))
        if r is not None:
            r["_file"] = os.path.join(d, n)
            recs.append(r)
    return recs


def reap_stale(cfg, log):
    """Remove holder/queue records whose owner is dead. Returns number recovered."""
    n = 0
    for kind, d in (("holder", cfg.holders), ("waiter", cfg.queue)):
        for r in list_records(d):
            if not pid_alive(r.get("pid", -1), r.get("start", "")):
                try:
                    os.unlink(r["_file"])
                except OSError:
                    continue
                n += 1
                log("stale-recovered", kind=kind, dead_pid=r.get("pid"), dead_class=r.get("class"),
                    dead_label=r.get("label"), dead_slot=r.get("slot", ""),
                    orphan_child=r.get("child_pid", ""), echo=True)
    return n


def try_flock(path, mode):
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
        return fd
    except OSError as e:
        os.close(fd)
        if e.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
            return None
        raise


def release_fd(fd):
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


class Aborted(Exception):
    def __init__(self, sig):
        super().__init__("signal %d" % sig)
        self.sig = sig


# ---------------------------------------------------------------- acquire / run

def run_wrapped(cls, label, json_path, wait_timeout, cmd):
    cfg = Cfg()
    cfg.ensure_dirs()
    log = Logger(cfg, cls, label)
    me = os.getpid()
    my_start = proc_start(me)[1]
    cmd_text = " ".join(cmd)

    # re-entrancy: never deadlock against a lock this process tree already holds
    held = os.environ.get("GPU_SLOT_HELD")
    if held:
        if cls == "perf" and held == "capture":
            sys.stderr.write("gpu_slot: refusing perf inside a capture slot (would deadlock)\n")
            log("refused-nested", nested_in=held, echo=True)
            return 2
        log("nested-passthrough", nested_in=held, cmd=cmd_text[:200], echo=True)
        try:
            return subprocess.call(cmd)
        except FileNotFoundError:
            sys.stderr.write("gpu_slot: command not found: %s\n" % cmd[0])
            return 127

    state = {"sig": None, "child": None, "run_phase": False}

    def on_signal(signum, _frame):
        if not state["run_phase"]:
            raise Aborted(signum)
        state["sig"] = signum
        c = state["child"]
        if c is not None:
            try:
                os.killpg(c.pid, signum)
            except OSError:
                pass

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, on_signal)

    ticket = "%020d-%d" % (time.time_ns(), me)
    qfile = os.path.join(cfg.queue, ticket + ".json")
    hfile = os.path.join(cfg.holders, "%s-%d.json" % (cls, me))
    t_enq = time.time()
    m_enq = time.monotonic()
    _atomic_write(qfile, {"pid": me, "start": my_start, "class": cls, "label": label,
                          "since": now_iso(), "since_epoch": t_enq, "ticket": ticket,
                          "cmd": cmd_text[:300]})
    log("enqueue", cmd=cmd_text[:200], echo=False)

    fds = []      # held flock fds
    holder = {"pid": me, "start": my_start, "class": cls, "label": label, "cmd": cmd_text[:300],
              "state": "acquiring", "since": now_iso(), "since_epoch": t_enq, "slot": ""}
    child = None
    result = {"schema": "gpu_slot/1", "class": cls, "label": label, "pid": me, "cmd": cmd,
              "cwd": os.getcwd(), "queued_at": now_iso()}
    rc = 1
    try:
        # ---- phase 1: FIFO head + lock acquisition
        last_log = 0.0
        thr = Throttle(cfg.wait_log_every)
        while True:
            reap_stale(cfg, log)
            queue = [r for r in list_records(cfg.queue)]
            head = queue[0] if queue else None
            hold = hold_reason(cfg)          # PAUSED / stuck engine: nobody acquires
            if hold is not None:
                log_hold(log, thr, hold, phase="queue")
            elif head is None or head.get("pid") == me:
                got = None
                if cls == "capture":
                    got = try_acquire_capture(cfg)
                else:
                    got = try_acquire_perf(cfg)
                if got is not None:
                    fds, slot = got
                    holder["slot"] = slot
                    break
            waited = time.monotonic() - m_enq
            if wait_timeout > 0 and waited > wait_timeout:
                outcome = hold[0] if hold is not None else "wait-timeout"
                extra = {}
                if cls == "capture" and hold is None and getattr(cfg, "cap_why", None):
                    extra = {"cap": cfg.eff_slots, "cap_why": "; ".join(cfg.cap_why)[:300]}
                log("wait-timeout", waited_s=round(waited, 1), outcome=outcome, echo=True, **extra)
                result.update(exit_code=EX_TIMEOUT, outcome=outcome, wait_s=round(waited, 1),
                              exclusive=False, contaminated=True)
                write_result(cfg, json_path, result)
                return EX_TIMEOUT
            if waited - last_log >= cfg.wait_log_every or last_log == 0.0:
                ahead = [r for r in queue if r.get("pid") != me and r.get("ticket", "") < ticket]
                holders = list_records(cfg.holders)
                extra = {}
                if cls == "capture" and getattr(cfg, "cap_why", None):
                    extra = {"cap": cfg.eff_slots, "cap_why": "; ".join(cfg.cap_why)[:300]}
                log("wait", phase="queue", waited_s=round(waited, 1), ahead=len(ahead),
                    holders=",".join("%s:%s" % (h.get("class"), h.get("pid")) for h in holders),
                    streaming=str(streaming(cfg)).lower(),
                    echo=(last_log == 0.0 or waited - last_log >= cfg.wait_log_every), **extra)
                last_log = waited
            time.sleep(cfg.poll)
        try:
            os.unlink(qfile)
        except OSError:
            pass
        holder["state"] = "settling" if cls == "perf" else "gating"
        _atomic_write(hfile, holder)
        t_lock = time.time()
        m_lock = time.monotonic()
        log("acquire", slot=holder["slot"], waited_s=round(m_lock - m_enq, 1), phase="lock", echo=(cls == "capture"))

        # ---- phase 2 (perf only): drain + calm gate
        settle = {}
        if cls == "perf":
            streak0, streak_util, last_log = None, [], 0.0
            while True:
                u = read_util(cfg)
                fc = foreign_captures(cfg)
                hold = hold_reason(cfg)
                if hold is not None:
                    log_hold(log, thr, hold, phase="settle")
                ok = (u is not None and u < cfg.util_max and not fc and hold is None)
                nowm = time.monotonic()
                if ok:
                    if streak0 is None:
                        streak0, streak_util = nowm, []
                    streak_util.append(u)
                    if nowm - streak0 >= cfg.calm:
                        break
                else:
                    streak0, streak_util = None, []
                waited = nowm - m_enq
                if wait_timeout > 0 and waited > wait_timeout:
                    outcome = hold[0] if hold is not None else "wait-timeout"
                    log("wait-timeout", phase="settle", waited_s=round(waited, 1), util=u,
                        foreign_captures=len(fc), outcome=outcome, echo=True)
                    result.update(exit_code=EX_TIMEOUT, outcome=outcome, wait_s=round(waited, 1),
                                  exclusive=False, contaminated=True)
                    write_result(cfg, json_path, result)
                    return EX_TIMEOUT
                if nowm - m_lock - last_log >= cfg.wait_log_every or last_log == 0.0:
                    log("wait", phase="settle", waited_s=round(waited, 1), util=u,
                        need_util_lt=cfg.util_max, calm_s=cfg.calm,
                        streak_s=0 if streak0 is None else round(nowm - streak0, 1),
                        foreign_captures=",".join(str(p["pid"]) for p in fc), echo=True)
                    last_log = nowm - m_lock
                time.sleep(cfg.poll)
            settle = {"calm_s": cfg.calm, "util_max": cfg.util_max, "samples": len(streak_util),
                      "min": min(streak_util), "max": max(streak_util)}

        # ---- phase 2b (capture only): GPU client cap, PAUSED / stuck engines, util calm + cooldown
        gate = {}
        if cls == "capture":
            outcome, gate = capture_gate(cfg, log, me, m_enq, wait_timeout)
            if outcome is not None:
                waited = round(time.monotonic() - m_enq, 1)
                result.update(exit_code=EX_TIMEOUT, outcome=outcome, wait_s=waited, exclusive=False,
                              contaminated=True, contaminated_reasons=[outcome], capture_gate=gate,
                              slot=holder["slot"])
                write_result(cfg, json_path, result)
                return EX_TIMEOUT

        # ---- phase 3: run
        wait_s = round(time.monotonic() - m_enq, 2)
        util_before = read_util(cfg)
        table = proc_table(cfg)
        ue_before = unreal_procs(cfg, table)
        gpu_before = gpu_procs(cfg, table)
        gpu_before_info = {"total": len(gpu_before), "by_kind": by_kind(gpu_before),
                           "clients": fmt_clients(gpu_before)}
        exclusive = (cls == "perf")
        result.update(wait_s=wait_s, util_before=util_before, exclusive=exclusive,
                      slot=holder["slot"], settle=settle, capture_gate=gate, gpu_clients_before=gpu_before_info,
                      unreal_before={"instances": len(ue_before),
                                     "captures": sum(1 for p in ue_before if p["kind"] == "capture"),
                                     "editors": sum(1 for p in ue_before if p["kind"] == "editor")})
        live = streaming(cfg)
        cap = cfg.fps_cap_streaming if live else cfg.fps_cap
        kind = engine_kind(cmd)
        run_cmd, cap_applied = apply_fps_cap(cmd, cap, kind)
        result.update(streaming=live, fps_cap=cap, fps_cap_engine=kind, fps_cap_applied=cap_applied)
        log("fps-cap", engine=kind or "unknown", cap=cap, applied=str(cap_applied).lower(),
            streaming=str(live).lower(), echo=(kind == "unity" and cap > 0))
        env = dict(os.environ)
        env.update(GPU_SLOT_FPS_CAP=str(cap), GPU_SLOT_STREAMING="1" if live else "0")
        env.update(GPU_SLOT_HELD=cls, GPU_SLOT_LABEL=label, GPU_SLOT_WAIT_S=str(wait_s),
                   GPU_SLOT_UTIL_BEFORE=fmt_util(util_before),
                   GPU_SLOT_INSTANCES_BEFORE=str(len(gpu_before)),
                   GPU_SLOT_EXCLUSIVE="1" if exclusive else "0")
        if json_path:
            env["GPU_SLOT_JSON"] = json_path
        max_hold = cfg.max_hold[cls]
        mon = {"utils": [], "instances_max": len(ue_before), "gpu_max": len(gpu_before), "foreign": {},
               "stop": threading.Event()}

        def monitor():
            while not mon["stop"].wait(cfg.sample):
                u = read_util(cfg)
                if u is not None:
                    mon["utils"].append(u)
                tb = proc_table(cfg)
                ue = unreal_procs(cfg, tb)
                mine = descendants(tb, me)
                mon["instances_max"] = max(mon["instances_max"], len(ue))
                mon["gpu_max"] = max(mon["gpu_max"], len(gpu_procs(cfg, tb)))
                if cls == "perf":
                    for p in ue:
                        if p["kind"] == "capture" and p["pid"] not in mine:
                            mon["foreign"][p["pid"]] = p["cmd"][:200]

        mt = threading.Thread(target=monitor, daemon=True)
        state["run_phase"] = True
        t_start = time.time()
        m_start = time.monotonic()
        try:
            child = subprocess.Popen(run_cmd, env=env, start_new_session=True)
        except FileNotFoundError:
            sys.stderr.write("gpu_slot: command not found: %s\n" % cmd[0])
            result.update(exit_code=127, outcome="cmd-not-found")
            rc = 127
            child = None
        except PermissionError:
            sys.stderr.write("gpu_slot: command not executable: %s\n" % cmd[0])
            result.update(exit_code=126, outcome="cmd-not-executable")
            rc = 126
            child = None
        hold_killed = False
        if child is not None:
            state["child"] = child
            holder["child_pid"] = child.pid
            holder["state"] = "running"
            holder["run_since_epoch"] = t_start
            _atomic_write(hfile, holder)
            if cls == "capture":
                write_last_release(cfg)                  # a cold launch also starts the cooldown clock
            log("run", child_pid=child.pid, max_hold_s=max_hold, gpu_clients_before=len(gpu_before),
                gpu_clients_by_kind=fmt_kinds(gpu_before_info["by_kind"]), cmd=cmd_text[:200], echo=True)
            mt.start()
            while True:
                try:
                    rc = child.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if not hold_killed and max_hold > 0 and time.monotonic() - m_start > max_hold:
                    hold_killed = True
                    log("max-hold-exceeded", max_hold_s=max_hold, echo=True)
                    _killpg(child, signal.SIGTERM)
                    t_term = time.monotonic()
                    while child.poll() is None and time.monotonic() - t_term < 10:
                        time.sleep(0.2)
                    if child.poll() is None:
                        _killpg(child, signal.SIGKILL)
                    child.wait()
                    rc = EX_MAXHOLD
                    break
            mon["stop"].set()
            if rc is not None and rc < 0:
                rc = 128 + (-rc)
            _killpg(child, signal.SIGKILL, quiet=True)  # stragglers in the command's process group
            write_last_release(cfg)                      # cold-launch cooldown starts now
        t_end = time.time()
        util_after = read_util(cfg)
        utils = mon["utils"]
        reasons = []
        if cls != "perf":
            reasons.append("no-exclusive-lock")
        else:
            if util_before is None or util_before >= cfg.util_max:
                reasons.append("util-before-not-idle")
            if mon["foreign"]:
                reasons.append("foreign-capture-process-during-run")
            if hold_killed:
                reasons.append("max-hold-exceeded")
        result.update(
            exit_code=rc, outcome="max-hold-killed" if hold_killed else result.get("outcome", "ran"),
            acquired_at=datetime.fromtimestamp(t_lock).astimezone().isoformat(timespec="milliseconds"),
            started_at=datetime.fromtimestamp(t_start).astimezone().isoformat(timespec="milliseconds"),
            released_at=datetime.fromtimestamp(t_end).astimezone().isoformat(timespec="milliseconds"),
            hold_s=round(t_end - t_lock, 2), run_s=round(t_end - t_start, 2),
            util_after=util_after,
            util_during={"n": len(utils), "min": min(utils) if utils else None,
                         "avg": round(sum(utils) / len(utils), 1) if utils else None,
                         "max": max(utils) if utils else None},
            instances_before=len(ue_before), instances_max_during=mon["instances_max"],
            gpu_clients_max_during=mon["gpu_max"],
            foreign_capture_during=mon["foreign"],
            contaminated=bool(reasons), contaminated_reasons=reasons,
            perf_valid=(cls == "perf" and not reasons))
        write_result(cfg, json_path, result)
        log("release", exit=rc, hold_s=result["hold_s"], wait_s=wait_s, util_before=fmt_util(util_before),
            util_after=fmt_util(util_after), instances_before=len(ue_before),
            instances_max=mon["instances_max"], gpu_clients_before=len(gpu_before),
            gpu_clients_by_kind=fmt_kinds(gpu_before_info["by_kind"]), gpu_clients_max_during=mon["gpu_max"],
            contaminated=str(bool(reasons)).lower(),
            reasons=",".join(reasons), echo=True)
        return rc if rc is not None else 1
    except Aborted as a:
        log("aborted", signal=a.sig, echo=True)
        return 128 + a.sig
    finally:
        state["run_phase"] = False
        if child is not None and child.poll() is None:
            _killpg(child, signal.SIGTERM, quiet=True)
            time.sleep(0.3)
            _killpg(child, signal.SIGKILL, quiet=True)
        for fd in fds:
            release_fd(fd)
        for f in (qfile, hfile):
            try:
                os.unlink(f)
            except OSError:
                pass


def _killpg(child, sig, quiet=False):
    try:
        os.killpg(child.pid, sig)
    except OSError:
        pass


def try_acquire_capture(cfg):
    """Shared: SH on perf.lock (fails while a perf run holds/settles) + one free capture slot, and only while
    fewer capture slots are held (every capture.N.lock counted) than the effective cap: min(configured or
    streaming slots, watchdog_cap)."""
    cap, cfg.cap_why = watchdog_cap(cfg)
    slots = cfg.streaming_slots if streaming(cfg) else cfg.slots
    cfg.eff_slots = max(0, min(slots, cap))
    if cfg.eff_slots <= 0:
        return None
    sh = try_flock(cfg.perf_lock, fcntl.LOCK_SH)
    if sh is None:
        return None
    held, got = 0, None
    for i in range(max(cfg.slots, slots)):
        fd = try_flock(os.path.join(cfg.locks, "capture.%d.lock" % i), fcntl.LOCK_EX)
        if fd is None:
            held += 1
        elif got is None and i < slots:
            got = (fd, i)
        else:
            release_fd(fd)
    if got is not None and held < cfg.eff_slots:
        return [sh, got[0]], str(got[1])
    if got is not None:
        release_fd(got[0])
    release_fd(sh)
    return None


def try_acquire_perf(cfg):
    """Exclusive: EX on perf.lock (fails while any capture holds SH or another perf holds EX)."""
    fd = try_flock(cfg.perf_lock, fcntl.LOCK_EX)
    if fd is None:
        return None
    return [fd], "perf"


def write_result(cfg, json_path, result):
    if json_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
            _atomic_write(json_path, result)
        except OSError as e:
            sys.stderr.write("gpu_slot: cannot write %s: %s\n" % (json_path, e))
    try:
        with open(os.path.join(cfg.dir, "runs.jsonl"), "a") as fh:
            fh.write(json.dumps(result) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- status

def cmd_status(as_json=False):
    cfg = Cfg()
    cfg.ensure_dirs()
    util = read_util(cfg)
    holders = list_records(cfg.holders)
    queue = list_records(cfg.queue)
    tbl = proc_table(cfg)
    ue = unreal_procs(cfg, tbl)
    gpu = gpu_procs(cfg, tbl)
    stuck = stuck_clients(cfg, tbl)
    paused = read_paused(cfg)
    last_rel = read_last_release(cfg)
    for r in holders + queue:
        r["alive"] = pid_alive(r.get("pid", -1), r.get("start", ""))
    cap, cap_why = watchdog_cap(cfg)
    if as_json:
        print(json.dumps({"util": util, "util_max": cfg.util_max, "perf_ready_now": util is not None and util < cfg.util_max,
                          "holders": holders, "waiters": queue, "unreal": ue, "slots": cfg.slots,
                          "effective_slots": min(cfg.streaming_slots if streaming(cfg) else cfg.slots, cap),
                          "watchdog_cap": cap, "cap_why": cap_why,
                          "gpu_clients": gpu, "gpu_clients_by_kind": by_kind(gpu), "gpu_client_cap": cap,
                          "stuck": stuck, "paused": paused, "last_release_epoch": last_rel or None,
                          "capture_gate": {"util_max": cfg.capture_util_max, "calm_s": cfg.capture_calm,
                                           "cooldown_s": cfg.cooldown, "settle_timeout_s": cfg.capture_settle_timeout}},
                         indent=1))
        return 0
    nowe = time.time()
    if paused is not None:
        since = paused.get("since")
        ago = " for %ds" % (nowe - since) if isinstance(since, (int, float)) else ""
        bt = paused.get("boottime")
        stale = "  (set before the current boot)" if isinstance(bt, int) and bt != boottime() else ""
        print("PAUSED:        YES%s  by=%s  reason=%s%s   -> no class launches until `gpu_slot.py resume`" % (
            ago, paused.get("by", "?"), json.dumps(paused.get("reason", "")), stale))
    else:
        print("PAUSED:        no")
    print("GPU Device Utilization now: %s %%   (perf gate: < %g %% for %g consecutive s)   %s"
          % (fmt_util(util), cfg.util_max, cfg.calm,
             "-> below threshold" if util is not None and util < cfg.util_max else "-> NOT idle"))
    live_h = [h for h in holders if h["alive"]]
    perf_h = [h for h in live_h if h.get("class") == "perf"]
    cap_h = [h for h in live_h if h.get("class") == "capture"]
    print("Perf lock:     %s" % ("HELD by pid %s label=%s state=%s for %ds" % (
        perf_h[0]["pid"], perf_h[0].get("label"), perf_h[0].get("state"), nowe - perf_h[0].get("since_epoch", nowe))
        if perf_h else "free"))
    print("Watchdog cap:  %d of %d configured%s" % (cap, cfg.slots, ("   " + "; ".join(cap_why)) if cap_why else "   (healthy)"))
    print("Capture slots: %d/%d in use%s" % (len(cap_h), min(cfg.streaming_slots if streaming(cfg) else cfg.slots, cap),
          "   STREAMING flag set -> %d slot(s), captures %s, fps cap %d" % (
              cfg.streaming_slots, "WAIT" if cfg.streaming_slots <= 0 else "allowed", cfg.fps_cap_streaming)
          if streaming(cfg) else "   (fps cap %d)" % cfg.fps_cap))
    print("Holders (%d):" % len(holders))
    for h in holders:
        print("  %-7s slot=%-4s pid=%-6s label=%-12s state=%-9s for %5ds%s  cmd=%s" % (
            h.get("class"), h.get("slot", ""), h.get("pid"), h.get("label"), h.get("state"),
            nowe - h.get("since_epoch", nowe), "" if h["alive"] else "  STALE(pid dead)", h.get("cmd", "")[:90]))
    print("Waiters, FIFO (%d):" % len(queue))
    for i, w in enumerate(queue, 1):
        print("  %d. %-7s pid=%-6s label=%-12s waiting %5ds%s  cmd=%s" % (
            i, w.get("class"), w.get("pid"), w.get("label"), nowe - w.get("since_epoch", nowe),
            "" if w["alive"] else "  STALE(pid dead)", w.get("cmd", "")[:90]))
    print("Capture gate:  util < %s for %g s, cooldown %s since last release (%s), settle budget %g s" % (
        ("%g %%" % cfg.capture_util_max) if cfg.capture_util_max > 0 else "OFF(exception)", cfg.capture_calm,
        ("%g s" % cfg.cooldown) if cfg.cooldown > 0 else "OFF(exception)",
        ("%ds ago" % (nowe - last_rel)) if last_rel else "none recorded", cfg.capture_settle_timeout))
    kinds = by_kind(gpu)
    print("GPU clients: %d (%s)   [cap: a capture launches only while < %d foreign GPU clients run]" % (
        len(gpu), ", ".join("%s %d" % (k, kinds[k]) for k in GPU_KINDS if k in kinds) or "none", cap))
    for p in gpu:
        print("  pid=%-6s %-13s role=%-10s stat=%-4s wrapped=%-3s etime=%-11s project=%-14s cmd=%s" % (
            p["pid"], p["kind"], p["role"], p["stat"], "yes" if p["wrapped"] else "no", p["etime"],
            p["project"] or "?", p["cmd"][:90]))
    if stuck:
        print("STUCK ENGINES (state E/Z) -> nothing acquires: %s" % ", ".join(
            "pid=%s stat=%s kind=%s" % (p["pid"], p["stat"], p["kind"]) for p in stuck))
    ncap = sum(1 for p in ue if p["kind"] == "capture")
    print("Unreal editor processes: %d (%d capture/-game, %d editor)   [capture slots %d]" % (
        len(ue), ncap, len(ue) - ncap, cfg.slots))
    for p in ue:
        print("  pid=%-6s %-7s project=%-12s etime=%s" % (p["pid"], p["kind"], p["project"] or "?", p["etime"]))
    under = set()
    for h in live_h:
        under |= descendants(tbl, h["pid"])
    unwrapped = [p for p in ue if p["kind"] == "capture" and p["pid"] not in under]
    if unwrapped:
        print("NOTE: %d capture process(es) not under a gpu_slot holder (unwrapped -> perf runs will wait / be contaminated): %s"
              % (len(unwrapped), ",".join(str(p["pid"]) for p in unwrapped)))
    return 0


# ---------------------------------------------------------------- main

def usage(code=2):
    sys.stderr.write(__doc__.split("Locking =")[0])
    sys.exit(code)


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        usage(0 if len(argv) >= 2 else 2)
    sub = argv[1]
    if sub == "status":
        return cmd_status("--json" in argv[2:])
    if sub == "cap":
        cfg = Cfg()
        cap, why = watchdog_cap(cfg)
        print("cap %d" % cap)
        for w in why:
            print("  " + w)
        return 0 if cap > 0 else 3
    if sub in ("pause", "resume"):
        cfg = Cfg()
        cfg.ensure_dirs()
        by = "%d %s" % (os.getppid(), _run(["ps", "-o", "command=", "-p", str(os.getppid())], 5).strip()[:200])
        log = Logger(cfg, "admin", os.environ.get("GPU_SLOT_LABEL") or "manual")
        if sub == "pause":
            reason = " ".join(argv[2:]).strip() or "manual pause"
            created, rec = write_paused(cfg, reason, by)
            if not created:
                print("already PAUSED by=%s reason=%s (left unchanged)" % (rec.get("by", "?"), json.dumps(rec.get("reason", ""))))
                return 0
            log("pause", reason=reason, by=by, echo=False)
            print("PAUSED: no gpu_slot class launches until `gpu_slot.py resume` (reason: %s)" % reason)
            return 0
        cur = read_paused(cfg)
        if cur is None:
            print("not paused")
            return 0
        try:
            os.unlink(cfg.paused_flag)
        except FileNotFoundError:
            pass
        since = cur.get("since")
        log("resume", by=by, was_reason=cur.get("reason", ""), was_by=cur.get("by", ""),
            paused_s=round(time.time() - since, 1) if isinstance(since, (int, float)) else "", echo=False)
        print("resumed (was paused by=%s reason=%s)" % (cur.get("by", "?"), json.dumps(cur.get("reason", ""))))
        return 0
    if sub == "util":
        u = read_util(Cfg())
        print(fmt_util(u))
        return 0 if u is not None else 1
    if sub == "summary":
        if len(argv) < 3:
            usage()
        r = _read_json(argv[2])
        if r is None:
            sys.stderr.write("gpu_slot: cannot read %s\n" % argv[2])
            return 1
        ud = r.get("util_during") or {}
        print("GPU-LOCK: class=%s exclusive=%s util_before=%s%% util_after=%s%% util_during_avg=%s%% wait_s=%s "
              "instances_before=%s instances_max=%s gpu_clients_before=%s gpu_clients_max=%s outcome=%s contaminated=%s%s" % (
                  r.get("class"), "yes" if r.get("exclusive") else "no", fmt_util(r.get("util_before")),
                  fmt_util(r.get("util_after")), ud.get("avg"), r.get("wait_s"), r.get("instances_before"),
                  r.get("instances_max_during"), (r.get("gpu_clients_before") or {}).get("total"),
                  r.get("gpu_clients_max_during"), r.get("outcome"), str(bool(r.get("contaminated"))).lower(),
                  " (%s)" % ",".join(r.get("contaminated_reasons") or []) if r.get("contaminated") else ""))
        return 0
    if sub not in ("capture", "perf"):
        sys.stderr.write("gpu_slot: unknown subcommand %r\n" % sub)
        usage()
    args = argv[2:]
    label = os.environ.get("GPU_SLOT_LABEL") or piece_from_cwd()
    json_path, timeout = os.environ.get("GPU_SLOT_JSON") or None, None
    i = 0
    while i < len(args) and args[i] != "--":
        a = args[i]
        if a == "--label" and i + 1 < len(args):
            label = args[i + 1]; i += 2
        elif a == "--json" and i + 1 < len(args):
            json_path = args[i + 1]; i += 2
        elif a == "--timeout" and i + 1 < len(args):
            timeout = float(args[i + 1]); i += 2
        else:
            sys.stderr.write("gpu_slot: unknown option %r\n" % a)
            usage()
    cmd = args[i + 1:]
    if i >= len(args) or not cmd:
        sys.stderr.write("gpu_slot: missing '-- <command...>'\n")
        usage()
    cfg = Cfg()
    return run_wrapped(sub, label, json_path, timeout if timeout is not None else cfg.wait_timeout[sub], cmd)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(130)
