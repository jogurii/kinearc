# `kinearc` Showcase Examples

Both showcase projects below are 100% deterministic, zero-dependency WebGL2 3D + Radiant Pearl Minimalist / Midnight Portal scenes featuring generous negative space, rack-focus blur reveals, continuous container morphs, planar 3D floor reflections, organic 35mm film grain (`assets/craft/kinearc-gl3d.js`), and breathable crystal/foley sound design (`kinearc_cli.py autocue`).

---

## 1. Responsive 3D Promo — Widescreen `16:9` & Vertical `9:16` (`kinearc-promo-3d/`)
- **Archetype:** *Radiant Pearl Minimalist & Velvet Midnight Portal* (human-first clarity with `responsive: true`).
- **Duration:** `13.0s` (`780` frames @ `60fps`) across `5` breathable scenes (`scenes/01_hook_3d_prism.html` .. `scenes/05_outro_cta.html`).
- **Audio:** `audio/bgm.wav` (`bgm_ambient.wav`) + `26` crystal/harmonic SFX cues in `audio/cues.json` (`harmonic_swell`, `crystal_glint`, `portal_drop`, `bloom_chime`, `ui_tap`, `key_clack`, `warm_riser`, `analog_chord`).

Re-generate breathable tactile SFX cues:
```bash
python -B scripts/kinearc_cli.py autocue --project examples/kinearc-promo-3d/kinearc.project.json --out examples/kinearc-promo-3d/audio/cues.json
```

Preview interactively in the Workbench UI:
```bash
python -B scripts/kinearc_cli.py ui --project examples/kinearc-promo-3d/kinearc.project.json
```

Render to Widescreen (`16:9`) or Vertical Social (`9:16`) MP4:
```bash
# Widescreen 1080p 60fps (for README & Desktop)
python -B scripts/kinearc_cli.py render --project examples/kinearc-promo-3d/kinearc.project.json --out out/kinearc_promo_3d_1080p.mp4 --json-progress

# Widescreen 4K UHD (3840x2160) 60fps
python -B scripts/kinearc_cli.py render --project examples/kinearc-promo-3d/kinearc.project.json --out out/kinearc_promo_3d_4k.mp4 --scale 2 --json-progress

# Vertical 9:16 (1080x1920) 60fps (for Reels / Shorts / TikTok)
python -B scripts/kinearc_cli.py render --project examples/kinearc-promo-3d/kinearc.vertical.project.json --out out/kinearc_promo_vertical_1080p.mp4 --json-progress
```

---

## 2. Human-First 4-Step Walkthrough Tutorial (`kinearc-tutorial/`)
- **Duration:** `18.0s` (`1080` frames @ `60fps`, `1920×1080` widescreen) across `4` clear, non-technical scenes (`01_drop_reference.html` .. `04_export_ready.html`): Drop any video $\rightarrow$ Separate Motion & Sound $\rightarrow$ Live 3D Retheming $\rightarrow$ Before/After Wipe & 4K Export.
- **Audio:** `audio/bgm.wav` (`bgm_ambient.wav`) + `26` crystal & tactile cues in `audio/cues.json`.

Preview interactively in the Workbench UI:
```bash
python -B scripts/kinearc_cli.py ui --project examples/kinearc-tutorial/kinearc.project.json
```

Render to MP4:
```bash
python -B scripts/kinearc_cli.py render --project examples/kinearc-tutorial/kinearc.project.json --out out/kinearc_tutorial_1080p.mp4 --json-progress
```
