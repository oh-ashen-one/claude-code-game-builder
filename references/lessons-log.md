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
