# `kinearc` Showcase Examples

Both showcase projects below are 100% deterministic, zero-dependency WebGL2 3D + Glassmorphic 2D Canvas examples rendered at **1920×1080 @ 60fps** (scalable to **4K 3840×2160** with `--scale 2`) with synthesized stereo music and beat-synced SFX cues.

---

## 1. Professional 3D Promo (`kinearc-promo-3d/`)
- **Duration:** `18.0s` (`1080` frames @ `60fps`) across `6` WebGL2 PBR + HUD scenes (`scenes/01_hook_3d_prism.html` .. `scenes/06_outro_cta.html`).
- **Audio:** `audio/bgm.wav` + `11` timestamped SFX cues in `audio/cues.json`.

Preview interactively in the Workbench UI:
```bash
python -B scripts/kinearc_cli.py ui --project examples/kinearc-promo-3d/kinearc.project.json
```

Render to 1080p or 4K MP4:
```bash
# 1080p 60fps
python -B scripts/kinearc_cli.py render --project examples/kinearc-promo-3d/kinearc.project.json --out out/kinearc-promo-3d-1080p.mp4 --json-progress

# 4K UHD (3840x2160) 60fps
python -B scripts/kinearc_cli.py render --project examples/kinearc-promo-3d/kinearc.project.json --out out/kinearc-promo-3d-4k.mp4 --scale 2 --json-progress
```

---

## 2. Interactive Walkthrough Tutorial (`kinearc-tutorial/`)
- **Duration:** `30.0s` (`1800` frames @ `60fps`) across `5` step-by-step scenes covering `extract`, deterministic `seek(t)`, the 60fps Workbench UI (`Split`, `4× Diff`, `[ In / Out ]`, right-click erase, `Copy AI Prompt`), and one-click 4K export + `install.py`.
- **Audio:** `audio/bgm.wav` + `11` timestamped SFX cues in `audio/cues.json`.

Preview interactively in the Workbench UI:
```bash
python -B scripts/kinearc_cli.py ui --project examples/kinearc-tutorial/kinearc.project.json
```

Render to MP4:
```bash
python -B scripts/kinearc_cli.py render --project examples/kinearc-tutorial/kinearc.project.json --out out/kinearc-tutorial-1080p.mp4 --json-progress
```
