# Critic protocol

## Blindness

- The critic is a **new agent every round** with no builder report, commit messages, READMEs, shot lists, telemetry or previous critiques. It judges pixels and motion only.
- `tools/abpack.py <pack_dir> <pairs.json>` builds anonymised pairs: each pair's two files are re-encoded (no metadata), centre-cropped to 84% (hides HUD/logos in reference footage) and randomly assigned A/B; the key goes outside the pack.
- Include at least one **progress pair** (this round vs last round of ours) so improvement is measured, not asserted.
- Blindness is imperfect (gray-box vs real footage, durations): require the critic to decide "which is better and why" before guessing identity, and to report when identity was obvious.

## Scoring

- 0–10 per axis: 10 = indistinguishable from the reference at the matching view/movement; 8 = accepted as a shipped AAA game; 5 = good indie; 2 = prototype.
- MEETS TARGET requires ≥8 on every axis of the piece with evidence; missing evidence = unproven = FAILS.
- Output ≤450 words: scores with one line of evidence each (file + timestamp/region), A/B decisions, the single biggest gap as a **testable instruction** (what, when/where, what it should look like, which reference shows it, a measurable test), ≤4 secondary issues, verdict. Full text to a CRITIC.md in the critic's scratch folder.
- **Measure, don't estimate**: crop and count pixels, extract frames at 6 fps, give frame times.
- Ask critics to flag copied brands/logos/text.

## Orchestrator verification

Before forwarding a gap, spot-check surprising claims against actual frames (extract 1–2 frames with ffmpeg and look). We caught a critic claiming a hero was 6–8% of frame height when frames showed ~17%; we also caught a builder's metric that measured the wrong thing. Forward what the frames support.

## Specs stop oscillation

Single-gap critics drift: one round punishes wall-hugging, the next punishes the resulting centred path. Fix with a per-piece `SPEC.md` of numeric targets measured from the references (ranges, not points) and a checker per line. Critics score against the spec, may add gaps they observe, and may not contradict a spec line unless they measure that the reference itself violates it.

## Axes we used

- Traversal: arc/rhythm/momentum · camera · web/rope read · move variety & transitions · body animation.
- City: facades · street dressing · rooftops & skyline · believability as the place · image quality.
- Characters (judged moving): hero model · hero animation · enemies · civilians · image quality.
- Look: sun/sky/time of day · GI & shadows · atmosphere & depth · reflections · post & exposure · night.
