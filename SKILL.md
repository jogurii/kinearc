---
name: kinearc
description: Universal programmatic video, 2D/3D motion graphics, interactive web motion, and 4K production skill with built-in Computer Vision Motion Capture toolkit, Automated Audio Mixer, Interactive Web Workbench (`kinearc_ui.py`), Unified CLI (`kinearc_cli.py`), and Native WebCodecs 4K HTML/Canvas Engine (`engine/render.mjs`). Reverse-engineers clips into 1:1 editable code (MotionClone mode with Savitzky-Golay LUTs, plateau locking, and SVG directional motion blur) and produces broadcast-grade ads, promos, explainers, 3D showcases, scientific animations, and interactive web timelines up to 4K 60fps via HTML/Canvas (`window.kinearc.seek(t)` + `engine/render.mjs`), Remotion (React / @remotion/three), Motion Canvas, Manim, Blender, or FFmpeg.
---

# `kinearc` (v3.0) — Universal 4K Motion, Ad Craft, 2D/3D, Interactive Web, 1:1 Video & Review Engine

`kinearc` is an all-in-one programmatic video and motion engineering framework for AI coding agents. It handles **1:1 cloning**, **new marketing/explainer/3D/interactive-web production up to 4K 60fps**, and **post-production audio/footage finishing**:

1. **Video-to-Code (1:1 MotionClone Mode):** Deconstructs reference videos into pixel-accurate, cinema-smooth editable code (HTML/Canvas, Remotion, Motion Canvas, or GSAP/WAAPI) using its built-in **Computer Vision Motion Capture Toolkit (`scripts/`)**.
2. **Code-to-Video & Interactive Web (Ads, Promos, Explainers, 2D/3D up to 4K):** Plans narrative structure (`references/ad-craft.md`), composes real screen recordings & mixed audio (`references/audio-and-footage.md`), builds deterministic 2D/3D scenes (`references/3d.md`) or scroll-driven web timelines (`references/web-interactive.md`), and renders up to **4K (`3840×2160` / `2160×3840`) @ 60fps** natively via `scripts/kinearc_cli.py` + `engine/render.mjs` (WebCodecs + CDP) or Remotion / Motion Canvas / Manim / Blender.
3. **Interactive Visual & Audio Workbench (`scripts/kinearc_ui.py`):** Launches a zero-build local web UI (`review_viewer.py` remains as a backward-compatible wrapper) with Dual Mode (`Live` HTML scene preview + MP4 `Clone`/`Side-by-Side`/`Split`/`Onion`/`Diff`), platform Safe Zones, `2×` optical loupe, real audio waveform + SFX/SceneCut/Worst-MAE markers, interactive Audio Mix & Cut-Pauses controls, one-click `Render Still` / `Export 1080p 60fps` / `Export 4K 60fps` live progress (`/api/render` -> `Open in Stage / Diff` via `/api/render/load`), and `.kinearc_analysis/selection.json` frame annotations.

---

## 1. Intent Detection & Decision Matrix

```text
                                 USER REQUEST
                                      │
             ┌────────────────────────┴────────────────────────┐
             ▼                                                 ▼
    Input is a Video/Clip?                        Generating New Video or Web Motion?
    (Reference / URL / MP4)                       (Ad / Promo / Explainer / 2D / 3D / Web)
             │                                                 │
     [VIDEO-TO-CODE MODE]                         1. Plan Storyboard & Safe Zones:
     Read: references/video-cloning.md               Read: references/ad-craft.md
     Run:  scripts/extract_full_motion.py         2. Choose Engine by Visual Need:
           scripts/track_objects.py               ┌───────┬───────┬───────┬───────────────┐
           scripts/measure_shapes_colors.py       ▼       ▼       ▼       ▼               ▼
                                               React/  2D Vector Math/   3D      Web / Scroll /
                                               UI/SaaS   TS     Science Scenes   HTML Canvas
                                                  │       │       │       │               │
                                              Remotion Motion   Manim  3d.md     web-interactive.md
                                                       Canvas                    (seek(t)/GSAP/WAAPI)
     [POST-PRODUCTION & REVIEW — Both Modes]
      • Native 4K HTML/Canvas Render & Stills          ─► scripts/kinearc_cli.py render|stills (engine/render.mjs)
      • Voiceover + Auto-Ducked BGM + SFX + Pause Cuts ─► references/audio-and-footage.md + scripts/audio_mix.py
      • Dual Live/MP4 inspection, audio UI, Render & notes ─► scripts/kinearc_ui.py
```

### Reference Guides Index (`references/`)
* **Anti-AI-Slop Visual & Tactile Audio Craft Directive:** `references/anti-ai-slop.md` (mandatory Ban List, Obsidian/Editorial/Optical archetypes, `assets/craft/kinearc-gl3d.js`, 35mm film grain, tactile cursor choreography, and `kinearc_cli.py autocue` micro-timed foley).
* **Native HTML/Canvas Engine & Unified CLI:** `references/kinearc-engine.md` (`scripts/kinearc_cli.py`, `kinearc.project.json`, `window.kinearc.seek(t)` contract, `engine/render.mjs` WebCodecs/CDP 4K export).
* **Cloning:** `references/video-cloning.md` (5-stage CV capture, scene-cut/loop diagnostics, and `--scale=2` 4K reconstruction).
* **Ads / Promos / Explainers:** `references/ad-craft.md` (narrative arcs, `16:9` / `9:16` UI safe zones, continuous motion, pre-render still audit).
* **3D Production:** `references/3d.md` (deterministic `@remotion/three`, Three.js HTML/Canvas `window.kinearc.seek(t)` / `renderAt(t)`, Manim `ThreeDScene`, headless Blender).
* **Interactive Web & Native Canvas:** `references/web-interactive.md` (GSAP `ScrollTrigger`, Web Animations API / `ScrollTimeline`, `motionTracks.ts` integration, `prefers-reduced-motion`, and deterministic `window.kinearc.seek(t)` / `renderAt(t)` with `?t=` & `?scale=2`).
* **Audio & Screen Footage:** `references/audio-and-footage.md` (`audio_mix.py` auto-ducking & SFX `cues.json`, pause cutting, `<OffthreadVideo>` device mockups).
* **Engines:** `references/kinearc-engine.md`, `references/remotion.md`, `references/motion-canvas.md`, `references/manim.md`, `references/web-interactive.md`, `references/ffmpeg.md`.

### 4K Output Support Across Every Mode
* **Native HTML/Canvas (`kinearc_cli.py` + `engine/render.mjs`) & Remotion:** Author at logical `1920×1080` (`16:9`) or `1080×1920` (`9:16`), preview `?scale=2` live in `kinearc_ui.py`, and render sharp **3840×2160 / 2160×3840 @ 60fps** via `python "<skill_dir>/scripts/kinearc_cli.py" render --project kinearc.project.json --out out_4k.mp4 --scale 2` (or one-click **`Export 4K 60fps`** in `kinearc_ui.py`), or `npx remotion render ... --scale=2` without touching CSS font scales.
* **Manim / Motion Canvas / Blender:** Pass `-qk --fps 60` (Manim), Scale `2` / `3840×2160` (Motion Canvas), or `resolution_x=3840, resolution_y=2160` (Blender).

---

## 2. Built-in Engine, Computer Vision, Audio & Review Toolkit (`scripts/` & `engine/` — v3.0)

Located inside `<skill_dir>/scripts/` and `<skill_dir>/engine/` (all analysis scripts default to `.kinearc_analysis/` and accept explicit `--out_dir` overrides cleanly):
1. **`kinearc_cli.py` + `engine/render.mjs` (`engine/browser_find.mjs`):**
   * Unified CLI (`doctor`, `stills`, `render`, `autocue`, plus direct passthrough to `extract`, `extract-audio`, `sfx-pack`, `track`, `measure`, `verify`, `ui`, `audio`).
   * Validates `kinearc.project.json` manifests (even-dimension clamping, scene/audio asset checks), auto-discovers Chrome/Edge/Chromium across Windows/macOS/Linux, and drives zero-npm Headless Chromium WebCodecs (`VideoEncoder` Annex-B H.264) + CDP PNG fallback up to **4K 60fps** (`--scale 2`, `--json-progress`) with automatic `audio_mix.py` voice/BGM/SFX muxing (`references/kinearc-engine.md`).
2. **`extract_full_motion.py`:** Extracts 100% of frames at native FPS (auto-preserving HD resolution `>= 720px` up to `1920px`), builds dense 30-frame contact sheets, generates **RGB Chrono-Motion Trail sheets** (`Red = Past → Green = Mid → Blue = Present`), exports hard-cut diagnostics to `.kinearc_analysis/scene_cuts.json` (with before/after transition pairs in `.kinearc_analysis/cuts/`, configurable via `--cut-threshold`), and records `source_loop_mae` inside `.kinearc_analysis/metadata.json`.
3. **`track_objects.py`:**
   * **Zero-Jitter Savitzky-Golay Filtering & Hold-Plateau Locking:** Smooths contour quantization noise and locks stationary windows (`cx_is_stationary_plateau`) so resting logos/icons never vibrate.
   * **3-Phase Container Segmenter (`CONTAINER_PHASES`):** Automatically segments container trajectories into `ENTER_SETTLE → HOLD_PLATEAU (STATIONARY) → EXIT_LIFT` so containers never drift during stationary holds.
   * **Universal Salient Icon Tracker & 60/120-FPS `sampleLUT`:** Tracks icons across any color hue (`0..180`), preserves continuous rotation & overshoot curves (`ICON_ANGLE_DEG`, `ICON_SIZE`), and exports Catmull-Rom sub-frame interpolation (`sampleLUT`) to `.kinearc_analysis/motion_tracks.json` and `.kinearc_analysis/motionTracks.ts`.
   * **Independent Multi-Particle Tracker (`PARTICLE_TRACKS`):** Tracks clockwise (`+dAngle`), counter-clockwise (`-dAngle`), and radial particle paths.
4. **`measure_shapes_colors.py`:**
   * **Active Card Bop-Scale Profiler (`card_bop_summary`):** Automatically measures idle vs active highlighted card dimensions and outputs the exact `bop_scale_ratio` (e.g. `1.074x` elastic pop when selected) to `.kinearc_analysis/geometry_report.json` (`--out_dir` or `--out` overrides cleanly).
   * **Radial Circle/Ring Profiler:** Measures exact center, inner/outer radius, stroke thickness, and 8-angle hex gradient stops.
5. **`verify_motion_diff.py`:**
   * Audits per-frame Pixel MAE/PSNR (time-synchronized across 30/60/120 FPS), Optical Flow Direction Similarity, **Unwanted Jitter/Hold-Drift (`jitter_or_drift_warnings`)**, **Missing Directional Motion Blur (`missing_motion_blur_warnings`)**, severity-ranked **`worst_frames`** (descending MAE with `rank` and `timestamp_sec`), and optional **`--check-loop`** seam auditing (`clone_loop_mae` + `loop_warnings`) inside `.kinearc_analysis/verification_report.json`.
6. **`kinearc_ui.py` (with `review_viewer.py` backward-compatible wrapper):**
   * Zero-build local Interactive Web Workbench (`http://127.0.0.1:4175`, served from `scripts/ui/`) accepting an MP4 render, `--scene path/to/scene.html`, and/or `--project kinearc.project.json`, plus `--ref`, `--voice`, `--bgm`, `--sfx`, `--out_dir` (default `.kinearc_analysis`), `--port`, and `--no-open`.
   * **Dual Mode Stage:** Switch between **`Live` Scene** (drives `window.kinearc.seek(t)` / `renderAt(t)` inside an aspect-locked iframe with multi-scene switching) and **MP4 Diff** modes (`Clone`, `Side-by-Side`, `Split`, `Onion`, `Diff` 4× error heatmap, cross-FPS synced against `--ref`).
   * **Inspection Overlays & Timeline:** Platform **Safe Zones** (`9:16`, `16:9`, `1:1`, `thirds`), interactive **`2×` Loupe**, frame stepping, real audio **Waveform** (`/api/audio-peaks`), Loop Seam status pill, and clickable **SceneCut** (`scene_cuts.json`), **Worst-MAE** (`verification_report.json`), and **SFX** (`cues.json`) timeline markers.
   * **Inspector Drawer (`Notes` / `QA` / `Audio & Out`):** Pin click/drag-box notes saved to `.kinearc_analysis/selection.json` + `selection/note_<id>.png` (`Copy Prompt`), jump directly to `worst_frames` and `scene_cuts` pairs in `QA`, trigger **`Trim Pauses`** (`cut-pauses`) and **`Auto-Duck Mix`** (`audio_mix`) into `.kinearc_analysis/renders/`, and run one-click **`Render Still`**, **`Export 1080p 60fps`**, or **`Export 4K 60fps`** via `/api/render` with live frame progress (`GET /api/render/<job_id>`) and **`Open in Stage / Diff`** (`POST /api/render/load`) into `Stage`.
7. **`audio_mix.py` + `auto_cue.py` + `extract_audio_style.py` + `assets/sfx/`:**
   * **`extract_audio_style.py` (`kinearc_cli.py extract-audio`):** Analyzes any reference video/audio's 5-band spectral balance, stereo width, and silence profile (`audio_profile.json`), slices isolated onset stems (`stems/`), and optionally remakes a 100% copyright-clean custom SFX pack via `build_sfx_pack.py --profile`.
   * **`auto_cue.py` (`autocue`):** Parses `@cue` and `@scene-audio` directives (plus automatic scene material, luminance, temperature & space inference), rotates round-robin variants, applies psychoacoustic pre-rolls, and outputs per-scene tone/room-tagged `cues.json` mapped to `assets/sfx/` (`airy-clean`, `tactile-wood`, `crisp-glass`, `cinematic-sub`).
   * **`audio_mix.py` (`audio`):** Sample-accurate stereo SFX bus compositor (Haas panning, deterministic micro-variation, per-cue `tilt_db`/`cutoff_hz`/`sub_boost` filtering, weighted room-reflection convolution IR) + FFmpeg voiceover/BGM sidechain ducking (`mix`) and dead-air trimmer (`cut-pauses`).

---

## 3. Mandatory Broadcast-Quality Rules for MotionClone Reconstruction (v2.1)

1. **Zero Jitter on Resting Elements:** Never use unsmoothed raw pixel LUTs during a stationary hold. Lock coordinates to the plateau constant when an icon/card is at rest, and use smooth cubic bezier curves (`Easing.bezier(0.16, 1, 0.3, 1)`) between inflection keyframes.
2. **Parent-Child Spatial Anchoring:** Icons inside stretching or moving containers (e.g. a star inside an expanding search pill) MUST be positioned relative to the parent container's inner edge (`left: interpolate(stretchP, [0, 1], [centerOffset, 26])`) so they move in 100% lockstep with the container's elastic bounce.
3. **Strict Hold-Plateau Discipline:** Respect `HOLD_PLATEAU` windows from `track_objects.py`. Do not linearly interpolate across a stationary hold phase.
4. **Authentic Card Bop / Pop Animation:** Apply the full measured `bop_scale_ratio` (e.g. `scale: 1.08` with a brief spring overshoot to `1.095` on selection) when grid cards or buttons activate.
5. **True Directional Shutter Motion Blur:** Use inline SVG `<feGaussianBlur stdDeviation="blurX blurY" />` (`<DirectionalBlur>`) driven by instantaneous velocity $(v_x, v_y)$ along the axis of movement rather than uniform isotropic CSS `blur()`.

---

## 4. Mandatory Broadcast-Quality Rules for Ads, Explainers & 3D (v3.0)

1. **`9:16` Safe-Zone Discipline:** For vertical Reels/Shorts/TikTok (`1080×1920` base), keep all essential copy, UI mockups, and CTAs inside `x: [72..930]`, `y: [220..1560]` (read `references/ad-craft.md`).
2. **Deterministic 3D & Canvas Only:** In `@remotion/three`, HTML/Canvas Three.js (`window.kinearc.seek(t)` / `renderAt(t)`), Manim `ThreeDScene`, or Blender, drive every transform from frame/time (`useCurrentFrame()` / `seek(t)` / `renderAt(t)`) — never wall-clock timers (read `references/3d.md`, `references/web-interactive.md`, and `references/kinearc-engine.md`).
3. **Continuous Motion & Still-Audit Gate:** Never leave dead static screens; keep subtle camera drift/ambient motion, and verify 4 key storyboard stills (`kinearc_cli.py stills`, `npx remotion still`, or `kinearc_ui.py` `Render Still`) before final **4K (`--scale 2` / `-qk`)** export.
4. **Audio Finishing & Real Footage:** Use `<OffthreadVideo>` for screen recordings, tighten pauses (`audio_mix.py cut-pauses`), and mix BGM auto-ducking + SFX (`audio_mix.py mix`) cleanly without re-encoding video (read `references/audio-and-footage.md`).
