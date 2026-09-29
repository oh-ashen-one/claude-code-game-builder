# Claude Code Game Builder

A Claude Code skill for running long, multi-agent **build → capture → blind critic → fix** loops that push a game toward a reference-quality target (e.g. porting a browser game to Unreal and iterating toward a shipped AAA look and feel).

It encodes what we learned from a real 20-hour run: how to split a game into independently judged pieces, give each builder exclusive ownership, run fresh blind critics against reference footage with anonymised A/B pairs, write numeric target specs so critics stop contradicting each other, split work across Sonnet 5.5 / Opus 5.5 / Fable 5.1, keep engine instances and GPU usage sane, measure performance honestly, and survive the incidents (usage limits, session restarts, LFS limits, mouse capture, runaway deletes, IP in upstream assets).

## Credit: based on the Gauntlet Loop

This skill is very much based on **the Gauntlet Loop by Matt Shumer** ([@mattshumer_](https://x.com/mattshumer_)) — <https://somethingbig.ai/gauntlet-loop/generator>. The core ideas come from there: give the agent a real bar it can inspect, split the work into independently judged pieces, and pair every builder with a separate harsh critic, iterating round after round until the evidence meets the bar. What this repo adds is what we learned running that loop for a long game-development session (engine ports, blind A/B against reference footage, numeric specs, multi-model roles, GPU/perf hygiene, and the incidents to avoid).

## Install

```bash
git clone https://github.com/oh-ashen-one/claude-code-game-builder ~/.claude/skills/claude-code-game-builder
# optional: agent definitions (Sonnet builder / Opus critic / Fable director)
cp ~/.claude/skills/claude-code-game-builder/templates/agents/*.md ~/.claude/agents/
```

Then ask Claude Code for an improvement loop on your game; the skill triggers on requests like "make this play like <reference game>", "port this to Unreal and iterate", or "run an overnight build/critic loop".

## Contents

- `SKILL.md` — the process and the hard-won rules.
- `references/` — orchestration walkthrough, model policy + self-evolving ledger, critic protocol, perf protocol, Unreal 5.8 macOS notes, dated lessons log.
- `tools/` — `abpack.py` (blind A/B packs), `progress.py` (live progress page), `ue_mcp.py` (Unreal MCP client).
- `templates/` — shared agent rules, ownership contract, critic prompt, numeric spec, handoff, agent definitions, progress JSON example.

This is a living skill: the lessons log and rules are updated as more loops run.

## License

MIT. Contains no third-party game footage or assets; bring your own references and keep them private.
