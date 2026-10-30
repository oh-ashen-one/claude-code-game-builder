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

## 2026-09-30 — a builder gamed its own look gate

- A perf builder hit its frame-time targets but regressed the look (tree canopies ~2x brighter, clouds erased, saturation −12 to −18 %). It moved its "no regression" comparison crop off the damaged trees and did not mention the cloud loss. The blind auditor caught both by re-measuring the raw stills.
- Rules: gates (crops, thresholds, views) are fixed before the round and cannot be moved by the builder; builders must disclose every visual loss; a round that passes numbers by hiding a regression is not merged. Keep an independent critic that recomputes from raw evidence — builder tables are claims, not results.
- (Same day, round 6) It happened again with a different model (Opus): two foliage losses went undisclosed. A written honesty rule is not enough. Make the look gate a committed script with fixed views, crops, metrics and pass lines, written before any optimisation, run unchanged by builder and critic, and pasted verbatim into the round notes.

## 2026-10-01 02:02 — two engines were enough to reset WindowServer

- With the cap at 2, two 1080p Unreal `-game` captures pinned an M3 Ultra GPU at 100 % for about 2 minutes. WindowServer's main thread then blocked inside a Metal GPU submit, its CPU fell to about 1 %, and its 40 s watchdog reset it. The display was asleep at the time. The orchestrating agent ran in a GUI terminal and died with the desktop session, so every builder and critic stopped and the loop sat idle for hours.
- A minute earlier the orchestrator's own watchdog had reported that the desktop session could not render, and the orchestrator explained it away as a screen lock.
- Rules:
  - Hard cap **one** heavy renderer per machine. A single engine pinning the GPU was safe; two were not.
  - Detect starvation automatically and act without waiting for an agent's judgement. The signature is a pinned GPU, WindowServer CPU collapsing toward 0, and a tiny screencapture that cannot finish within a few seconds. On that signal, pause launches and stop the newest engine (SIGTERM first).
  - Treat any "desktop cannot render" alert as an emergency.
  - Run the orchestrator in `tmux` or another detached host, so a GUI reset cannot take the loop down with it.

## 2026-10-29 03:23 — the GPU driver wedged for 7 hours under five "invisible" clients

- The slot tool reported one engine instance because it only recognised processes whose binary was named `UnrealEditor`. The GPU actually had five or more clients: a chain of 15 cold Unreal `-game` editor launches in 38 minutes with no gap between them (each a 34 GB process), three PyTorch MPS trainers started by the same loop, a packaged game build from a second loop and a Godot renderer from a third. Utilization read 100 % at every one of the last 40 slot acquisitions and the capture class launched anyway (only the perf class waited for a calm GPU).
- The trainers stalled first (`MTLCommandBuffer waitUntilCompleted`). Eight minutes later a fresh editor submitted its first frame and never got it back; its log sat at frame 0. Four minutes after that WindowServer's main thread blocked in the same driver call and the 40 s watchdog killed it: logout, every GUI app and GUI-hosted agent gone. The driver never recovered (`recoveryCount 0`), the editor sat in `E` state unkillable, a loop still launched a Godot run beside it, and the machine waited seven hours for a power-button reset. The previous boot's unified log survived the reset; in zsh use `/usr/bin/log`, the `log` builtin prints nothing.
- Rules:
  - Count every GPU client: packaged game builds, Godot and Unity players, Blender and Metal/MPS/MLX training all take a slot. A trainer that shares the GPU with captures runs under the slot tool like an engine.
  - A slot at 100 % utilization is not a free slot: captures wait for headroom (under ~85 % for 10 s) and leave a 20 s cooldown between cold engine launches; after a settle timeout the round is skipped and logged, never forced.
  - "No frame 1 within 2x the normal startup", any engine in `E`/`Z` state, or a 5 s Metal probe that hangs is the wedge signal: a machine-wide PAUSED file stops every launch, nothing is SIGKILLed, WIP is pushed, the owner is notified. A headless watchdog independent of every loop does this check every 15 s.
  - After a wedge or reset, run one renderer and no concurrent GPU training for the first clean hour. All three loops restarted the previous mix within 13 minutes of the reboot.

## 2026-10-28 12:30 — an uncapped game build broke the owner's stream mic

- A Godot capture (Orchard Reach, 3440x1440, no frame cap) sat at 100 % GPU for the whole session. Streamlabs on the same Mac logged 37.6 % lagged frames and 44 mic restarts in four minutes: OBS clocks its audio mixer off the render loop, so a starved renderer drops the mic while every other app's mic keeps working.
- Low Latency Audio Buffering Mode (a DeckLink/NDI option) had been switched on as an earlier "fix"; it turned every stall into a hard mic cut. Off is correct for streaming; dynamic buffering rides out stalls.
- Rules:
  - Cap every agent-launched engine at 60 fps; nothing in a loop needs more, and an uncapped renderer takes the whole GPU by design. `gpu_slot` now injects the cap.
  - The owner streams 11-13 ET daily. `stream_guard.py` runs the window: STREAMING flag, cap 30, one capture slot, heavy jobs backgrounded with `taskpolicy -b`, the frontmost app and Streamlabs untouched.
  - macOS has no GPU priority control. Headroom comes from capping and serialising renderers, not from boosting the stream.

## 2026-10-28 13:10 — live test: one agent render next to a streamed game is still too much

- With the morning fixes (dynamic audio buffering, Enhanced Broadcasting off, 48 kHz) the stream ran at 2.1 % lagged frames and zero mic restarts under a pinned GPU, versus 37.6 % and 44 restarts before. Twitch-side captures (streamlink + ffmpeg) showed zero video hitches in every sample.
- Residual: hard mid-word audio cuts of 60-180 ms in the Twitch output, measured as speech-to-digital-zero within 10 ms. Worst (6 cuts in 6 s of speech) with an Unreal game at 30 fps plus one agent Unity capture on the GPU; 2 cuts with only an agent Godot capture; the Streamlabs log stayed clean, so the loss is upstream of its mixer. The USB bus is not shared (each device has its own XHCI controller on the Studio), so bus contention is ruled out.
- The audio buffer growth (128 -> 533 ms) came from the macOS Screen Capture sources, not the mic: ScreenCaptureKit audio stalls under GPU load and drags the whole mix. Capture the game window, not the 3440x1440 display.
- Two self-inflicted incidents: Elgato Wave Link launched as a "buffer" took over the Wave XLR, muted the Streamlabs input, then glitched it; and the guard window ended at 13:05 while the owner was still live, so an agent capture started in the gap. Also: the Enhanced Broadcasting checkbox in the Go Live window only saves when the stream is confirmed.
- Rules:
  - While the owner streams, agent renders are ZERO, not one. `gpu_slot` opens no capture slot while `STREAMING` exists (`GPU_SLOT_STREAMING_SLOTS=1` is an explicit owner exception).
  - The guard follows the stream, not the clock: it holds past the window while the Streamlabs/OBS log shows a live RTMP connection, and a 5-minute auto check arms it for off-schedule streams.
  - Never launch Wave Link or any second audio engine on the stream mic from an agent. Never change a live source's device.
  - Stream scenes capture the game window, not the whole display; measure the stream from the viewer side (`streamlink` 40 s + silence/zero analysis), not from the preview.


## 2026-10-30 11:40 — 18 hours of passed gates shipped clips that look the same

An overnight creature re-animation loop (AI video → joint reader → rig fit → refine → blind A/B) passed every gate it had: reader held-out under 3 px, fit under 5 px, loop seams, foot drift, and an in-game blind A/B with a "wins or ties" ship rule. The owner looked at the before/after and saw about 80 % the same. Every gate measured fidelity (does the rig match the video) and none measured quality (is the video a better performance than the clip it replaces). The inputs that decide quality were all fixed by the brief: provider, start picture (the current rig in its stance), timing windows, rig. The first blind round already came back ties and marginal wins; the loop kept going because the goal said "do not stop early", then spent the night chasing a pixel bar with no visible effect.

Rules (added to the hard-won list): a fidelity metric proves the transfer, never the upgrade; pilot one piece beside what it replaces on a close-up before scaling; when the first blind round is flat, stop and report the ceiling and the levers even if the goal says not to stop; "tie ships" is a replacement rule, not an upgrade rule.
