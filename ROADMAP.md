# Roadmap

Planned improvements, unbuilt capabilities, and platform validation goals for `kinearc`. Items listed here are engineering priorities rather than fixed release promises.

## Not Built Yet

- **Synchronized WebAudio during MP4 timeline playback:** Today the timeline renders real audio waveforms and supports interactive `Trim Pauses` / `Auto-Duck Mix`, while browser playback in `Clone`, `Side-by-Side`, `Split`, `Onion`, and `Diff` drives visual frames without live WebAudio output (audio is muxed cleanly into exported MP4 renders).
- **Transparent video output (`WebM VP9 Alpha` / `ProRes 4444`):** Needed for standalone transparent motion overlays and compositing plates.
- **Selective scene re-rendering (`--only`):** Multi-scene projects already produce per-scene MP4 segments prior to FFmpeg concatenation and audio muxing; exposing a cached segment flag such as `--only 3` would skip unchanged scenes during iterative edits.
- **Parallel multi-worker scene rendering:** Exporting scenes concurrently across bounded Chromium workers on multi-core hosts, with clean fallback to sequential rendering when memory or hardware encoder sessions are constrained.
- **Editable & bulk-manageable annotations in the Workbench UI:** Dragging/resizing saved annotation boxes in place on `#overlayCanvas`, plus one-click archival or bulk deletion of `done` notes in `.kinearc_analysis/selection.json`.
- **Single-command MP4 export with custom GLSL transitions:** Declaring shader transitions directly inside `kinearc.project.json` between adjacent scene entries.

## Platform Validation Status

- **Windows 11:** Verified end-to-end across Chrome/Edge, Node.js `v24.16.0`, Python `3.14.7`, OpenCV `5.0.0`, and FFmpeg `9.0.2`, including WebCodecs 4K H.264 rendering, CDP PNG fallback, mixed-scene concat, audio muxing, and live Playwright/Chrome browser UI tests.
- **Linux (`ubuntu-latest` CI):** Automated syntax checks, unit tests, and headless Chromium renders execute in GitHub Actions (`.github/workflows/ci.yml`), typically using software rendering (`SwiftShader`) without a dedicated GPU.
- **macOS:** Darwin Chrome discovery paths are implemented in `engine/browser_find.mjs` and `scripts/kinearc_cli.py`, but real macOS hardware VideoToolbox renders and Apple Silicon benchmarks remain untested on physical hardware.
- **Optional external pipelines:** Remotion, Motion Canvas, Manim, and Blender 3D workflows are documented in `references/`; real-world CI runners only exercise the zero-dependency built-in WebCodecs/CDP + CV + Audio toolkit by default.
