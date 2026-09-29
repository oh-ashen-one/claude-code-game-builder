---
name: claude-code-game-builder
description: Run a long, multi-agent build → capture → blind-critic → fix loop that pushes a game (browser, Unreal, Unity, Godot) toward a named AAA reference game. Use when asked to "make it look/play like <reference game>", port a game to another engine, run an overnight improvement loop, or fan out builder and critic agents on a game. Covers piece decomposition and ownership, per-model roles (Sonnet 5.5 / Opus 5.5 / Fable 5.1), blind A/B critics against reference footage, numeric target specs, GPU/engine instance hygiene, performance protocol, progress pages, and the failure modes we hit.
---

# Claude Code Game Builder

A field-tested process for improving a game toward a reference-quality target with many agents over many hours. Written from a real 20-hour run (a three.js homage web-swinging game ported to Unreal Engine 5.8 on a Mac Studio M3 Ultra, judged against a shipped AAA game). Every rule here exists because breaking it cost us time.

Read this file fully before starting. Detail lives in `references/`; ready-to-use tools and templates in `tools/` and `templates/`.

## The loop in one paragraph

Break the game into pieces that can be judged independently. Give each piece one builder with exclusive ownership of its branch, worktree, engine instance and folders. Each round the builder builds, runs the real game, captures matching views and movement clips, and stops. A **fresh critic that never sees the builder's notes** compares those captures to reference footage in anonymised A/B pairs, scores fixed axes, and names the **single biggest gap** (or a small set, see below) as a measurable instruction. The builder fixes that and nothing else. Repeat until the critic says MEETS TARGET with evidence. A director model reviews the whole loop at wave boundaries, reconciles contradictions and reassigns models. A live progress page shows before/after, clips, verdicts, perf and gaps.

## Roles and models (owner policy; re-evaluate with the ledger)

| Role | Model / effort | Why |
|---|---|---|
| Hard, central engineering: physics/animation/gameplay ports, integration map, performance | **Opus 5.5, high** | Deep reasoning, long context; the original code was written with it |
| Pipelines, assets, content scripts, captures, tooling, searches | **Sonnet 5.5, extra-high** | Cheap and very capable when the instruction is concrete |
| Critics (every round), integration playtests | **Opus 5.5, high** | The critic is the quality gate; keep it harsh and trustworthy |
| Director: wave plans, stall/oscillation diagnosis, model reassignment, final acceptance | **Fable 5.1, high** | Smartest; has its own weekly limit and draws a lot of usage — direct, never build |

- In Claude Code the Agent tool sets a model but not effort. Use Workflow agents (`agent(prompt, {model:'sonnet', effort:'xhigh'})`) or agent definitions in `~/.claude/agents/` (templates in `templates/agents/`; they load at session start).
- Never interrupt running work to apply a policy change; apply it to the next spawn.
- **Self-evolving:** keep `model-ledger.json` (piece, round, model, effort, tokens, critic scores). Occasionally build the same gap with Sonnet and Opus as a blind A/B. The director reassigns models from this evidence. See `references/model-policy.md`.

## Setup checklist (do this before any builder starts)

1. **Survey first.** One read-only agent maps the codebase (systems, constants with file:line, assets, harnesses, controls, perf notes, known gaps). Builders get this map instead of rediscovering it.
2. **Reference library.** Stills and short clips of the target game, organised by what will be judged (traversal, streets, characters, animation, combat, night...), with an `INDEX.md` written by *looking* at every file, `SOURCES.md`, a `CRITIC_GUIDE.md` rubric, and a script that regenerates local-only clips. Keep third-party footage in a **private** repo; never in a public one.
3. **Ownership contract** (`templates/OWNERSHIP.md`): per piece — branch, worktree path, owned folders, engine content folder, MCP port, dev-server port. Shared files change only through the integrator.
4. **Shared agent rules** (`templates/RULES.md`): read first by every agent. Include instance limits, delete limits, IP rules, commit trailer, LFS policy, capture rules.
5. **Baseline.** Capture the "before": stills, clips, perf, and a numbered playtest bug list of the existing build.
6. **Numeric target spec per piece** (`templates/SPEC.md`), measured from the references by an Opus agent: swing period, hero screen-height percentiles, window-brightness distribution, luminance at night, clipped-pixel %, etc., each with the checker that measures it. Critics score against the spec, may add gaps, may not contradict a spec line. **Write this before round 1** — we only did it at round 9 and paid for it (see failures).
7. **Progress page** (`tools/progress.py` + JSON): pieces table, before/after, clips, critic log, perf table with internal resolution, model ledger, gaps, log with **real clock timestamps** (`date +%H:%M`, never estimates).
8. **GPU lock** for engine captures and an exclusive perf lock (`references/perf-protocol.md`).

## Per-round protocol

1. Builder builds and runs the **real game** (never the editor viewport as evidence), captures the fixed shot list and scripted movement sequences (deterministic input replays so rounds are comparable), writes neutral notes only (camera, inputs, internal res — **no self-assessment**), commits, pushes, stops its processes, rewrites `HANDOFF.md`.
2. Orchestrator packs anonymised A/B pairs with `tools/abpack.py` (re-encodes and centre-crops so files can't be matched by hash, duration or HUD) including a "progress" pair (this round vs last round of ours).
3. Fresh critic (`templates/CRITIC_PROMPT.md`) scores axes 0–10 (10 = indistinguishable from the reference at the matching view, 8 = shippable AAA), decides each A/B pair before guessing identity, names the biggest gap as a testable instruction, lists ≤4 secondary issues, gives FAILS / APPROACHES / MEETS. MEETS requires ≥8 on every axis with evidence. **Critics must measure, not estimate** (crop and count pixels).
4. **Orchestrator verifies surprising critic claims against frames** before forwarding them (a critic twice reported the hero at "6–8% of frame" when frames showed 17%; the builder's metric was right once and wrong once — check both).
5. Send the builder the gap(s) + critic file path; the builder copies the critique into the round folder.
6. Merge the piece branch into the integration branch, update the progress page and ledger.

**Gap batching:** single-gap rounds are clean but slow and can oscillate. Once a piece has a numeric spec, send 2–3 gaps per round when they touch different files. Keep single-gap rounds for contested areas.

## Hard-won rules (each from a real incident)

- **Usage:** six parallel Opus builders exhausted a weekly limit in ~1 hour. Cap concurrency, put pipeline work on Sonnet, track tokens in the ledger.
- **One engine instance per agent, launched offscreen** (`-RenderOffScreen -NoSound` for Unreal, including the editor), max 3 at once on one GPU, close the editor when idle. A windowed game grabbed the owner's mouse and Escape didn't release it — ship a mouse-safe controller (no capture on launch, Escape always releases) before any windowed run.
- **Kill only by your own absolute project path.** A shared README said `pkill -f Project.uproject`, which matches every agent's editor.
- **Delete only inside your own worktree/scratch**, via a path check. An agent's cleanup targeted the owner's browser profile (the OS blocked it).
- **Agents never edit global instructions, memory, or other repos.** An agent misread a relayed owner message and pushed an unrequested global rule; owner messages are handled by the orchestrator only.
- **Public forks can't take new Git LFS objects, and LFS budgets run out.** Make engine content reproducible from committed scripts (idempotent `build_<piece>.py`); keep binaries out of git.
- **Stale module binaries:** UE's UBT can leave the modules manifest pointing at a deleted dylib when other editors run — delete the module dylibs + manifest before building.
- **Captures:** hidden browser tabs throttle to 1 Hz; use headless Chrome with its own profile over CDP. Warm up auto-exposure (pre-roll) before recording or the first frames are white.
- **Perf numbers from a shared GPU are void.** Record GPU utilisation before every run, take an exclusive lock, disclose internal resolution (TSR %), and never claim 60 fps from offline fixed-step captures.
- **IP:** upstream assets may carry third-party brands (ad atlases, liveries). Exclude them (document in `IP_EXCLUSIONS.md`), OCR the renders, never put the reference game's name in image-generation prompts, keep a homage disclaimer.
- **Session restarts kill background agents.** On restart: commit every worktree's WIP, push, kill orphaned engine instances, then resume agents with the WIP commit id.
- **Timestamps:** read the clock. Guessed times drifted hours off twice.
- **Tear down** merged worktrees, captures and engine caches (DerivedDataCache, Intermediate, Library) in the same session.

## Stall and oscillation playbook

- Scores flat for 3 rounds → diagnose the approach, not the next gap. Our traversal sat at 2–3/10 for three rounds on a placeholder body; porting the real rig + animation system jumped it.
- Critics contradict each other (r7 "hugging walls" → r8 "rail-straight in the centre") → write both constraints into the spec as one target ("weave inside a safe corridor").
- A piece judged in a gray-box test world against lit reference footage loses on environment, not on its own axes → capture it inside the real integrated scene.
- Metric vs pixels disagree → measure from pixels (hero-only mask/depth capture), and verify a sample frame yourself.

## Files

- `references/process.md` — full orchestration walkthrough with timings and the wave structure.
- `references/model-policy.md` — model roles, ledger format, A/B build protocol, Workflow/agent-definition recipes.
- `references/critic-protocol.md` — blind A/B packing, scoring, measuring, verification, spec discipline.
- `references/perf-protocol.md` — GPU lock, exclusive perf runs, what to record.
- `references/unreal-notes.md` — UE 5.8 on macOS: MCP, offscreen capture, UBT, glTF import quirks, Nanite UV limits, Lumen, TSR.
- `references/lessons-log.md` — dated log of what we learned; append after every loop.
- `tools/` — `abpack.py`, `progress.py`, `gpu_slot.sh` (see references), `ue_mcp.py`.
- `templates/` — RULES.md, OWNERSHIP.md, CRITIC_PROMPT.md, SPEC.md, HANDOFF.md, agent definitions.

## Keep this skill alive

After each loop (or every few hours of one), append to `references/lessons-log.md`, update the rules above if a new incident taught something, and push. The skill is open source: never commit secrets, personal data, private paths, or third-party footage.
