# Ad Craft, Promos & Explainers Playbook

Use this guide whenever building **original marketing videos from scratch**—product ads, launch promos, SaaS explainers, feature announcements, or vertical reels—instead of cloning an existing reference clip.

---

## 1. Pre-Production Creative Spec

Before writing a single animation line, establish 5 concrete parameters (infer defaults if omitted, or confirm ambiguous branding details):
1. **Format & Narrative Archetype:** Product Ad (15–30s), Hype Promo (10–20s), Explainer / Demo (30–90s), or Social Reel/Short (15–45s).
2. **Canvas Resolution & FPS:** Match the target platform (up to **4K / 60fps** — see Section 2).
3. **Narrative Beat Sheet:** Scene-by-scene table with exact timestamps, visual subjects, on-screen copy (<= 9 words per beat), SFX cues, and transitions.
4. **Visual Direction:** 1 background color, 1 surface color, 1 primary accent, 1 high-contrast ink color, and 1–2 font families (`Display` + `Body/Mono`). Never scatter 6 unrelated neon gradients on black.
5. **Audio Plan:** BGM mood/BPM, optional voiceover timing, and SFX cues (`cues.json`) for `scripts/audio_mix.py`.

---

## 2. Platform Aspect Ratios & UI Safe Zones

| Platform / Use Case | Logical Base | Native 4K / `--scale=2` | FPS | Notes |
| :--- | :--- | :--- | :--- | :--- |
| YouTube, Hero Embed, Demo | `1920×1080` (`16:9`) | `3840×2160` | 30 / 60 | Keep margins `>= 96px` on all edges (1080p base). |
| TikTok, Reels, Shorts | `1080×1920` (`9:16`) | `2160×3840` | 60 | **Strict UI Safe Zone below!** |
| Instagram / LinkedIn Feed | `1080×1080` (`1:1`) | `2160×2160` | 30 / 60 | Center hero card; avoid tiny footer disclaimers. |
| Mobile Feed Portrait | `1080×1350` (`4:5`) | `2160×2700` | 30 / 60 | High screen occupancy on mobile feeds. |

### Mandatory `9:16` Vertical Safe Zone (`1080×1920` Base Coordinates)
Short-form apps cover edges with search bars, profile pills, action icons, and captions. Never place essential text or buttons outside the safe core:
* **Top clearance:** `>= 220px` (status bar, following/search header).
* **Bottom clearance:** `>= 360px` (caption block, audio ticker, sponsored CTA pill).
* **Right clearance:** `>= 150px` (like, comment, bookmark, share stack).
* **Left clearance:** `>= 72px`.
* **Safe Core Box:** `x: [72 .. 930]`, `y: [220 .. 1560]` (`858×1340` safe region).

---

## 3. Proven Narrative Arc Templates

### A. Product Ad / Conversion Spot (15s – 30s)
1. **Beat 1 — Hook (0.0s – 2.5s):** Immediate pattern interrupt. Bold headline (`<= 6` words) or snappy macro UI action on frame 1—never fade in from blank black for 1 full second.
2. **Beat 2 — Friction / Problem (2.5s – 6.0s):** Visually contrast the old slow workflow (cluttered cards, red error/delay counter, stalled spinner).
3. **Beat 3 — Hero Solution & UI Demo (6.0s – 18.0s):** Snap transition into clean branded UI/product mockup. Spotlight max 2–3 core features with animated cursor taps, zoomed callouts, or real screen recording (`<OffthreadVideo>`).
4. **Beat 4 — Proof & Velocity (18.0s – 24.0s):** Animated KPI counters (`tabular-nums`), trust badges, or customer quote card.
5. **Beat 5 — CTA & Brand Lockup (24.0s – 30.0s):** High-contrast product logo, clean URL/action pill, and subtle micro-glow hold for `>= 2.0s`.

### B. Launch Hype / Social Promo (10s – 20s)
* Structure as **8–12 tight musical beats** (`0.9s – 1.8s` each) aligned to audio hits in `cues.json`.
* Alternate rhythm intentionally: **Fast kinetic word pop** (`0.8s`) -> **Clean full-bleed product card** (`1.8s`) -> **Macro UI detail** (`1.2s`) -> **Stinger logo outro** (`2.5s`).
* Keep copy punchy (`2–5` words per beat) at huge typographic scale (`72px–140px` at 1080p base).

### C. SaaS / Technical Explainer (30s – 90s)
1. **Context Hook (0–4s):** Clear question or one-sentence promise.
2. **Mental Model / Architecture (4–16s):** Clean nodes, connectors, and flow arrows (use **Motion Canvas** or **Remotion** SVG paths with animated `strokeDashoffset`).
3. **3-Step Guided Walkthrough (16–60s):** One concept per scene (`Step 1 -> Step 2 -> Step 3`) synced to `audio_mix.py` voiceover timestamps; highlight active card while dimming inactive siblings (`opacity: 0.35`).
4. **Summary & Next Step (60–75s+):** Crisp checklist recap + CTA.

---

## 4. Visual Craft & Motion Quality Standards

1. **Zero Dead Frames:** Even during reading holds (`0.8s–2.0s`), maintain subtle life: background gradient drift (`±20px`), gentle container push-in (`scale: 1.00 -> 1.03`), or floating soft shadows.
2. **Hierarchy & Contrast:** One primary focal element per beat. Headings >= 2× body scale; maintain >= `4.5:1` contrast between text and card fill; apply `fontVariantNumeric: 'tabular-nums'` on every live counter, clock, or price.
3. **Match Cuts Over Generic Fades:** Link consecutive scenes through shared geometry—morphing a button into the next scene's card container, sliding a hero mockup across frame boundaries (`translateX` + velocity blur), or zooming cleanly into a sub-panel.
4. **Overshoot Discipline:** Use `spring({ damping: 14–18, mass: 0.6–0.9, stiffness: 140–220 })` or `cubic-bezier(0.16, 1, 0.3, 1)` for snappy settles. Avoid sloppy infinite oscillation on UI text.
5. **Readability Buffer:** Every line of on-screen copy should hold legible at peak opacity for at least `max(1.2s, wordCount * 0.28s)`.

---

## 5. Audio Sync & Pre-Render Verification Gate

1. Generate your SFX cues JSON (`cues.json`) directly from your code's scene start timestamps (`sceneStartFrame / fps`) so every transition whoosh and CTA hit lands on the exact frame.
2. **Pre-Render Still Audit (Mandatory for Ads/Promos):** Before exporting a heavy 1080p/4K video, render 4 representative stills (Hook frame, Mid-demo frame, Proof frame, CTA frame) using `scripts/kinearc_cli.py stills` (`engine/render.mjs`, `references/kinearc-engine.md`), `npx remotion still`, or `Render Still` inside `scripts/kinearc_ui.py` (`POST /api/render`), verify safe zones (`9:16` / `16:9` / `1:1`) and typography overlap visually in `kinearc_ui.py`, fix layout flaws, and then execute final 4K render (`kinearc_cli.py render --scale 2` or one-click `Export 4K 60fps` -> `Open in Stage / Diff` via `/api/render/load`) + `scripts/audio_mix.py mix`.
