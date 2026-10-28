#!/usr/bin/env python3
"""stream_guard: give the live stream the machine while the owner is streaming.

  stream_guard.py on  [--until HH:MM]   set the STREAMING flag and background every heavy non-stream job
  stream_guard.py off                   clear the flag and restore the jobs it backgrounded
  stream_guard.py status
  stream_guard.py window [--until HH:MM] [--interval S] [--hard-until HH:MM]
        `on`, then re-apply every S seconds (new jobs started mid-window get backgrounded, the frontmost
        app is always restored) until HH:MM local time AND the stream is actually over (Streamlabs/OBS
        log shows no live RTMP connection), or the flag is removed, or --hard-until (default 17:00).
  stream_guard.py auto                  for a periodic LaunchAgent: arm the guard when a stream is live
        outside the window, disarm it when that stream ends. Does nothing while a window run owns the flag.

What "priority" means on macOS (no sudo needed):
  * every own-user process that is heavy (CPU >= STREAM_GUARD_CPU_MIN %, default 15) or matches the
    engine/build pattern is moved to the Darwin background class with `taskpolicy -b` (efficiency cores,
    low I/O priority). Streamlabs/OBS, audio, capture hardware, browsers and the frontmost app (plus its
    children) are never touched, so the game the owner is playing keeps full speed.
  * the flag file ${GPU_LOCK_DIR:-~/.cache/gpu-slot}/STREAMING is read by gpu_slot.py: while it exists
    agent captures are frame-capped at 30 fps and only one capture slot is open.
  * if passwordless sudo is available, Streamlabs' engine is also reniced to -10; otherwise skipped.
macOS has no GPU priority knob: the FPS cap (gpu_slot) is what leaves GPU headroom for the stream.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

DIR = os.environ.get("GPU_LOCK_DIR", os.path.expanduser("~/.cache/gpu-slot"))
FLAG = os.path.join(DIR, "STREAMING")
LOG = os.path.join(DIR, "stream_guard.log")
CPU_MIN = float(os.environ.get("STREAM_GUARD_CPU_MIN", "15"))

HEAVY = re.compile(os.environ.get("STREAM_GUARD_HEAVY_PATTERN") or
                   r"UnrealEditor|/Binaries/Mac/|-WHShotDir=|(^|\s)-game(\s|$)|[Gg]odot|/Unity\.app/|/Unity/Hub/|"
                   r"Blender\.app|(^|/)blender(\s|$)|dsymutil|xcodebuild|swift-frontend|(^|/)clang(\+\+)?(\s|$)|"
                   r"CoreSimulator/Devices/.*\.app/|(^|/)ffmpeg(\s|$)")
PROTECT = re.compile(os.environ.get("STREAM_GUARD_PROTECT_PATTERN") or
                     r"obs64|Streamlabs|OBS\.app|/OBS(\s|$)|Elgato|Wave Link|Stream Deck|coreaudiod|WindowServer|"
                     r"Google Chrome|Safari|Finder|Dock|loginwindow|stream_guard|kernel_task|launchd|"
                     r"Terminal|ghostty|iTerm|tmux|/claude(\s|$)|codex|Codex|agy(\s|$)")


def log(msg):
    line = "%s %s" % (datetime.now().astimezone().isoformat(timespec="seconds"), msg)
    print(line, flush=True)
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def run(argv, timeout=10):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def procs():
    """Own-user processes: {pid: {ppid, cpu, comm, args}}."""
    # args= must be the last column: ps truncates comm= to 16 chars when other columns follow it.
    r = run(["ps", "-axo", "pid=,ppid=,uid=,%cpu=,args="])
    out = {}
    uid = os.getuid()
    for line in (r.stdout if r else "").splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            pid, ppid, puid, cpu = int(parts[0]), int(parts[1]), int(parts[2]), float(parts[3])
        except ValueError:
            continue
        if puid != uid or pid == os.getpid():
            continue
        args = parts[4]
        m = re.match(r"(.*?\.app/Contents/MacOS/[^/ ]+|\S+)", args)
        comm = m.group(1) if m else args.split(" ", 1)[0]
        out[pid] = {"ppid": ppid, "cpu": cpu, "comm": comm, "args": args}
    return out


def frontmost_pid():
    r = run(["lsappinfo", "front"])
    asn = (r.stdout.strip() if r else "")
    if not asn:
        return None
    r = run(["lsappinfo", "info", "-only", "pid", asn])
    m = re.search(r"pid\s*=\s*(\d+)", r.stdout if r else "")
    return int(m.group(1)) if m else None


def gui_pids():
    """PIDs of regular (Dock-visible, type=Foreground) apps: things the owner interacts with. Never throttled."""
    r = run(["lsappinfo", "list"])
    out, pid = set(), None
    for line in (r.stdout if r else "").splitlines():
        m = re.search(r"\bpid\s*=\s*(\d+)", line)
        if m:
            pid = int(m.group(1))
            if 'type="Foreground"' in line:
                out.add(pid)
    return out


CAPTURE_FLAGS = re.compile(r"-WHShotDir=|(^|\s)-game(\s|$)|-RenderOffScreen")


def descendants(table, root):
    kids = {}
    for pid, p in table.items():
        kids.setdefault(p["ppid"], []).append(pid)
    out, stack = set(), [root]
    while stack:
        n = stack.pop()
        for k in kids.get(n, []):
            if k not in out:
                out.add(k)
                stack.append(k)
    return out


SLOBS_LOGS = Path.home() / "Library/Application Support/slobs-client/node-obs/logs"
OBS_LOGS = Path.home() / "Library/Application Support/obs-studio/logs"
RE_LIVE = re.compile(r"Connection to rtmps?://\S+ success")
RE_STOP = re.compile(r"Output '[^']*': stopping")


def streaming_active():
    """True if the newest Streamlabs/OBS engine log shows a live RTMP connection after the last stop."""
    for d in (SLOBS_LOGS, OBS_LOGS):
        logs = sorted(d.glob("*.txt"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
        if not logs:
            continue
        newest = logs[-1]
        if time.time() - newest.stat().st_mtime > 6 * 3600:
            continue
        try:
            text = newest.read_text(errors="ignore")
        except OSError:
            continue
        last_live = max((m.end() for m in RE_LIVE.finditer(text)), default=-1)
        last_stop = max((m.end() for m in RE_STOP.finditer(text)), default=-1)
        if last_live > last_stop:
            proc = "obs64" if d == SLOBS_LOGS else "OBS"
            r = run(["pgrep", "-x", proc])
            if r is not None and r.returncode == 0:
                return True
    return False


def read_flag():
    try:
        with open(FLAG) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_flag(d):
    os.makedirs(DIR, exist_ok=True)
    tmp = FLAG + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh, indent=1)
    os.replace(tmp, FLAG)


def proc_start(pid):
    r = run(["ps", "-o", "lstart=", "-p", str(pid)])
    return (r.stdout.strip() if r else "")


STICKY_S = float(os.environ.get("STREAM_GUARD_STICKY_S", "600"))


def candidates(table, flag=None):
    """Heavy own-user pids minus protected ones. The frontmost app, its children, and any app that was
    frontmost within STICKY_S seconds (the game the owner is playing while they glance at Streamlabs) are protected."""
    front = frontmost_pid()
    now = time.time()
    recent = (flag or {}).setdefault("recent_front", {}) if flag is not None else {}
    if front is not None:
        recent[str(front)] = now
    for spid in list(recent):
        if now - recent[spid] > STICKY_S or int(spid) not in table:
            del recent[spid]
    protected = set()
    for spid in recent:
        protected |= {int(spid)} | descendants(table, int(spid))
    for gpid in gui_pids():
        if gpid in table:
            protected |= {gpid} | descendants(table, gpid)
    out = []
    for pid, p in table.items():
        if pid in protected or PROTECT.search(p["args"]):
            continue
        # heavy = sustained CPU, or an engine/build binary (matched on the executable, not its arguments),
        # or an offscreen engine capture (flags in the arguments)
        if p["cpu"] >= CPU_MIN or HEAVY.search(p["comm"]) or CAPTURE_FLAGS.search(p["args"]):
            out.append(pid)
    return out, front


def background(pid):
    r = run(["taskpolicy", "-b", "-p", str(pid)])
    return r is not None and r.returncode == 0


def foreground(pid):
    r = run(["taskpolicy", "-B", "-p", str(pid)])
    return r is not None and r.returncode == 0


def boost_stream(table):
    """Best effort: renice the streaming engine if passwordless sudo exists; never prompts."""
    pids = [str(pid) for pid, p in table.items() if re.search(r"obs64|Streamlabs Desktop$|OBS$", p["comm"] or "")]
    if not pids:
        return "no-stream-process"
    r = run(["sudo", "-n", "renice", "-n", "-10", "-p"] + pids)
    return "reniced" if r is not None and r.returncode == 0 else "no-passwordless-sudo"


def apply(flag, table=None):
    table = table or procs()
    cands, front = candidates(table, flag)
    bg = flag.setdefault("backgrounded", {})
    changed = []
    # restore anything we backgrounded that is now protected (frontmost) or gone
    for spid in list(bg):
        pid = int(spid)
        if pid not in table or table[pid]["comm"] != bg[spid].get("comm") or proc_start(pid) != bg[spid].get("start"):
            del bg[spid]
            continue
        if pid not in cands:
            foreground(pid)
            changed.append("fg:%d:%s" % (pid, table[pid]["comm"]))
            del bg[spid]
    for pid in cands:
        spid = str(pid)
        if spid in bg:
            continue
        if background(pid):
            bg[spid] = {"comm": table[pid]["comm"], "start": proc_start(pid), "cpu": table[pid]["cpu"]}
            changed.append("bg:%d:%s" % (pid, os.path.basename(table[pid]["comm"])))
    flag["front_pid"] = front
    flag["front"] = os.path.basename(table[front]["comm"]) if front in table else None
    flag["applied_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_flag(flag)
    if changed:
        log("apply front=%s changes=%s" % (flag["front"], ",".join(changed)))
    return flag


def cmd_on(until=None, mode="manual"):
    flag = read_flag() or {}
    flag.update(since=flag.get("since") or datetime.now().astimezone().isoformat(timespec="seconds"),
                until=until, mode=mode, pid=os.getpid())
    table = procs()
    flag["boost"] = boost_stream(table)
    apply(flag, table)
    log("on mode=%s until=%s boost=%s backgrounded=%d" % (mode, until, flag["boost"], len(flag.get("backgrounded", {}))))
    return 0


def cmd_off():
    flag = read_flag()
    if flag is None:
        log("off (flag already clear)")
        return 0
    table = procs()
    n = 0
    for spid, rec in (flag.get("backgrounded") or {}).items():
        pid = int(spid)
        if pid in table and table[pid]["comm"] == rec.get("comm") and foreground(pid):
            n += 1
    try:
        os.unlink(FLAG)
    except OSError:
        pass
    log("off restored=%d" % n)
    return 0


def cmd_status():
    flag = read_flag()
    if flag is None:
        print("STREAMING: off (%s absent)" % FLAG)
        return 1
    print("STREAMING: on since %s until %s mode=%s front=%s boost=%s" % (
        flag.get("since"), flag.get("until"), flag.get("mode"), flag.get("front"), flag.get("boost")))
    for spid, rec in sorted((flag.get("backgrounded") or {}).items(), key=lambda kv: int(kv[0])):
        print("  backgrounded pid=%-6s %s" % (spid, rec.get("comm")))
    return 0


def parse_until(s):
    if not s:
        return None
    h, m = s.split(":")
    now = datetime.now()
    t = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    return t


def cmd_window(until_s, interval, hard_until_s="17:00"):
    until = parse_until(until_s)
    hard = parse_until(hard_until_s)
    if until is None:
        print("window needs --until HH:MM", file=sys.stderr)
        return 2
    if datetime.now() >= until and not streaming_active():
        log("window: already past %s and no live stream, nothing to do" % until_s)
        return 0
    cmd_on(until=until.astimezone().isoformat(timespec="minutes"), mode="window")
    extended = False
    try:
        while True:
            now = datetime.now()
            if now >= hard:
                log("window: hard stop at %s" % hard_until_s)
                break
            if now >= until:
                if streaming_active():
                    if not extended:
                        log("window: past %s but the stream is still live; holding the guard" % until_s)
                        extended = True
                else:
                    break
            time.sleep(interval)
            flag = read_flag()
            if flag is None:
                log("window: flag removed externally, stopping")
                return 0
            apply(flag)
    finally:
        if read_flag() is not None:
            cmd_off()
    log("window: ended (%s)" % ("stream ended" if extended else until_s))
    return 0


def cmd_auto():
    flag = read_flag()
    live = streaming_active()
    if flag is None:
        if live:
            log("auto: live stream detected outside the window, arming")
            return cmd_on(until=None, mode="auto")
        return 0
    if flag.get("mode") == "auto":
        if live:
            apply(flag)
        else:
            log("auto: stream ended, disarming")
            return cmd_off()
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    sub, args = argv[1], argv[2:]
    until, interval, hard_until = None, 60.0, "17:00"
    i = 0
    while i < len(args):
        if args[i] == "--until" and i + 1 < len(args):
            until = args[i + 1]; i += 2
        elif args[i] == "--interval" and i + 1 < len(args):
            interval = float(args[i + 1]); i += 2
        elif args[i] == "--hard-until" and i + 1 < len(args):
            hard_until = args[i + 1]; i += 2
        else:
            print("unknown option %r" % args[i], file=sys.stderr)
            return 2
    if sub == "on":
        return cmd_on(until=parse_until(until).astimezone().isoformat(timespec="minutes") if until else None)
    if sub == "off":
        return cmd_off()
    if sub == "status":
        return cmd_status()
    if sub == "window":
        return cmd_window(until, interval, hard_until)
    if sub == "auto":
        return cmd_auto()
    print("unknown subcommand %r" % sub, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
