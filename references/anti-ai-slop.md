# Anti-AI-Slop Visual & Tactile Audio Craft Directive (`kinearc` v3.0)

AI-generated motion graphics fail when they fall back on programmer-art defaults: sterile indigo/mint neon gradients, synthwave perspective floor grids, repetitive centered cards, unlit 3D polygons, dense unreadable developer dashboards, and dead or noisy synthetic beeps.

Every scene authored with `kinearc` MUST obey this directive so the output looks and sounds indistinguishable from top human motion-design houses (Apple Keynotes, Google Gemini launches, Linear, Stripe, Teenage Engineering).

---

## 1. The Ban List (Zero-Tolerance AI Slop Patterns)

1. **Banned Color Clichés:** Never pair default AI indigo/purple (`#6366f1`, `#6c8cff`) with neon cyan/mint (`#3ad29f`, `#00ffcc`) on dark navy (`#06070c`).
2. **Banned Backdrops:** Never draw retro synthwave vanishing-point floor grids or aimless neon dot clouds on every slide.
3. **Banned Framing Repetition:** Never repeat "Centered Title at Top + 3 Identical Translucent Boxes in the Middle" across consecutive scenes.
4. **Banned Fake Sci-Fi Telemetry:** Never plaster fake HUD corner brackets (`[ ]`) and `SYS // READY // 60 FPS` boilerplate onto every scene.
5. **Banned Silent UI Action:** Never animate a keystroke, button click, slider drag, card snap, or scene transition without a micro-timed tactile sound cue.
6. **NO Crowded Developer Dashboards (Negative Space Law):** Never dump tiny `12px` monospace codec flags, JSON braces, shader uniforms, or 15 badges per slide in promos or general tutorials. Keep **60–75% open Negative Space** with **one clear visual idea and 2–6 readable words per moment** so non-technical humans understand every frame effortlessly.

---

## 2. Four High-Craft Visual Archetypes

Pick **one** deliberate archetype per video using `assets/craft/kinearc-gl3d.js`:

### Archetype A — Radiant Pearl Minimalist & Midnight Portal *(Default for Human-First Consumer / Gemini-Inspired Showcases)*
- **Surface Palette:** Luminous pearl `#f6f7fb` / `#ffffff`, ink charcoal `#18181b`, muted violet-indigo accent `#635bff` / `#7c3aed`, warm rose-gold highlight `#ec4899` / `#f59e0b`, and contrasting Midnight Portal stages (`theme: "midnight"`, `#070611`).
- **Optical VFX:** Rack-focus blur reveals (`drawBlurRevealText`), continuous object morphs (floating 3D emblem $\rightarrow$ pill $\rightarrow$ card), luminous frosted porcelain cards (`drawPearlCard`), 2×2 selection bops (`1.075×`), and expanding radial Light↔Dark wipes (`drawPortalFlash`).
- **Responsive Viewport:** Pass `responsive: true` to `registerScene` so a single authored scene adapts smoothly between `16:9` widescreen (`1920×1080`) and `9:16` vertical (`1080×1920`).

### Archetype B — Obsidian Anodized Hardware
- **Surface Palette:** Deep carbon `#09090b`, machined graphite `#141417`, titanium ivory `#f4f4f5`, warm tungsten amber `#f59e0b`, optical ice `#38bdf8`.
- **Lighting & Depth:** 3-point tungsten/titanium WebGL2 PBR (`keyColor: [1.0, 0.86, 0.68]`) with planar floor reflection (`floorY: -1.35`, `reflectionAlpha: 0.18`).
- **UI & Texture:** `drawCraftBackdrop(ctx, W, H, t, { theme: "obsidian" })`, `drawMachinedPanel` with 1px top specular bevel, and `drawFilmGrain(ctx, W, H, t, 0.038)`.

### Archetype C — Precision Editorial Workshop
- **Surface Palette:** Warm graphite `#0c0c0e`, bone ivory `#fafaf9`, signal vermilion `#f97316`, emerald verification `#10b981`.
- **Choreography:** Asymmetric split-screen views, realistic vector cursor (`drawTactileCursor`) with click depression and shockwave rings, and word-staggered `drawKineticHeadline`.

### Archetype D — Optical Calibration Lab
- **Surface Palette:** Pitch `#050507`, brushed silver `#d4d4d8`, ruby indicator `#ef4444`, warm phosphor `#eab308`.
- **Details:** Precision ruled hairlines measuring live optical-flow vectors and Savitzky-Golay velocity curves.

---

## 3. Compositional Shot-Variety Law

Across a multi-scene `kinearc.project.json`, consecutive scenes MUST alternate scale and physical motion:
1. **Rack-Focus Emblem Reveal:** Floating 3D glass prism + bold 2–3 word blur-to-sharp reveal in open Negative Space.
2. **Spatial Container Morph:** Emblem stretches smoothly into an interactive pill and expands vertically into a clean 3-item card.
3. **Dynamic Feature Bop Grid:** Dynamic cycling headline above a clean 2×2 tactile tile grid (`1.075×` bop + rim highlight).
4. **Light ↔ Dark 3D Portal Transformation:** Velvet midnight backdrop with pulsing 3D WebGL2 sculpture transitioning via radial `drawPortalFlash`.
5. **Stacked Kinetic Statement:** Clean, high-contrast 3-word closer + lockup.

---

## 4. The 3-Layer & Breathable Tactile Audio Law (`kinearc_cli.py autocue`)

Great motion audio needs **breathing room (~35–45% clean open silence or ultra-soft `bgm_ambient.wav`)** so every sound hits cleanly:
- **Layer 1 (Anticipation / Swell):** `swell` (`sfx/harmonic_swell.wav`) or `swish` (`sfx/air_swish_fast.wav`) starting **30–40ms before** peak visual focus or card expansion.
- **Layer 2 (Crystal / Tactile Transient):** Feather-light `glint` (`sfx/crystal_glint.wav`), capacitive `tap` (`sfx/ui_tap.wav`), rotary detent `tick` (`sfx/scrubber_tick.wav`), or magnetic `latch` (`sfx/switch_latch.wav`).
- **Layer 3 (Portal Weight / Resolution):** Deep velvet `portal` (`sfx/portal_drop.wav`) on Light→Dark transitions, radiant `bloom` (`sfx/bloom_chime.wav`) on bright resets, and warm `chord` (`sfx/analog_chord.wav`) on the final lockup.

### Declarative `@cue` Directives & Auto-Cuer CLI
Embed semantic `@cue` comments directly inside your scene's `<script>` block right next to animation timestamps:

```javascript
// @cue 0.85 swell volume=0.78
// @cue 2.20 glint volume=0.74
// @cue 3.55 transition volume=0.80
// @cue 7.65 portal volume=0.85
// @cue 9.25 bloom volume=0.82
```

Then generate `cues.json` automatically across every scene:

```bash
python scripts/kinearc_cli.py autocue --project kinearc.project.json --out audio/cues.json
```

`scripts/audio_mix.py` automatically resolves `sfx/*.wav` from `assets/sfx/`, pre-composites cues in 48kHz stereo NumPy with sample-wise soft-knee limiting (unity gain on quiet transients, zero command-line overflow), and auto-ducks BGM when needed.
