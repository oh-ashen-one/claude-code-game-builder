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
