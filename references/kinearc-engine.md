# `kinearc` Native HTML/Canvas Engine & CLI Reference Guide

Use this guide when authoring, validating, previewing, or exporting deterministic HTML, SVG, 2D `<canvas>`, GSAP, WAAPI, or Three.js WebGL scenes through the unified `kinearc` CLI (`scripts/kinearc_cli.py`).

---

## 1. Prerequisites

* **Node.js `24+`:** Required by the native `engine/render.mjs` WebCodecs/CDP capture pipeline.
* **Browser (`Chrome` / `Edge` / `Chromium`):** Auto-discovered on Windows, macOS, and Linux, or set explicitly via `CHROME_PATH`.
* **FFmpeg & FFprobe:** Required on `PATH` for muxing, audio ducking, and video probing.
* **Python `3.9+` (`opencv-python`, `numpy`):** Required for the CV motion toolkit, workbench UI, and manifest validation.

Verify your host setup anytime:

```bash
python "<skill_dir>/scripts/kinearc_cli.py" doctor
python "<skill_dir>/scripts/kinearc_cli.py" doctor --json --strict
```

---

## 2. Project Layout & `kinearc.project.json` Schema

Organize multi-scene deliverables cleanly with a root `kinearc.project.json` manifest:

```text
my-project/
├── kinearc.project.json
├── scenes/
│   ├── 01_hook.html
│   └── 02_cta.html
└── audio/
    ├── voice.wav
    ├── bgm.mp3
    └── cues.json
```

### `kinearc.project.json`

```json
{
  "fps": 60,
  "width": 1920,
  "height": 1080,
  "scenes": [
    { "path": "scenes/01_hook.html", "duration": 3.5 },
    { "path": "scenes/02_cta.html", "duration": 2.5 }
  ],
  "audio": {
    "voice": "audio/voice.wav",
    "bgm": "audio/bgm.mp3",
    "sfx": "audio/cues.json",
    "voice_vol": 1.0,
    "bgm_vol": 0.35,
    "video_vol": 1.0,
    "fade_out": 1.5,
    "keep_video_audio": false
  }
}
```

* **`fps`, `width`, `height`:** Base logical canvas dimensions and target frame rate (default `1920×1080 @ 60`). Scaled pixel dimensions are automatically clamped down to even integers (`>= 2`) for H.264 `yuv420p` compatibility.
* **`scenes`:** Non-empty list of relative/absolute `.html` paths or `{ "path", "duration" }` objects (`"file"`, `"src"`, `"html"`, and `"total"` aliases are also supported). Every path is validated before Chromium launches.
* **`audio` (optional):** Omit or pass `null` when silent. When provided, `"voice"`, `"bgm"`, and `"sfx"` (`cues.json`, e.g. `[{"file": "sfx/pop.wav", "time": 1.2, "volume": 0.85}]`) resolve relative to the manifest directory and pass directly into `audio_mix.py` auto-ducking defaults.

---

## 3. Mandatory Deterministic Page Contract

Every HTML/Canvas/WebGL scene must be **100% time-driven** (never driven by `requestAnimationFrame` delta timers or wall-clock `Date.now()`) and expose:

1. **`window.kinearc = { totalDuration, ready, seek(t) }`:**
   * `totalDuration` (`number`): Total timeline duration in seconds (also set `window.TOTAL = totalDuration`).
   * `ready` (`Promise<void>`): Resolves once fonts, textures, images, and initial layout have settled (also set `window.ready = ready`).
   * `seek(t)` (`(t: number) => void`): Synchronously renders exact visual state at `t` seconds (also set `window.renderAt = seek`).
2. **Query Parameter Support (`?t=` & `?scale=`):**
   * `?t=<seconds>`: Seek immediately to `t` on initial load for still-frame inspection.
   * `?scale=2`: Scale `<canvas>` backing buffers (`canvas.width = W * S`, `canvas.height = H * S`, or `renderer.setPixelRatio(S)`) for crisp 4K (`3840×2160` / `2160×3840`) without changing logical coordinates.
3. **WebGL & Microtask Capture Rules:**
   * Initialize WebGL with `preserveDrawingBuffer: true` (e.g. `new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true })`) so CDP frame capture never reads a cleared backbuffer.
   * Complete all draw calls synchronously inside `seek(t)` / `renderAt(t)` so microtask-level capture after `seek(t)` always sees the completed frame.

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><title>kinearc Deterministic Scene</title></head>
<body style="margin:0;overflow:hidden;background:#09090b;">
<canvas id="c"></canvas>
<script>
const q = new URLSearchParams(location.search);
const rawScale = parseFloat(q.get("scale") || "");
const S = Number.isFinite(rawScale) && rawScale > 0 ? rawScale : 1;
const W = 1920, H = 1080;
const canvas = document.getElementById("c");
canvas.width = W * S;
canvas.height = H * S;
canvas.style.width = "100vw";
canvas.style.height = "100vh";
const ctx = canvas.getContext("2d");

const TOTAL = 4.0;
const seek = (t) => {
  ctx.setTransform(S, 0, 0, S, 0, 0);
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#09090b";
  ctx.fillRect(0, 0, W, H);
  // Deterministic math from `t` only
};

const rawT = parseFloat(q.get("t") || "");
const initialT = Number.isFinite(rawT) && rawT > 0 ? rawT : 0;
const ready = document.fonts.ready.then(() => seek(initialT));
window.TOTAL = TOTAL;
window.ready = ready;
window.renderAt = seek;
window.kinearc = { totalDuration: TOTAL, ready, seek };
</script>
</body>
</html>
```

---

## 4. Fast CLI Usage (`scripts/kinearc_cli.py`)

```bash
# 1. Verify runtime dependencies (Python CV, FFmpeg/FFprobe, Node 24+, Chrome/Edge)
python "<skill_dir>/scripts/kinearc_cli.py" doctor

# 2. Render storyboard still PNGs before full video export
python "<skill_dir>/scripts/kinearc_cli.py" stills \
  --scene scenes/01_hook.html \
  --out_dir .kinearc_analysis/stills \
  --times 0,0.8,1.6,3.0 \
  --scale 1

# 3. Render 1080p master MP4 from project manifest or standalone HTML scene
python "<skill_dir>/scripts/kinearc_cli.py" render \
  --project kinearc.project.json \
  --out out_1080p.mp4 \
  --crf 16

# 4. Export crisp 4K (3840x2160 for 16:9, or 2160x3840 for 9:16) with live JSON progress
python "<skill_dir>/scripts/kinearc_cli.py" render \
  --project kinearc.project.json \
  --out out_4k.mp4 \
  --scale 2 \
  --crf 16 \
  --json-progress

# 5. Launch the interactive Dual Live + MP4 Workbench UI
python "<skill_dir>/scripts/kinearc_cli.py" ui --project kinearc.project.json
```

`kinearc_cli.py` also forwards `extract`, `track`, `measure`, `verify`, `ui`, and `audio` directly to the corresponding `scripts/*.py` modules with all flags preserved.
