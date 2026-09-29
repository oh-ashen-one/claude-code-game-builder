# Model policy (Claude models, late 2026)

| Model | Relative cost | Use for |
|---|---|---|
| Sonnet 5.5, extra-high thinking | lowest | Pipelines, asset/import scripts, content generation, captures, tooling, reference indexing, baselines, fan-out workers |
| Opus 5.5, high thinking | moderate | Hard/central engineering (physics, animation, gameplay/combat ports, integration, performance), every critic, integration playtests |
| Fable 5.1, high thinking | highest; own weekly limit | Director only: wave plans, stall/oscillation diagnosis, model reassignment, final acceptance. Never builds. Not every round. |

Owner guidance that shaped this: outcome quality comes first ("if you have to use the usage, use it"), but don't waste it; Opus is excellent and shouldn't be starved of building work; Fable directs.

## Setting model + effort in Claude Code

- Agent tool: `model` is settable, effort is not.
- Workflow agent: `agent(prompt, {model: 'sonnet'|'opus'|'fable', effort: 'xhigh'|'high'|'medium'})`.
- Agent definitions (`~/.claude/agents/*.md` frontmatter `model:` + `effort:`) — see `templates/agents/`. Loaded at session start; a session started before you write them won't see them.

## Model ledger (self-evolving)

`docs/loop/model-ledger.json`:

```json
{"rounds": [{"piece": "Traversal", "round": 6, "model": "Opus 5.5", "effort": "high", "scores": [4,4,5,4,4]}],
 "agents": [{"piece": "Traversal", "rounds": "6–8", "model": "Opus 5.5", "tokens": 654000}]}
```

- Per-round averages compare trajectories, not models (each round targets a different gap).
- For a real comparison run a **same-gap A/B build**: two builders (Sonnet xhigh and Opus high) in separate worktrees get the identical brief; a blind critic compares both results against the reference and each other. Record winner, score delta and tokens.
- At each wave boundary the director reads the ledger and reassigns.

## Observed so far (one run)

- Sonnet xhigh builders delivered solid pipeline rounds (city windows, street level, brute texture fix, reference index with ~70 manifest corrections) at clearly lower cost.
- Opus carried the traversal/animation C++ port; the jump from 2→4 on body animation came from an Opus approach change (real rig + ported animator).
- Opus critics were harsh and useful but twice mis-measured sizes by eye → require pixel measurement.
- The Fable director's first pass found the structural causes of a stall (gray-box evaluation environment, oscillating single gaps, void perf data) that per-round critics missed.
