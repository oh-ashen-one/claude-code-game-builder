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

## 2026-10-13 — second map for a Unity horror game: eight rounds, what the loop taught

Setup: a public Unity 6 ghost-investigation game got a second, hand-authored map with a new hunter. One Opus integrator owned every shared file and the only engine instance; Sonnet builders owned layout, art, props, audio and rules in their own worktrees; an Opus critic scored each round blind against generated concept images; the director (Fable) never built. Score went 3.5 → 4.5 → 5.0 → 5.0 → 5.3 over rounds 1–7.

- **A self-test that logs the value you applied is not a test.** The candle-flame "lean toward the hunter" passed the builder's own `HC_LEAN_CHECK` at 28° for four rounds while the critic measured 0–7° in pixels: a billboard script re-faced the quad after the lean was applied. The fix was to move the effect into the shader's vertex stage and make the read-back project the post-offset vertices to screen. Rule: a round-level self-test must read back from the render (or a projection of what the GPU will draw), never from the number the script wrote.
- **Procedural textures made at editor time arrive blank in the player.** The layout ran in the editor and was saved into the scene; its `new Texture2D` sprites (flames, moons, runes) were non-readable scene assets and rendered as solid white cards in the build for three rounds. Bake generated textures to files under `Resources/`, and add a one-shot player log that prints the material's shader name and texture size.
- **Map A's mechanics leak into map B.** The house's "breaker off → every lamp off" warning phase ran unchanged in the castle and killed every candle during the hunt, so hunt frames were blue-black while the still shots were warm. Keyed every lamp rule by map before anything else was tuned.
- **A black-lift post pass fakes the "no crushed pixels" check.** Round 2 passed "0 % below luma 8" by raising every dark pixel to luma 17; the references have 15–28 % below 8. Score darkness as a band measured against the reference histogram, never as "no black".
- **Exposure oscillates when fills change by whole factors.** One room went 46 % → 4 % → 42 % near-black across three rounds. A committed `exposure_report.py` (per shot: mean luma, % below luma 8, % warm, verdict, suggested half-step) run after every capture, plus a "change by half the error" rule, stopped it in one round.
- **Forward rendering's per-pixel light cap silently drops fill lights.** Four per-pixel lights per object meant every "warm fill" lost to the candle lamps; marking fills `ForcePixel` fixed shots that had looked untouched for two rounds. Check the light budget before tuning intensities.
- **Capture framing by pose bounds under-frames a winged creature.** Fill 58 % of the frame by the pose bounding box gave 35 % body height because the wings dominated the box. Frame by body (feet to head) and log both heights.
- **3D providers moderate gore, and auto top-ups fire.** A flayed-demon reference was refused as NSFW by one provider; the first charge triggered a 400-credit auto top-up on the owner's account before the refund. Before any paid loop: check the account's auto top-up setting, keep one job in flight, and record balance before/after each job. A second provider (via an MCP) took the same reference without complaint.
- **Another session's GPU load voids your frame times.** Record the slot's GPU utilisation with every capture and mark the round "contaminated" instead of making lighting decisions on it.
- **Stills can't judge scary.** Seven rounds of critic scoring rated the hunter's model "near ship quality" on fidelity to its sheet; the owner looked once and rejected the design as not frightening. Show the owner the hero asset at the concept stage and again at first in-engine capture, before the loop optimises toward the wrong target.
- **Stone kits over box colliders need a second pass.** Dressing cube rooms with relief modules in one round left the old columns poking through the new piers, untextured cube faces and panel-sized seams; the integration round was as long as the dressing round. Budget both.

## 2026-10-14 — fear wave on the same map: research → 19 items → one overnight wave

Setup: a research pack (how a reference horror game makes hunts scary) was turned into a 19-item plan with written contracts per shared type, then built in one wave: one Opus integrator on every shared file plus the only engine, five Sonnet/Opus builders in worktrees (rules, hunter, scares, audio, grab clips), one Sonnet on a title redo, one on a wall-art handoff. All seven branches merged in one night; the scripted fear run proved 14 of 16 behaviours on the first build.

- **A gate that rejects every candidate must log why.** Prop throws never fired: a table's collision box was 0.95 m tall over a 0.775 m tabletop, so the sight check from the hunter to every prop hit the table's own box and skipped silently; behind that, the scene-prepare step static-batched all 38 castle props (only map A's one throwable was exempted by name), so none could have moved anyway. Both were invisible because the reject path had no log. Rule: every filter in a scare/AI candidate loop logs `SKIP reason=` with the measured value, and the scripted run's summary counts skips by reason. Also: any object a script moves must be excluded from static batching by tag or component, never by name.
- **Write the contracts before the fan-out, and name a single owner for every shared file.** Seven parallel branches merged with no conflicts because the plan listed, per piece, the exact public API it would expose (`HuntRules.For(map)`, `Investigation.AddDread`, `CastleRun.Sarcophagus()`, audio key names, clip names and reach distances) and the integrator alone edited `Game`, `Interface`, `Soundscape` and the editor scripts. Builders coded against the contract, not against each other's branches.
- **Map A must stay byte-identical, and a fuzz test is the only proof.** The new hunt rules were injected via a per-map rules object and verified identical to the old behaviour over 4,000 seeded runs. Without that test the "we gated everything by map" claim is just a claim.
- **Agents cannot hear.** Thirteen procedural sound effects and three synthetic voice lines shipped unlistened because no builder has an audio device. Record in the asset log which clips a human has heard; the critic's checklist carries them until someone does.
- **A scripted run that forces the dice is a wiring test, not a playtest.** The fear run set the rules' random values and pushed the dread meter itself to reach every branch in four minutes. It proved the branches exist; only a natural run or the owner can say whether they are frightening. Report both kinds separately.
- **Full screen is a liability on a shared desktop.** The owner uses the machine while the loop runs; scripted full-screen game launches were closed from outside within seconds and the saved screen mode leaked into the owner's own launches. Default every build and every scripted run to a window, restore the window mode on quit, and log the mode at start.
- **A streaming owner means no windows at all.** When the owner went live, every remaining task that needed the game on screen (captures, playthroughs, the blind critic) was parked and the loop switched to code-only work: a static critic reading code against the plan, a builder fixing a bug from logs, docs and merges. Keep a list of which backlog items need a window so the switch takes one message.

## 2026-10-14 — rounds 10–12 on the same map: tells, metronomes and blind-to-each-other builders

Setup: three more critic rounds (static 4→5, blind-from-captures 4.5, blind playtest 4.5 → 5.0) on the fear loop, with waves of fixes between them. Same crew shape: one Opus integrator on shared files and the only engine, Opus on rules and the hunter, Sonnet on scares, audio, clips and three art pieces, Opus critics blind.

- **Removing tells moves them; count the next one.** Round 11's fixes removed every HUD, music and lamp hunt tell. Round 12 found hunts now began within 5 s of an apparition that fired every 101–141 s, so "he appears about every two minutes, and when he appears he hunts" was learnable in one session, and the first hunt was fixed at 69–74 s. Any periodic event that can escalate into a threat is a tell. Before a round, list every clock in the game (scare cadence, first-hunt window, cue timers) with its coefficient of variation; anything under 0.5 that correlates with danger is the next critic finding.
- **A 100 %-reliable cue is a tell even when it is too late to act on.** The torch flicker fired in the last second of every dive. It saved no one, but it told the player exactly when the grab lands. Fire decoys at the same rate at harmless moments, or roll the real one.
- **A log that reports a scalar the script computed is not a measurement.** The hunter's `claw_ok=True claw_px=629` was logged with no hand on screen; the critic measured the frame and threw the gate out. Project the real mesh vertices (frustum- and occlusion-clipped) and log that, next to the frame name, so the critic's pixel count and the game's number can disagree visibly.
- **A chance that is zero below a threshold is a contract players discover.** Hiding unwatched below Dread 80 never failed in 9 of 9 hunts; the critic called it a guaranteed save. Make every survival mechanic fail on a curve from low Dread, add in-match learning (the hunter checks the hide he last found you in), and turn low-probability "it can happen" rolls into bags (exactly 1 in N) so a short critic run can observe them.
- **Builders working blind to each other duplicate shared logic; the director reconciles at merge.** The rules builder exposed a near-miss curve and an escalation gate; the hunter and scares builders, briefed in the same wave, each wrote their own copies with slightly different numbers. The fix was a reconciliation list sent to the integrator (which function is canonical, what floors or multipliers to keep on top). Either sequence the API owner first or send the integrator a reconciliation list the moment the API lands.
- **The critic tests the build it was given, not HEAD.** Two fixes merged while the critic ran were re-reported as findings. Record the build hash in the critic brief and in the fix-wave brief, and tell builders which findings are already fixed-but-unbuilt.
- **"Done" from the integrator needs the critic's own metrics in the run summary.** When the critic's pass tests are numeric (share, longest gap, CV, % of hunts within 10 s of a scare, hidden survival %), have the scripted-run summary print those exact numbers so the next critic round starts from an agreed measurement instead of recomputing from logs.
