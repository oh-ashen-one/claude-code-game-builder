# <Loop name> — ownership contract

> If this is a homage/fan project: state here that it is not official and not affiliated with the reference game's owners.

Integration branch: `<branch>` (worktree `<INTEGRATION_WORKTREE>`, owned by the orchestrator).
Target: <reference game> quality — <axes>. Hardware: <machine>. Output <W×H> @ <fps>, internal resolution always disclosed, perf measured during real gameplay under the exclusive GPU lock.

| Piece | Branch | Worktree | Owns (folders, engine content, scripts) | Engine MCP port | Dev port | Builder model |
|---|---|---|---|---|---|---|
| Foundation | `loop/foundation` | `<LOOP_DIR>/foundation` | engine project scaffold, core module, capture/perf scripts | 8770 | — | Opus 5.5 high |
| World/City | `loop/city` | `<LOOP_DIR>/city` | exporter, `/Game/City`, city shaders, `build_city.py` | 8771 | 5202 | Sonnet 5.5 xhigh |
| Characters | `loop/characters` | `<LOOP_DIR>/characters` | `/Game/Characters`, import tools, `build_characters.py` | 8772 | 5203 | Sonnet 5.5 xhigh |
| Traversal/controls | `loop/traversal` | `<LOOP_DIR>/traversal` | movement/camera/anim source, `/Game/Traversal` | 8773 | 5204 | Opus 5.5 high |
| Look | `loop/look` | `<LOOP_DIR>/look` | `/Game/Look`, `build_look.py` | 8774 | 5205 | Sonnet 5.5 xhigh |
| Combat | `loop/combat` | `<LOOP_DIR>/combat` | combat source, `/Game/Combat` | 8775 | 5206 | Opus 5.5 high |
| City life | `loop/life` | `<LOOP_DIR>/life` | crowd/traffic/water | 8776 | 5207 | Sonnet 5.5 xhigh |
| Perf | `loop/perf` | `<LOOP_DIR>/perf` | perf harness on the integrated map | 8777 | — | Opus 5.5 high |
| Integrator | `<branch>` | `<INTEGRATION_WORKTREE>` | main map, merges, progress page, ledger | 8765 | 5200 | orchestrator |

Critics: Opus 5.5 high, fresh every round. Director: Fable 5.1 high, at wave boundaries / stalls / acceptance.

Evidence: `docs/loop/<piece>/round-NN/` (captures, clips ≤15 MB, perf JSON, neutral notes), critic texts under `docs/loop/<piece>/critic/`, `HANDOFF.md` per piece rewritten every round.

Protected (never touch): other sessions' checkouts, processes, ports and engine instances; `main`.
