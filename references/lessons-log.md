# Lessons log

Append a dated entry after every loop (or every few hours during one). Newest last.

## 2026-09-29 — first run (browser homage game → Unreal 5.8, Mac Studio M3 Ultra)

- **Usage:** 6 parallel Opus builders hit the weekly limit in ~1 h; the loop sat idle 5 h overnight. Cap concurrency; split building Sonnet (pipelines) / Opus (hard engineering); critics Opus; Fable director only.
- **Traversal stall:** 3 rounds at 2–3/10 on a placeholder body; switching to the real rig + a C++ port of the original animator gave the first real gains. Diagnose the approach when scores are flat.
- **Oscillating critics:** "don't hug walls" then "don't rail down the centre". Numeric specs from measured references, written before round 1, prevent this.
- **Wrong environment:** traversal judged in a gray-box canyon against lit city footage kept losing A/B on environment. Capture in the real integrated scene.
- **Measurement disagreements:** critic eyeballed hero size wrong; builder's metric was once wrong too. Pixel masks + orchestrator spot checks.
- **Blind A/B leaks:** identical files hashed, clip durations, reference HUD. Re-encode, centre-crop, and ask critics to decide quality before identity.
- **Perf contamination:** all early perf numbers void. Exclusive GPU lock + utilisation logging.
- **Infra incidents:** windowed game trapped the owner's mouse; `pkill` pattern matched everyone's editor; agent cleanup targeted a browser profile; agent pushed an unrequested global rule; session restart killed all agents mid-round; LFS refused on public fork and then budget exhausted; progress-page timestamps guessed wrong. Each became a rule in SKILL.md.
- **IP:** upstream ad atlases and liveries carried third-party brands; excluded per cell with an OCR check.
- **Wins:** Unreal Midtown from the browser city in one round (exporter + GLSL→HLSL facade port); window glass fixed by mip bias; 2,225 storefronts + 616 fire escapes procedurally; brute texture fixed by repainting on the correct UV layout; wall-run with procedural limb phase; swing cadence and facade clearance fixed with measurable checks.

## 2026-09-29 (afternoon) — measure the reference before trusting a critic

- A numeric-spec pass that **measured the reference clips** (YOLO person boxes, vanishing-point camera estimates, luminance histograms) showed three earlier critic demands were contradicted by the reference itself: "hero should swing between 30–70 % of frame width" (reference: hero stays centred, 3–5 % spread — the lively feel comes from camera yaw 2–25° and near geometry filling one side), "rope on screen ≥75 %" (reference 25–45 %), "anchor must be in frame" (reference rope runs off the top edge). One of these had already been sent to a builder as its round target.
- Rule: write the measured SPEC **before round 1**; critics must cite spec lines; a critic demand not backed by a measured reference number is a hypothesis, not a target.
- Reference clips stored at 60 fps may carry 30 fps content — compare motion at the content rate.
- A GPU lock (flock-based capture slots + exclusive perf) now ships in `tools/gpu/`; a live test correctly refused to measure perf while three game instances ran.

## 2026-09-29 16:43 — the GPU took the desktop down

- Five builders + a perf piece + a Blender job launched 11 Unreal instances in 13 minutes (one agent was crash-relaunching an editor every ~30 s). The GPU saturated, macOS's WindowServer missed its watchdog check-in for 40 s, and the system killed it — which logs the user out and kills every app, including the orchestrator's terminal and all agents. The machine itself stayed up.
- The GPU lock only covered captures and perf runs; editors and build commandlets bypassed it. Rule now: a global cap of 2 renderer-bearing engine processes (editors included) through the lock, null-RHI commandlets for builds, no auto-relaunch loops, kill orphaned crash reporters.
- Recovery: commit + push every worktree's WIP immediately, kill leftover engine/crash-reporter processes you own, then resume at lower concurrency.

## 2026-09-29 (evening) — finding the safe concurrency, and relayed messages

- **Measured ceiling on an M3 Ultra (80-core GPU) with Unreal 5.8 Lumen/HW-RT scenes:** an adaptive tuner (start 4 slots, +1 per calm 20 min, −2 on WindowServer strain, emergency kill of the newest capture) climbed to 7, but agents only averaged ~3.8 concurrent instances, the GPU sat at ≥98 % in 48 % of samples, and WindowServer peaked at 40 % CPU (strain threshold 45 %). A single 4K capture pins the GPU alone. Practical ceiling: **~5 renderer-bearing instances**; beyond that they just queue and edge toward the watchdog. Run more *agents* (CPU/RAM have lots of headroom), not more simultaneous renders.
- **Owner messages sent mid-run are relayed into running Workflow agents.** Two builders answered the owner's question ("how's the CPU/GPU?", "what happened?") instead of doing their build, wasting a round each. A soft "ignore relayed messages" line wasn't enough; put it first, in capitals, and say the question is already answered.
- **A same-gap A/B build (Sonnet xhigh vs Opus high) is the only fair model comparison.** Per-round averages mix gap difficulty.
- **First same-gap A/B (river water, identical brief, separate worktrees, blind Opus critic):** Opus 5.5 high 3.8 vs Sonnet 5.5 xhigh 3.4. Opus won on colour and reflections; Sonnet won on shoreline foam and the far-view luma rule. Take the winner and graft the loser's best element next round — the A/B is useful beyond the ledger.

## 2026-09-29 23:08 — a SIGKILL'd engine panicked the kernel

- Stopping agents mid-round, the orchestrator `kill -9`ed a 4K Unreal `-game` perf run mid-frame. It never finished exiting: it stayed a zombie inside the GPU driver. The stopped agents' capture shell loops were still alive and launched two more engines on top. GPU pinned at 100 %, WindowServer blocked uninterruptibly in the kernel, and after 120 s the watchdog **panicked and rebooted the machine** (worse than the 16:43 logout).
- Rules: when stopping an agent, kill its driver scripts before its engine; stop engines with SIGTERM + wait, SIGKILL only as a last resort; the GPU slot lock refuses every launch while any engine process is stuck exiting (`ps` stat `E`/`Z`).

## 2026-09-30 06:55 — the "safe ceiling of ~5" was wrong

- An auto-tuner raised the engine cap to 5 because WindowServer CPU stayed low. At 06:55 four concurrent 4K Lumen/HW-RT captures held the GPU at 100 % for minutes; WindowServer starved **on the GPU** (its CPU read 0–8 %), missed its watchdog and was reset. The owner was logged out and the desktop session was left dead, so every later engine launch hung until a human logged in — the overnight loop lost its ability to render.
- Rules: WindowServer CPU is not a strain signal; sustained 100 % GPU with 3+ heavy renderers is. Hard cap 2 heavy renderers on one machine, never auto-raised. Keep a PAUSED switch in the GPU lock so the orchestrator can stop every launch at once, and have builders fall back to CPU-side work.

## 2026-09-30 00:48 → 06:54 — an OS dialog nobody could click

- A perf agent ran Unreal Insights headless to analyse a trace. Insights opens a network listener, so macOS showed its firewall prompt ("accept incoming network connections?"). Agents cannot click system dialogs; it sat on screen for six hours. When the GPU starved WindowServer at 06:55 the screen froze on that dialog, and the owner found it frozen in the morning and had to power the machine off.
- Rules: before an unattended run, list every tool that opens a port (editor MCP server, profilers, trace servers, cache servers, dev servers) and have the owner pre-approve them in the firewall; never start a new listening tool unattended; the watchdog alerts when the system dialog process appears. After a WindowServer reset the desktop session is dead and no agent can repair it — pause launches, push all WIP, notify the owner.
