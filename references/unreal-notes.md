# Unreal Engine 5.8 on macOS — notes from the run

## Setup
- Launcher install; owner signs into the Epic launcher. Xcode 27 works with UE 5.8.3 as installed (Apple_SDK.json accepts 15.2–27.9). Install the Metal Toolchain first: `xcodebuild -downloadComponent MetalToolchain`.
- Official MCP: plugins `ModelContextProtocol` + `EditorToolset`; start with `-ModelContextProtocolStartServer -ModelContextProtocolPort=<port>` or project `Config/DefaultEditorPerProjectUserSettings.ini` (`[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings] bAutoStartServer=True ServerPortNumber=<port>`). It exposes `list_toolsets / describe_toolset / call_tool`; `tools/ue_mcp.py` is a tiny client.
- Launch detached: `open -n .../UnrealEditor.app --args <abs uproject> -NoCrashReports -RenderOffScreen -NoSound ...` (a raw binary child dies with the shell; CrashReportClient can steal the MCP port).
- Stop with `pkill -9 -f "<abs path to your uproject>"` — plain kill is ignored; a bare project name kills everyone's editors.
- Don't put projects in `~/Documents` (TCC prompt blocks headless launch).

## Build
- Content-only → C++: add Target files + module, build with `Engine/Build/BatchFiles/Mac/Build.sh <Name>Editor Mac Development -Project=<uproject> -WaitMutex`. When other editors are running, UBT may leave `Binaries/Mac/UnrealEditor.modules` pointing at a deleted dylib: delete the module dylibs + manifest before building.
- No Live Coding on Mac: C++ changes need the editor closed or a separate instance per agent (separate worktree = separate project path).

## Content
- Public GitHub forks refuse new LFS objects; LFS budgets run out. Make `/Game/<Piece>` reproducible from committed, idempotent editor-Python scripts run headless (`-run=pythonscript -script=...`), with source assets committed.
- glTF import: Interchange rejects .webp (convert to PNG), renames bones (`upperArm.R` → `upperarm_r`); scripted imports only complete through `AssetImportTask` with a pipeline-stack override. glTF normal maps are OpenGL-style (flip green).
- Nanite keeps only 4 UV channels — shaders needing more (packed facade data) must stay non-Nanite.
- Materials used on instanced/Nanite meshes need the usage flags saved, or they silently fall back to the default grey material.
- Custom HLSL via `.ush` includes: the editor caches includes — run `recompileshaders changed` after edits.
- Interior-mapped windows at 50–73 % internal res sample the interior atlas 2–4 mips too coarse: bias mips or every room turns into one flat colour.

## Capture
- `-game -RenderOffScreen` gives true 3840×2160 output; default TSR renders internally at 50 %. Fixed-timestep frame dump → ffmpeg for 60 fps video.
- Pre-roll ~0.8 s before recording so auto-exposure settles (otherwise white first frames).
- Mouse safety: `bCaptureMouseOnLaunch=False`, capture mode NoCapture for automation, Escape always releases in the PlayerController.
- Hero-only pixel metrics: a second scene capture rendering only the hero (depth/mask) → bounding box per frame. Use the rendered camera, not a computed one.
