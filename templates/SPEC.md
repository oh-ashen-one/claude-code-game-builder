# <Piece> — target spec (numeric, measured from references)

Written by an Opus agent that MEASURED the reference files (frames extracted, pixels counted, events timed). Critics score axes against these lines; they may add gaps they observe but may not contradict a line unless they measure that the reference itself violates it. Builders ship a checker per line.

| # | Axis | Target (range) | Measured from (ref file @ time) | Checker (script, what it measures) |
|---|---|---|---|---|
| 1 | e.g. swing rhythm | attach→release 1.2–1.8 s | clip_x.mp4 0:00–0:08 (5 swings) | `cadence_check.py` from telemetry CSV |
| 2 | e.g. hero framing | hero bbox height 12–22 % of frame, p5–p95 | clip_x.mp4 frames at 6 fps | hero-only mask capture → bbox |
| 3 | e.g. facade clearance + weave | hero ≥3 m from facades AND centre-x spread ≥30 % of frame width | clip_y.mp4 | depth capture + bbox |

## Resolved contradictions
- <constraint A> and <constraint B> both hold: <single combined target>.

## Unmeasurable from refs
- <anything you can't measure — say so instead of inventing>

## Axis → lines
- Axis 1: lines 1, 4 …
