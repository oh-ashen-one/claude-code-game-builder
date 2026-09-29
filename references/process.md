# Orchestration walkthrough

## Shape of a run

```
Wave 0  foundations   survey · reference library · baseline playtest · engine foundation (compiles, offscreen capture, perf JSON)
Wave 1  core pieces   city/world · characters · traversal/controls · look/lighting — each: build → capture → blind critic → fix
Wave 2  integration   numeric specs · integrated map · combat · city life · dedicated perf piece · regression playtester
Director passes       at every wave boundary and whenever a piece stalls or oscillates
```

The orchestrator (main session) never builds pieces itself. It: creates worktrees, writes the ownership contract and rules, launches builders, packs A/B pairs, launches critics, verifies surprising claims, forwards gaps, merges branches, updates the progress page and the model ledger, handles incidents, and reports to the owner.

## Piece decomposition that worked

| Piece | Owns | Judged on |
|---|---|---|
| Foundation | engine project, C++ module, capture/perf scripts | compiles; offscreen 4K frame; perf JSON with internal res |
| Reference library | private refs repo | coverage per category; INDEX from viewing every file |
| Baseline | docs of the existing build | stills, clips, perf, numbered bugs |
| City / world | exporter, world content, shaders | 8 fixed views vs reference stills |
| Characters | hero/enemy/civilian assets, import scripts | characters **while moving** vs reference clips |
| Traversal + camera + runtime animation | movement component, camera, anim instance | 4 scripted movement sequences vs reference clips |
| Look | lighting presets, post, atmosphere | 3 times of day × fixed views |
| Performance | exclusive-GPU perf harness on the integrated map | p50/p95 at disclosed internal res |
| Integration + regression | integrated map, playtest bug list | whole-game playthrough |

Pieces own disjoint folders. Anything shared (project file, build rules, default configs, main map) goes through the integrator.

## Worktrees and branches

- One integration branch the owner named. Each piece: `loop/<piece>` branch in its own `git worktree` under one parent folder. Never work on `main`; never merge to `main` without owner permission.
- Builders merge the integration branch into their branch at the start of a round; the orchestrator merges piece branches back after each round.
- Commit trailer names the model that actually did the work.

## Continuity

- Resumable agents (SendMessage) keep context between rounds; that's efficient until context grows past ~600–900k tokens. Then have the builder write `HANDOFF.md` (architecture map, commands, constants changed and why, known bugs, critic history) and start a fresh builder from it.
- Fresh builder per round (Workflow agents) works well for Sonnet pipeline pieces when HANDOFF.md is good.

## Deterministic evidence

- Scripted input playback (timed key/axis events from JSON) + per-frame telemetry CSV make every round's clips comparable and let builders prove numeric checks.
- Fixed shot list (camera transforms in JSON) for static views.
- Offline fixed-timestep video for visual review; **never** use it for performance claims.

## What a builder report should contain

What changed (short), a table of the checks and results, deviations from the brief and why, known problems, round folder path. No quality self-assessment — that's the critic's job.

## Reporting to the owner

Lead with the verdicts and what changed; flag incidents and owner decisions explicitly (IP, licensing, budgets); keep a progress page link in every update; timestamps from the clock.
