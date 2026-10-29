#!/usr/bin/env python3
"""gpu_watchdog: headless GPU health watchdog for the Mac Studio (independent of every loop).

  gpu_watchdog.py                 loop forever (LaunchAgent / LaunchDaemon entry point)
  gpu_watchdog.py --once          one sample, print the state JSON, exit 0 healthy / 3 tripped
  gpu_watchdog.py --dry-run       log what it would do (stderr only), take no action, write nothing
  gpu_watchdog.py status          print the last state JSON

Why: on 2026-10-29 03:15 the GPU driver wedged under 5+ GPU clients; an Unreal launch sat in `E` state
unkillable, WindowServer's watchdog logged the owner out at 03:28, ioreg recoveryCount stayed 0, another
loop launched Godot beside the stuck process at 03:30, and nothing recovered until a power-button reboot at
10:17. Nothing watched the GPU independently of the loops. This does.

Each sample (every GPU_WATCHDOG_INTERVAL s, default 15):
  1. Metal probe: GPU_WATCHDOG_PROBE (default <dir>/bin/metal_probe, one 1 MiB blit, prints "ok <ms>") in its
     own session with GPU_WATCHDOG_PROBE_TIMEOUT (default 5 s). On timeout its group gets SIGKILL and the
     sample is a hang even if the kill cannot complete (a probe stuck in the driver can be unkillable). The
     watchdog never blocks on it and never starts a second probe while an earlier one is still alive (that
     sample is also a hang). Probe missing = "absent": the stuck-client rule still works.
  2. `ioreg -r -d 1 -c IOAccelerator`: max "Device Utilization %", summed "recoveryCount".
  3. GPU clients via gpu_slot.gpu_procs(cfg) (or unreal_procs + `ps` stat); stuck = stat starts with E or Z.
  4. gpu_slot holders from <dir>/holders/*.json.
  Every external command runs bounded and in its own session, so a wedged driver cannot hang the watchdog.

Trips:
  wedge             probe hangs on 3 consecutive samples, OR a stuck GPU client persists >= GPU_WATCHDOG_STUCK_SECONDS
                    (default 60). Actions: (a) write <dir>/PAUSED (gpu_slot refuses launches) if absent;
                    (b) SIGTERM the process group of the newest live `capture` holder's child_pid (never perf,
                    never SIGKILL); (c) notify once, then every GPU_WATCHDOG_RENOTIFY s (default 1800) while
                    tripped, via GPU_WATCHDOG_NOTIFY_CMD (message as argv) or iMessage to GPU_WATCHDOG_IMESSAGE_TO;
                    <dir>/ALERT.txt is always written. Notification failure is logged, never fatal.
  unregistered-load util >= 99 for >= GPU_WATCHDOG_PIN_SECONDS (default 300) with zero live holders: log + state only.
Recovery: probe passes 3 consecutive samples and no stuck client -> log `recovered`. PAUSED is NEVER removed
  (owner rule: never auto-resume), except PAUSED written by this watchdog in an earlier boot (its `boottime`
  differs from kern.boottime): after 3 passing probes it is removed and `paused-cleared-after-reboot` is logged.

Self-reboot (DEFAULT OFF, not approved): only when BOTH GPU_WATCHDOG_REBOOT=1 is in the environment AND
  <dir>/REBOOT_OK exists. Fires when the wedge is tripped, the probe is still hanging, and (a stuck client
  exists OR recoveryCount is unchanged since the trip) continuously for GPU_WATCHDOG_REBOOT_GRACE s
  (default 600) after the first notification (which announces the reboot). Runs `sudo -n /sbin/shutdown -r now`
  (GPU_WATCHDOG_SUDO overrides `sudo`, for tests). It needs this sudoers entry, added by the owner with
  `sudo visudo -f /etc/sudoers.d/gpu-watchdog` (the installer never adds it):
      midir ALL=(root) NOPASSWD: /sbin/shutdown -r now
  With either opt-in missing it logs `reboot=disabled` once per trip and never calls shutdown.

Files (dir = $GPU_LOCK_DIR or ~/.cache/gpu-slot): gpu_watchdog.log (one key=value line per sample, rotated at
5 MB), gpu_watchdog.json (state), PAUSED, ALERT.txt, REBOOT_OK (owner-created opt-in).
Test hooks: GPU_WATCHDOG_MOCK_IOREG_FILE (ioreg text), GPU_WATCHDOG_MOCK_STUCK_FILE (lines "pid stat kind";
replaces client enumeration), GPU_WATCHDOG_MOCK_BOOTTIME, GPU_WATCHDOG_OSASCRIPT (osascript stand-in).
Python 3 stdlib only.
"""
import glob
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
E = os.environ


def _f(name, default):
    try:
        return float(E.get(name) or default)
    except ValueError:
        sys.stderr.write("gpu_watchdog: bad %s=%r, using %s\n" % (name, E.get(name), default))
        return float(default)


DIR = E.get("GPU_LOCK_DIR") or os.path.expanduser("~/.cache/gpu-slot")
LOG = os.path.join(DIR, "gpu_watchdog.log")
STATE = os.path.join(DIR, "gpu_watchdog.json")
PAUSED = os.path.join(DIR, "PAUSED")
ALERT = os.path.join(DIR, "ALERT.txt")
REBOOT_OK = os.path.join(DIR, "REBOOT_OK")
HOLDERS = os.path.join(DIR, "holders")
INTERVAL = _f("GPU_WATCHDOG_INTERVAL", 15)
PROBE = E.get("GPU_WATCHDOG_PROBE") or os.path.join(DIR, "bin", "metal_probe")
PROBE_TIMEOUT = _f("GPU_WATCHDOG_PROBE_TIMEOUT", 5)
STUCK_SECONDS = _f("GPU_WATCHDOG_STUCK_SECONDS", 60)
PIN_SECONDS = _f("GPU_WATCHDOG_PIN_SECONDS", 300)
RENOTIFY = _f("GPU_WATCHDOG_RENOTIFY", 1800)
REBOOT_GRACE = _f("GPU_WATCHDOG_REBOOT_GRACE", 600)
NOTIFY_CMD = E.get("GPU_WATCHDOG_NOTIFY_CMD") or ""
IMESSAGE_TO = E.get("GPU_WATCHDOG_IMESSAGE_TO") or "7088608874"
OSASCRIPT = E.get("GPU_WATCHDOG_OSASCRIPT") or "osascript"
SUDO = E.get("GPU_WATCHDOG_SUDO") or "sudo"
MOCK_IOREG = E.get("GPU_WATCHDOG_MOCK_IOREG_FILE") or ""
MOCK_STUCK = E.get("GPU_WATCHDOG_MOCK_STUCK_FILE") or ""
MOCK_BOOT = E.get("GPU_WATCHDOG_MOCK_BOOTTIME") or ""
STRIKES = 3            # consecutive probe hangs that trip / passes that recover
CMD_TIMEOUT = 10.0     # ioreg / ps / sysctl
CLIENT_TIMEOUT = 20.0  # gpu_slot client enumeration (thread)
NOTIFY_TIMEOUT = 30.0
LOG_MAX = 5 * 1024 * 1024
FALLBACK_GPU_COMM = re.compile(r"/MacOS/UnrealEditor$|[Gg]odot|/Unity\.app/|Blender\.app|(^|/)blender$")

DRY = False
STOP = threading.Event()
_ABANDONED = []        # Popen objects we SIGKILLed but could not reap yet (stuck in the kernel)


# ---------------------------------------------------------------- logging / io

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _fmt(v):
    s = "" if v is None else str(v)
    return json.dumps(s) if (s == "" or re.search(r"[\s\"]", s)) else s


def log(event, echo=False, **kv):
    line = " ".join([now_iso(), "pid=%d" % os.getpid(), "event=%s" % event] +
                    ["%s=%s" % (k, _fmt(v)) for k, v in kv.items()])
    if DRY:
        sys.stderr.write("[dry-run] " + line + "\n")
        sys.stderr.flush()
        return
    try:
        os.makedirs(DIR, exist_ok=True)
        try:
            if os.path.getsize(LOG) > LOG_MAX:
                os.replace(LOG, LOG + ".1")
        except OSError:
            pass
        fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
        try:
            os.write(fd, (line + "\n").encode())
        finally:
            os.close(fd)
    except OSError:
        pass
    if echo:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


def atomic_write(path, text):
    if DRY:
        return
    tmp = "%s.tmp%d" % (path, os.getpid())
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def reap_abandoned():
    for p in list(_ABANDONED):
        try:
            if p.poll() is not None:
                _ABANDONED.remove(p)
        except Exception:
            _ABANDONED.remove(p)


def bounded(argv, timeout):
    """Run argv in its own session; never block past timeout (+1 s reap attempt).
    Returns (returncode|None, stdout, status) with status in ok|timeout|oserror."""
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    except OSError:
        return None, "", "oserror"
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or "", "ok"
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            p.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            _ABANDONED.append(p)
        try:
            p.stdout.close()
        except Exception:
            pass
        return None, "", "timeout"


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False


def boottime():
    if MOCK_BOOT:
        return int(MOCK_BOOT)
    rc, out, _ = bounded(["sysctl", "-n", "kern.boottime"], CMD_TIMEOUT)
    m = re.search(r"sec\s*=\s*(\d+)", out)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- sample collection

def run_probe(state):
    """-> (result ok|hang|error|absent, ms or None, why)."""
    # A probe from an earlier sample (or an earlier watchdog process) that is still alive is stuck in the
    # driver: count a hang and do not start another one on top of it.
    alive = [pid for pid in state.get("stuck_probe_pids", []) if pid_alive(pid)]
    reap_abandoned()
    alive = sorted(set(alive) | {p.pid for p in _ABANDONED})
    state["stuck_probe_pids"] = alive
    if alive:
        return "hang", None, "previous-probe-alive:%s" % ",".join(map(str, alive))
    if not (os.path.isfile(PROBE) and os.access(PROBE, os.X_OK)):
        return "absent", None, ""
    t0 = time.monotonic()
    rc, out, st = bounded([PROBE], PROBE_TIMEOUT)
    wall = int((time.monotonic() - t0) * 1000)
    if st == "timeout":
        reap_abandoned()
        state["stuck_probe_pids"] = sorted({p.pid for p in _ABANDONED})
        return "hang", wall, "timeout"
    m = re.match(r"\s*ok\s+(\d+)", out)
    if rc == 0 and m:
        return "ok", int(m.group(1)), ""
    return "error", wall, (out.strip()[:80] or "rc=%s" % rc)


def read_ioreg():
    if MOCK_IOREG:
        try:
            with open(MOCK_IOREG) as fh:
                out = fh.read()
        except OSError:
            out = ""
    else:
        _, out, _ = bounded(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], CMD_TIMEOUT)
    utils = [int(x) for x in re.findall(r'"Device Utilization %"\s*=\s*(\d+)', out)]
    recs = [int(x) for x in re.findall(r'"recoveryCount"\s*=\s*(\d+)', out)]
    return (max(utils) if utils else None), (sum(recs) if recs else None)


_client_job = {"thread": None, "result": None}


def _enumerate_clients():
    try:
        sys.path.insert(0, HERE)
        sys.dont_write_bytecode = True   # no __pycache__ in the repo or <dir>/bin
        import gpu_slot  # noqa: E402  (maintained by the gpu_slot owner; may be mid-edit)
        cfg = gpu_slot.Cfg()
        if hasattr(gpu_slot, "gpu_procs"):
            res = [{"pid": int(p["pid"]), "stat": str(p.get("stat", "")), "kind": p.get("kind", "?"),
                    "cmd": str(p.get("cmd", ""))[:160]} for p in gpu_slot.gpu_procs(cfg)]
            return res, "gpu_procs"
        ue = gpu_slot.unreal_procs(cfg)
        src = "unreal_procs+ps"
    except BaseException as exc:  # includes SystemExit from a bad GPU_SLOT_* env
        ue, src = [], "ps-only(%s)" % type(exc).__name__
    rc, out, _ = bounded(["ps", "-axww", "-o", "pid=,stat=,comm="], CMD_TIMEOUT)
    stat, comm = {}, {}
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)$", line)
        if m:
            stat[int(m.group(1))] = m.group(2)
            comm[int(m.group(1))] = m.group(3).strip()
    res, seen = [], set()
    for p in ue:
        pid = int(p["pid"])
        seen.add(pid)
        res.append({"pid": pid, "stat": stat.get(pid, ""), "kind": p.get("kind", "unreal"),
                    "cmd": str(p.get("cmd", ""))[:160]})
    for pid, c in comm.items():
        if pid not in seen and FALLBACK_GPU_COMM.search(c):
            res.append({"pid": pid, "stat": stat[pid], "kind": "engine", "cmd": c[:160]})
    return res, src


def gpu_clients():
    """-> (clients list, source). Runs enumeration in a thread so a hung `ps` cannot hang the watchdog."""
    if MOCK_STUCK:
        res = []
        try:
            with open(MOCK_STUCK) as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) >= 2:
                        res.append({"pid": int(parts[0]), "stat": parts[1],
                                    "kind": parts[2] if len(parts) > 2 else "?", "cmd": "mock"})
        except OSError:
            pass
        return res, "mock"
    job = _client_job
    if job["thread"] is not None and job["thread"].is_alive():
        return [], "enumeration-still-running"
    box = {}

    def work():
        box["r"] = _enumerate_clients()
    t = threading.Thread(target=work, daemon=True)
    job["thread"] = t
    t.start()
    t.join(CLIENT_TIMEOUT)
    if t.is_alive():
        return [], "enumeration-timeout"
    return box.get("r", ([], "enumeration-failed"))


def is_stuck(stat):
    return stat[:1] in ("E", "Z")


def live_holders():
    out = []
    for path in sorted(glob.glob(os.path.join(HOLDERS, "*.json"))):
        r = read_json(path)
        if isinstance(r, dict) and pid_alive(r.get("pid", -1)):
            out.append({k: r.get(k) for k in ("pid", "class", "label", "child_pid", "run_since_epoch")})
    return out


# ---------------------------------------------------------------- actions

def reboot_gate():
    env_ok = E.get("GPU_WATCHDOG_REBOOT") == "1"
    file_ok = os.path.exists(REBOOT_OK)
    reason = "" if (env_ok and file_ok) else ",".join(
        x for x, ok in (("env-GPU_WATCHDOG_REBOOT-not-1", env_ok), ("REBOOT_OK-missing", file_ok)) if not ok)
    return env_ok and file_ok, reason


def write_paused(reason, details, boot):
    cur = read_json(PAUSED) if os.path.exists(PAUSED) else None
    if os.path.exists(PAUSED):
        # Our own PAUSED from an earlier boot is re-stamped so it cannot be cleared as "after reboot".
        if not (isinstance(cur, dict) and cur.get("by") == "gpu_watchdog" and cur.get("boottime") != boot):
            by = cur.get("by") if isinstance(cur, dict) else "unreadable"
            log("action", action="paused", result="already-present", by=by)
            return "already-present"
    body = {"since": round(time.time(), 3), "since_iso": now_iso(), "by": "gpu_watchdog", "reason": reason,
            "details": details, "boottime": boot}
    if DRY:
        log("action", action="paused", result="would-write", reason=reason)
        return "would-write"
    try:
        atomic_write(PAUSED, json.dumps(body, indent=1) + "\n")
        log("action", action="paused", result="written", reason=reason, echo=True)
        return "written"
    except OSError as exc:
        log("action", action="paused", result="error", error=str(exc), echo=True)
        return "error"


def sigterm_newest_capture(holders):
    caps = [h for h in holders if h.get("class") == "capture" and h.get("child_pid") and pid_alive(h["child_pid"])]
    if not caps:
        log("action", action="sigterm-capture", result="none")
        return {"result": "none"}
    h = max(caps, key=lambda x: float(x.get("run_since_epoch") or 0))
    child = int(h["child_pid"])
    try:
        pgid = os.getpgid(child)
    except OSError:
        pgid = None
    # gpu_slot starts the child as its own session leader; only signal the group when that holds, so a
    # non-leader child never takes the wrapper (or the agent) down with it.
    target = "group" if pgid == child else "pid"
    info = {"holder_pid": h.get("pid"), "label": h.get("label"), "child_pid": child, "target": target}
    if DRY:
        log("action", action="sigterm-capture", result="would-send", **info)
        return dict(info, result="would-send")
    try:
        if target == "group":
            os.killpg(child, signal.SIGTERM)
        else:
            os.kill(child, signal.SIGTERM)
        res = "sent"
    except OSError as exc:
        res = "error:%s" % exc.__class__.__name__
    log("action", action="sigterm-capture", result=res, echo=True, **info)
    return dict(info, result=res)


def imessage(text, to):
    """Same AppleScript pattern as ~/skills/clipfarm-cli/imessage.py."""
    esc = text.replace("\\", "\\\\").replace('"', '\\"')
    script = ('\n    tell application "Messages"\n        set svc to 1st account whose service type = iMessage\n'
              '        send "%s" to participant "%s" of svc\n    end tell' % (esc, to))
    rc, _, st = bounded([OSASCRIPT, "-e", script], NOTIFY_TIMEOUT)
    if rc == 0:
        return "imessage-sent"
    alt = 'tell application "Messages" to send "%s" to buddy "%s"' % (esc, to)
    rc2, _, st2 = bounded([OSASCRIPT, "-e", alt], NOTIFY_TIMEOUT)
    return "imessage-sent-buddy" if rc2 == 0 else "imessage-failed:%s/%s" % (st if rc is None else rc,
                                                                             st2 if rc2 is None else rc2)


def notify(msg):
    if not DRY:
        try:
            atomic_write(ALERT, "%s\n%s\n" % (now_iso(), msg))
        except OSError as exc:
            log("action", action="alert-file", result="error", error=str(exc))
    if DRY:
        log("action", action="notify", result="would-send", via="cmd" if NOTIFY_CMD else "imessage", message=msg)
        return "would-send"
    try:
        if NOTIFY_CMD:
            rc, _, st = bounded(shlex.split(NOTIFY_CMD) + [msg], NOTIFY_TIMEOUT)
            res = "cmd-ok" if rc == 0 else "cmd-failed:%s" % (st if rc is None else rc)
        else:
            res = imessage(msg, IMESSAGE_TO)
    except Exception as exc:  # never fatal
        res = "error:%s" % exc.__class__.__name__
    log("action", action="notify", result=res, message=msg, echo=True)
    return res


def do_reboot():
    argv = [SUDO, "-n", "/sbin/shutdown", "-r", "now"]
    if DRY:
        log("action", action="reboot", result="would-run", cmd=" ".join(argv))
        return "would-run"
    log("action", action="reboot", result="running", cmd=" ".join(argv), echo=True)
    rc, _, st = bounded(argv, 30)
    res = "ok" if rc == 0 else "failed:%s" % (st if rc is None else rc)
    log("action", action="reboot", result=res, echo=True)
    return res


# ---------------------------------------------------------------- one sample

def fresh_state(boot):
    return {"schema": "gpu_watchdog/1", "boottime": boot, "hang_strikes": 0, "pass_streak": 0,
            "stuck_since": {}, "pin_since": None, "warn": None, "stuck_probe_pids": [], "trip": None,
            "last_trip": None, "reboot_disabled_logged": False}


def sample(state):
    now = time.time()
    boot = state["boottime"]
    probe, ms, why = run_probe(state)
    util, rec = read_ioreg()
    clients, csrc = gpu_clients()
    holders = live_holders()

    if probe in ("hang", "error"):      # a failing probe (GPU error status) is a strike like a hang
        state["hang_strikes"] += 1
        state["pass_streak"] = 0
    elif probe in ("ok", "absent"):   # absent: no probe installed, the stuck-client rule carries recovery
        state["hang_strikes"] = 0
        state["pass_streak"] += 1

    prev = state.get("stuck_since") or {}
    stuck, since = [], {}
    for c in clients:
        if is_stuck(c["stat"]):
            k = str(c["pid"])
            since[k] = prev.get(k, now)
            stuck.append(dict(c, age_s=round(now - since[k], 1)))
    state["stuck_since"] = since
    long_stuck = [c for c in stuck if c["age_s"] >= STUCK_SECONDS]

    state.update(updated=now_iso(), probe={"result": probe, "ms": ms, "why": why, "path": PROBE},
                 util=util, recovery_count=rec, clients=clients, clients_source=csrc, stuck=stuck,
                 holders=holders, dry_run=DRY)

    # unregistered load: pinned GPU with nobody holding a slot
    if util is not None and util >= 99 and not holders:
        state["pin_since"] = state.get("pin_since") or now
        if now - state["pin_since"] >= PIN_SECONDS and not state.get("warn"):
            state["warn"] = {"type": "unregistered-load", "since": now_iso(), "util": util}
            log("warn", type="unregistered-load", util=util, pinned_s=round(now - state["pin_since"], 1),
                clients=",".join("%s:%s" % (c["kind"], c["pid"]) for c in clients), echo=True)
    else:
        if state.get("warn"):
            log("warn-cleared", type="unregistered-load", util=util)
        state["pin_since"], state["warn"] = None, None

    reasons = []
    if state["hang_strikes"] >= STRIKES:
        reasons.append("probe-hang x%d" % state["hang_strikes"])
    for c in long_stuck:
        reasons.append("stuck-client pid=%s stat=%s kind=%s for %ds" % (c["pid"], c["stat"], c["kind"], c["age_s"]))
    wedge = bool(reasons)
    trip = state.get("trip")
    host = socket.gethostname().split(".")[0]
    armed, gate_why = reboot_gate()

    if wedge and not trip:
        reason = "; ".join(reasons)
        details = {"probe": state["probe"], "util": util, "recovery_count": rec, "stuck": stuck,
                   "holders": holders, "clients": len(clients)}
        log("trip", type="wedge", reason=reason, util=util, recovery=rec, echo=True)
        trip = state["trip"] = {"type": "wedge", "reason": reason, "since": now_iso(), "since_epoch": now,
                                "recovery_at_trip": rec, "first_notify": None, "last_notify": None,
                                "notify_count": 0, "reboot": {"armed": armed, "cond_since": None,
                                                              "attempted": None}}
        trip["paused"] = write_paused(reason, details, boot)
        trip["sigterm"] = sigterm_newest_capture(holders)
        if armed:
            log("reboot", reboot="armed", grace_s=REBOOT_GRACE, echo=True)
        else:
            log("reboot", reboot="disabled", why=gate_why)

    if trip:
        trip["reboot"]["armed"] = armed
        due = trip["last_notify"] is None or now - trip["last_notify"] >= RENOTIFY
        if due:
            if armed:
                tail = ("Self-reboot ARMED: the Mac reboots in ~%ds unless the GPU recovers." % REBOOT_GRACE)
            else:
                tail = "Self-reboot disabled: reboot by hand if it does not recover."
            msg = ("GPU watchdog on %s: GPU WEDGE since %s (%s). PAUSED written, gpu_slot refuses launches. "
                   "util=%s recoveryCount=%s probe=%s. %s"
                   % (host, trip["since"][11:19], trip["reason"], util, rec, probe, tail))
            if trip["notify_count"]:
                msg = "[repeat %d] " % trip["notify_count"] + msg
            trip["notify_result"] = notify(msg)
            trip["last_notify"] = now
            trip["first_notify"] = trip["first_notify"] or now
            trip["notify_count"] += 1

        # self-reboot evaluation (logged every sample while tripped)
        unchanged = rec is None or rec == trip.get("recovery_at_trip")
        cond = probe == "hang" and (bool(stuck) or unchanged)
        rb = trip["reboot"]
        if cond and trip["first_notify"]:
            rb["cond_since"] = rb["cond_since"] or max(now, trip["first_notify"])
        else:
            rb["cond_since"] = None
        if rb["cond_since"] and not rb["attempted"]:
            held = now - rb["cond_since"]
            if held >= REBOOT_GRACE:
                if armed:
                    rb["attempted"] = now_iso()
                    rb["result"] = do_reboot()
                elif not rb.get("disabled_logged"):
                    rb["disabled_logged"] = True
                    log("reboot", reboot="disabled", decision="would-reboot-now-if-enabled",
                        held_s=round(held, 1), why=gate_why)
            elif armed:
                log("reboot", decision="waiting", held_s=round(held, 1), grace_s=REBOOT_GRACE)

        if state["pass_streak"] >= STRIKES and not stuck:
            log("recovered", after_s=round(now - trip["since_epoch"], 1), paused_kept=os.path.exists(PAUSED),
                echo=True)
            trip["recovered"] = now_iso()
            if not DRY:
                try:
                    with open(ALERT, "a") as fh:
                        fh.write("%s RECOVERED (PAUSED kept: resume by hand)\n" % now_iso())
                except OSError:
                    pass
                notify("GPU watchdog on %s: GPU RECOVERED after %ds (%s). PAUSED kept: resume by hand with gpu_slot resume."
                       % (host, now - trip["since_epoch"], trip["reason"]))
            state["last_trip"], state["trip"], trip = trip, None, None

    # only case PAUSED is ever removed: written by this watchdog in an earlier boot, GPU healthy now
    if not trip and state["pass_streak"] >= STRIKES and not stuck and os.path.exists(PAUSED):
        p = read_json(PAUSED)
        if isinstance(p, dict) and p.get("by") == "gpu_watchdog" and boot is not None \
                and p.get("boottime") not in (None, boot):
            if DRY:
                log("paused-cleared-after-reboot", result="would-remove", paused_boot=p.get("boottime"), boot=boot)
            else:
                try:
                    os.remove(PAUSED)
                    log("paused-cleared-after-reboot", paused_boot=p.get("boottime"), boot=boot, echo=True)
                except OSError as exc:
                    log("paused-cleared-after-reboot", result="error", error=str(exc))

    state["tripped"] = bool(state.get("trip"))
    state["paused_present"] = os.path.exists(PAUSED)
    log("sample", probe=probe, probe_ms=ms if ms is not None else "?", util="?" if util is None else util,
        recovery="?" if rec is None else rec, clients=len(clients), csrc=csrc, stuck=len(stuck),
        holders=len(holders), strikes=state["hang_strikes"], passes=state["pass_streak"],
        tripped=str(state["tripped"]).lower(), warn=(state.get("warn") or {}).get("type", "none"))
    return state


def load_state():
    boot = boottime()
    st = read_json(STATE)
    if not isinstance(st, dict) or st.get("schema") != "gpu_watchdog/1" or st.get("boottime") != boot:
        st = fresh_state(boot)   # new boot: counters, trip and stuck-probe pids from the old boot are void
    base = fresh_state(boot)
    for k, v in base.items():
        st.setdefault(k, v)
    return st


def save_state(st):
    if DRY:
        return
    try:
        os.makedirs(DIR, exist_ok=True)
        atomic_write(STATE, json.dumps(st, indent=1, default=str) + "\n")
    except OSError as exc:
        log("state-write-error", error=str(exc))


# ---------------------------------------------------------------- main

def main(argv):
    global DRY
    args = argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    if args[:1] == ["status"]:
        st = read_json(STATE)
        print(json.dumps(st if st is not None else {}, indent=1, default=str))
        return 0 if st is not None else 1
    unknown = [a for a in args if a not in ("--once", "--dry-run")]
    if unknown:
        sys.stderr.write("gpu_watchdog: unknown argument(s) %s (see --help)\n" % " ".join(unknown))
        return 2
    DRY = "--dry-run" in args
    once = "--once" in args

    def on_signal(sig, _frm):
        STOP.set()
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, on_signal)

    st = load_state()
    if once:
        st = sample(st)
        save_state(st)
        print(json.dumps(st, indent=1, default=str))
        return 3 if st.get("tripped") else 0

    log("start", interval_s=INTERVAL, probe=PROBE, probe_timeout_s=PROBE_TIMEOUT, stuck_s=STUCK_SECONDS,
        reboot_gate="armed" if reboot_gate()[0] else "disabled", dry_run=str(DRY).lower(), echo=True)
    while not STOP.is_set():
        t0 = time.monotonic()
        try:
            st = sample(st)
            save_state(st)
        except Exception as exc:   # a watchdog must not die on one bad sample
            log("sample-error", error="%s: %s" % (exc.__class__.__name__, exc), echo=True)
        STOP.wait(max(0.0, INTERVAL - (time.monotonic() - t0)))
    log("stop", echo=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
