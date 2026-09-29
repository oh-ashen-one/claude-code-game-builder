# Performance protocol

Performance numbers taken on a shared GPU are void. On our run, other agents' engine instances and other sessions held the GPU at 40–100 % before most runs, and identical builds varied 2× between runs.

## Rules

1. **Exclusive lock for perf, shared slots for captures.** Captures may share (max 2); a perf run takes an exclusive lock and waits until no capture holds a slot, no other engine game/offscreen process runs, and GPU utilisation stays under ~15 % for 10 s. Max hold ~15 min. (macOS: `ioreg -r -d 1 -c IOAccelerator | grep "Device Utilization"`; implement the lock with mkdir-based lock dirs or python fcntl — there is no flock(1).)
2. **Record with every number:** output resolution, internal resolution (TSR/DLSS %), GPU utilisation before and after, instance count, lock wait time, build commit, route/script. Mark anything taken without the lock "contaminated".
3. **Measure real gameplay** (scripted route through the heaviest area), not a static view and never an offline fixed-timestep capture. Report avg, p50, p95, p99, hitches > 33 ms, and GPU time.
4. **Disclose internal resolution.** 4K output with TSR 50–67 % is an honest target on Apple Silicon; native 4K at 60 is usually not.
5. **Re-run after integration** — combat, crowds and traffic add load after the budget is set.

## Unreal flags we used

`-game -RenderOffScreen -ResX=3840 -ResY=2160 -ForceRes -NoSound -NoCrashReports`, `-exec "r.ScreenPercentage 100"` for native, CSV profiler for frame stats, `t.MaxFPS 0`. First heavy costs to look at: Lumen screen-probe gather, virtual shadow maps, base pass of heavy custom shaders. Single toggles (HW RT, volumetric fog, clouds) each saved only 1–2 ms in our scene.
