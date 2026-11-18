# Changelog

All notable changes to `kinearc` are documented in this file.

## v3.0.0 — 2026-11-18

### Standalone Engine & CLI
- Added zero-dependency Node.js 24+ Headless Chromium WebCodecs/CDP 4K render engine (`engine/package.json`, `engine/browser_find.mjs`, `engine/render.mjs`) with automatic two-tier frame capture (in-page WebCodecs `VideoEncoder` for `<canvas>`/WebGL and automatic CDP PNG-pipe fallback for pure DOM/SVG scenes).
- Added unified cross-platform CLI entrypoint (`scripts/kinearc_cli.py`) supporting `doctor` (`--json`, `--strict`), `render` (`--scale 2`, `--crf`, `--json-progress`), `stills`, and direct passthrough for all CV/audio/UI subcommands.
- Added pre-flight `kinearc.project.json` schema validation (`validate_manifest`) with automatic even-integer dimension clamping for H.264 `yuv420p` and relative audio path resolution.
- Updated `scripts/audio_mix.py` so SFX cue paths inside `cues.json` resolve cleanly relative to `cues.json` or the project folder in addition to CWD.
- Added `references/kinearc-engine.md` documenting `window.kinearc`, `kinearc.project.json`, WebCodecs capture rules, and CLI flags.

### Interactive 60 FPS Workbench UI
- Integrated live server-side rendering via `POST /api/render`, `GET /api/render/<job_id>`, and `POST /api/render/load` hot-swap in `scripts/kinearc_ui.py` with atomic 10-field geometry rollback on invalid loads.
- Added real-time render progress bar and one-click `Open in Stage / Diff` workflow in `scripts/ui/drawer.js` and `scripts/ui/app.js`.
- Added multi-phase `ImageBitmap` background pre-warming cache (`240` frames, `clone` + `ref` + `4x diff`) and synchronous 60Hz playback in `scripts/ui/stage.js` + `scripts/ui/timeline.js`, paired with persistent sequential `cv2.VideoCapture` and LRU frame caches in `scripts/kinearc_ui.py` so all six modes (`Live`, `Clone`, `Side-by-Side`, `Split`, `Onion`, `Diff`) scrub and play smoothly at 60 FPS.
- Added timeline clip range revision annotations (`[ In` / `Out ]` buttons, `I` / `O` shortcuts, `Shift+Drag` on timeline, amber `.timeline-note-range` bars) and right-click (`contextmenu`) deletion on draft markers, saved stage pins/boxes, and timeline range bars in `scripts/ui/annotations.js`.

### Examples & GitHub Packaging
- Added zero-dependency WebGL2 3D + Glassmorphic HUD demo showcase (`examples/kinearc-promo-3d/`) and interactive 5-step tutorial project (`examples/kinearc-tutorial/`) complete with synthesized BGM and beat-synced SFX cues.
- Added one-command cross-platform installer (`install.py`), MIT `LICENSE`, `ROADMAP.md`, `CONTRIBUTING.md`, `SECURITY.md`, and GitHub Actions CI matrix workflow (`.github/workflows/ci.yml`).

---

## v2.0.0 — 2026-11-17

- Built the zero-build modular web workbench UI (`scripts/kinearc_ui.py` + `scripts/ui/{index.html,styles.css,stage.js,timeline.js,annotations.js,drawer.js,app.js}`).
- Added Dual Viewport modes (`Live` iframe + MP4 `Clone`, `Side-by-Side`, `Split`, `Onion`, `4x Diff`), `2x` optical pixel loupe, platform safe-zone overlays (`9:16`, `16:9`, `1:1`, `thirds`), real audio waveform + QA/SFX markers, interactive audio pause-cutting/auto-ducking controls, and `.kinearc_analysis/selection.json` point/box note annotations.

---

## v1.0.0 — 2026-11-17

- Established the `kinearc` identity, clean separation of 1:1 CV motion capture (`scripts/extract_full_motion.py`, `scripts/track_objects.py`, `scripts/measure_shapes_colors.py`, `scripts/verify_motion_diff.py`) and audio finishing (`scripts/audio_mix.py`).
- Added scene cut detection (`scene_cuts.json`, `cuts/`), loop seam MAE auditing (`--check-loop`), `.kinearc_analysis` default output paths, and `tests/` hygiene & unit test suites.
