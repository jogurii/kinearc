# Video-to-Code (1:1 MotionClone Mode — v2.1) Reference Guide

This guide defines the mandatory **5-Stage 1:1 Computer-Vision Motion Capture Protocol (v2.1)** for reconstructing a reference video into editable code with zero jitter, exact parent-child anchoring, true directional shutter motion blur, and broadcast-grade physics.

---

## The 6 Golden Laws of 1:1 Motion Reconstruction (v2.1)

1. **Zero-Jitter Signal Filtering & Hold-Plateau Locking:**
   * Raw contour bounding boxes from compressed video have $\pm 1.5\text{ px}$ quantization noise. Never feed unsmoothed raw pixel arrays directly into `left/top/size` during a stationary hold.
   * Always use the Savitzky-Golay smoothed & plateau-locked arrays from `track_objects.py` v2.1, or interpolate with smooth `Easing.bezier()` between measured **inflection keyframes** (`start → overshoot_peak → hold_plateau → exit`).
2. **Strict 3-Phase Hold Discipline (`ENTER → HOLD_PLATEAU → EXIT`):**
   * Check `upper_bubble_phases` (and container plateaus) in `motion_tracks.json`.
   * When a container settles into a `HOLD_PLATEAU` (e.g. `f120–143 at constant_y = 273px`), keep its position **100% stationary** during the hold! Never connect an early entrance frame (`f116`) to a late exit frame (`f150`) with a linear slope that causes unnatural upward creep.
3. **Parent-Child Spatial Anchoring:**
   * When an icon, badge, or label sits inside an expanding or moving container (such as a star inside a stretching search pill), **anchor the child inside the parent container's coordinate system** (e.g. `left: interpolate(stretchP, [0, 1], [centerOffset, 26])` inside the pill `div`). Never drive a child icon from detached world coordinates while its parent container stretches.
4. **Active Card Bop / Pop Scale (`card_bop_summary`):**
   * Check `card_bop_summary` in `geometry_report.json` (from `measure_shapes_colors.py` v2.1).
   * When a card or grid tile becomes active/selected, apply the measured **`bop_scale_ratio`** (typically `1.08x` / `+8%` with a subtle spring overshoot to `1.095x` on activation), not a barely visible `1.02x`.
5. **True Directional Shutter Motion Blur (`<feGaussianBlur stdDeviation="dx dy">`):**
   * Standard CSS `filter: blur(Npx)` blurs equally in X and Y (like an out-of-focus camera).
   * Real After Effects 180° shutter motion blur is **directional and velocity-proportional**:
     * Horizontal movement (`vx`) requires horizontal blur (`stdDeviation="blurX 0"`).
     * Vertical movement (`vy`) requires vertical blur (`stdDeviation="0 blurY"`).
     * Blur peaks at **maximum instantaneous velocity** (mid-flight, proportional to $|x(f) - x(f-1)|$), and reaches `0` the instant the element settles.
6. **Independent Multi-Particle Trajectories:**
   * In particle/constellation scenes, drive each orb from its tracked keyframes in `PARTICLE_TRACKS` so clockwise (`+dAngle`), counter-clockwise (`-dAngle`), and radial paths are preserved individually.

---

## The 5-Stage 1:1 Motion Capture Pipeline

```
[Stage 1: Full-FPS, RGB Motion Trails, Scene Cuts & Loop Seam MAE]
   python <skill_dir>/scripts/extract_full_motion.py input.mp4 [--out_dir .kinearc_analysis] [--cut-threshold 18.0]
        │
        ▼
[Stage 2: Zero-Jitter LUTs, 3-Phase Plateaus & Particle Tracking]
   python <skill_dir>/scripts/track_objects.py input.mp4 [--out_dir .kinearc_analysis]
        │
        ▼
[Stage 3: Radial Circle Profiler, Card Bop Scale & HEX Sampling]
   python <skill_dir>/scripts/measure_shapes_colors.py input.mp4 <key_frames...> [--out_dir .kinearc_analysis]
        │
        ▼
[Stage 4: Production-Grade Reconstruction (Anchored Hierarchy + Directional Blur)]
   Build Remotion, Motion Canvas, or deterministic web/HTML-Canvas components with velocity-driven directional blur
        │
        ▼
[Stage 5: Closed-Loop MAE + Ranked Worst Frames + Flow + Jitter/Blur + Loop Verification Gate]
   python <skill_dir>/scripts/verify_motion_diff.py input.mp4 output.mp4 [--check-loop]
```

### Stage 1 Outputs (`.kinearc_analysis/`, overridable via `--out_dir`)
* `frames_all/`, `contact_sheets/`, `motion_trails/`: 100% extracted frames, 30-frame contact sheets, and FPS-adaptive RGB chrono-motion trail sheets.
* `scene_cuts.json` & `cuts/cut_XXXX.png`: Hard scene-cut timestamps (`delta_mae >= --cut-threshold`, default `18.0`) paired with labeled before/after transition PNGs for multi-scene planning.
* `metadata.json`: Resolution, FPS, high-motion frame indices, and `source_loop_mae` (first-vs-last frame MAE to detect seamless loops early).

---

## Reusable True Directional Motion Blur Helper (Remotion / React)

Include this helper in `src/theme.ts` (or a shared component) so every fast slide, stretch, and reveal has authentic After Effects directional shutter blur:

```tsx
import React from 'react';

/**
 * Renders an inline SVG directional Gaussian blur filter (`stdDeviation="blurX blurY"`)
 * driven by instantaneous frame velocity (dx, dy).
 */
export const DirectionalBlur: React.FC<{
  id: string;
  dx?: number;
  dy?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ id, dx = 0, dy = 0, children, style }) => {
  const bx = Math.min(28, Math.max(0, Math.abs(dx)));
  const by = Math.min(28, Math.max(0, Math.abs(dy)));
  const active = bx > 0.25 || by > 0.25;
  return (
    <div style={{ ...style, filter: active ? `url(#dirblur-${id})` : undefined }}>
      {active && (
        <svg width={0} height={0} style={{ position: 'absolute' }}>
          <defs>
            <filter id={`dirblur-${id}`} x="-35%" y="-35%" width="170%" height="170%">
              <feGaussianBlur in="SourceGraphic" stdDeviation={`${bx.toFixed(2)} ${by.toFixed(2)}`} />
            </filter>
          </defs>
        </svg>
      )}
      {children}
    </div>
  );
};
```

### Velocity-Driven Reveal Pattern (Bell-Curve Shutter Blur):
Instead of blurring most when `opacity = 0` (`(1 - p) * maxBlur`), combine a gentle entrance focus blur with a **velocity bell curve** (`Math.sin(p * Math.PI)`) along the axis of movement:

```tsx
export const revealX = (
  frame: number,
  start: number,
  dur = 11,
  dist = 64,
  maxBlurX = 16
): { style: React.CSSProperties; blurX: number } => {
  const p = prog(frame, start, start + dur);
  // Instantaneous velocity peaks during the fast initial/mid sweep and hits 0 at settle (p=1)
  const velBlur = Math.sin(Math.pow(p, 0.65) * Math.PI) * maxBlurX * (1 - p * 0.35);
  return {
    blurX: frame >= start && frame < start + dur ? velBlur : 0,
    style: {
      opacity: interpolate(p, [0, 0.35, 1], [0, 0.85, 1], clamp),
      transform: `translateX(${(1 - p) * dist}px)`,
    },
  };
};
```

---

## Stage 5: Verification Gate Criteria (`verify_motion_diff.py` v2.1)

Run (defaults to `--out_dir .kinearc_analysis`; pass `--out_dir` to override cleanly):
```bash
python "<skill_dir>/scripts/verify_motion_diff.py" input.mp4 output_clone.mp4 --out_dir .kinearc_analysis --check-loop
```

Check `.kinearc_analysis/verification_report.json` and `.kinearc_analysis/motion_audit_sheet.png`:
1. **`overall_mae` < 6.0** and **`max_mae` < 16.0** (triage the highest-error moments first via severity-ranked **`worst_frames`**, sorted by descending MAE with `rank` and `timestamp_sec`).
2. **`jitter_or_drift_warnings_count` == 0** (no vibrating icons or drifting hold plateaus).
3. **`missing_motion_blur_warnings_count` minimized** (all high-speed transitions use directional blur).
4. **Loop Seam Audit (`--check-loop`):** For seamless loops/stingers, inspect **`clone_loop_mae`** and **`loop_warnings`** (`BROKEN_LOOP_SEAM` triggers if first vs last frame MAE exceeds `6.0`).
5. Export synchronized side-by-side comparison video (`Original | Reconstructed`).

---

## Stage 6 (Optional): Interactive Web Workbench & QA Inspection (`kinearc_ui.py`)

When the user wants to inspect the live HTML scene or rendered MP4 frame by frame, jump through QA diagnostics, adjust audio, or pin revision notes (`scripts/review_viewer.py` remains available as a backward-compatible CLI/module wrapper):

```bash
# MP4 + reference comparison + audio waveform/mixing tracks
python "<skill_dir>/scripts/kinearc_ui.py" output_clone.mp4 \
  --ref input.mp4 \
  --voice voice.wav --bgm soundtrack.mp3 --sfx cues.json \
  --out_dir .kinearc_analysis

# Dual Mode: inspect a live interactive HTML scene alongside rendered MP4 + reference
python "<skill_dir>/scripts/kinearc_ui.py" output_clone.mp4 \
  --scene scene.html --ref input.mp4 --out_dir .kinearc_analysis
```

* **CLI Flags:**
  * Positional `clone`: optional rendered MP4 (omit when previewing `--scene` or `--project kinearc.project.json` standalone).
  * `--ref`: reference video for `Side-by-Side`, `Split`, `Onion`, and `Diff` (cross-FPS time-aligned automatically).
  * `--scene` / `--project`: live deterministic HTML scene (`window.kinearc.seek(t)` / `renderAt(t)`) or multi-scene manifest (`kinearc.project.json`).
  * `--voice`, `--bgm`, `--sfx`: audio tracks and `cues.json` for timeline waveform rendering, SFX markers, and live `Audio & Out` controls (`--out_dir` defaults to `.kinearc_analysis`, `--port` defaults to `4175`, `--no-open` skips auto-launching the browser).
* **Capabilities & QA Jump Workflow:**
  * Opens a zero-build local web workbench at `http://127.0.0.1:4175/` with Dual Mode viewport (`Live`, `Clone`, `Side-by-Side`, `Split`, `Onion`, `Diff` 4× amplified heatmap), SVG Safe Zone overlays (`9:16`, `16:9`, `1:1`, `thirds`), and a `2×` optical pixel loupe.
  * **QA Jump Workflow (`QA` tab & Timeline Markers):** Automatically loads `.kinearc_analysis/verification_report.json` (`overall_mae`, `overall_psnr_db`, `clone_loop_mae`, top-5 severity-ranked **`worst_frames`**) and `.kinearc_analysis/scene_cuts.json` (**`scene_cuts`** with `cuts/cut_*.png` pairs). Click any **`Jump`** button in the `QA` drawer—or click Worst-MAE / Scene-Cut / SFX markers on the timeline—to seek directly to that frame and verify alignment via `Split`/`Diff` + `2×` Loupe.
  * **Visual Annotations (`Notes` tab):** Supports frame-by-frame stepping (`←` / `→`), drag-box or click pins, and saves all notes to `.kinearc_analysis/selection.json` alongside annotated frame snapshots in `.kinearc_analysis/selection/note_<id>.png` (`Copy Prompt` / `Copy AI Prompt` builds a ready-to-paste revision list).
* **Revision Round Workflow:**
  * Whenever the user asks to apply review notes (e.g. *"Fix the notes in the viewer"* or *"Apply selection.json"*):
    1. Read `.kinearc_analysis/selection.json` and inspect every `selection/note_<id>.png` with status `"open"`.
    2. Fix each issue directly in code, update `"status": "done"` in `selection.json`, re-render, and re-run `verify_motion_diff.py`.

---

## Cloning or Exporting in 4K (`3840×2160` / `2160×3840`)

When `input.mp4` is 4K—or when the user requests a **4K reconstructed export** from a 720p/1080p reference:

1. **Track in Logical HD (`<= 1920px` wide) for Speed & Memory Safety:**
   * `track_objects.py` automatically caps default analysis width at `1920` (`min(1920, max(720, orig_w))`), or pass `--width 1080` (for `9:16` vertical `1080×1920`) / `--width 1920` (for `16:9` horizontal `1920×1080`).
2. **Author the Code in Logical 1080p (`1920×1080` or `1080×1920`):**
   * Convert tracked coordinates (`ICON_CX`, `ICON_CY`, `PARTICLE_TRACKS`) proportionally (`targetW / work_w`) into your Remotion, Motion Canvas, or HTML/Canvas (`window.kinearc.seek(t)`) 1080p composition.
   * Run `verify_motion_diff.py` at 1080p (`verify_motion_diff.py` auto-resizes to common comparison geometry).
3. **Export Crisp 4K via 2× Deterministic Scaling:**
   * **Remotion:** `npx remotion render src/index.ts Main out_4k.mp4 --scale=2 --crf=16`
   * **Motion Canvas / Native HTML Canvas (`engine/render.mjs`):** Set Motion Canvas scale to `2` (`3840×2160`), or export deterministic `window.kinearc.seek(t)` / `renderAt(t)` HTML/Canvas scenes (`references/kinearc-engine.md`, `references/web-interactive.md`) at 4K via `python "<skill_dir>/scripts/kinearc_cli.py" render --project kinearc.project.json --out out_4k.mp4 --scale 2` (or one-click `Export 4K 60fps` inside `kinearc_ui.py`)—vector paths, SVG filters, and text re-rasterize cleanly at 2× for lossless 4K sharpness.
