# Interactive Web & Scroll-Driven Motion Reference Guide

Use this guide when the target output is **live interactive web UI** (scroll-driven storytelling, hero product reveals, interactive DOM/SVG/Canvas motion, or paired web + MP4 deliverables) rather than a standalone MP4 only.

---

## 1. Choosing Between GSAP `ScrollTrigger` and Native Web Animations API

| Need | Recommended API | Why |
| :--- | :--- | :--- |
| Complex multi-element choreography, scrubbed timelines, pinned sections | **GSAP + `ScrollTrigger`** | Mature timeline nesting (`gsap.timeline()`), `scrub`, `pin`, and `gsap.matchMedia()`. |
| Zero-dependency browser animations or lightweight CSS/JS scroll linking | **Web Animations API (`Element.animate()` / `ScrollTimeline`)** | Native browser compositor performance with zero bundle overhead. |
| Pixel-level `<canvas>` / WebGL frame-accurate scenes | **Canvas / Three.js + `window.kinearc.seek(t)`** | Deterministic frame-stepping (`?t=`, `?scale=2`) exported directly to 4K MP4 via `kinearc_cli.py` + `engine/render.mjs` (`references/kinearc-engine.md`). |

---

## 2. Deterministic Verification Contract (`window.kinearc.seek(t)`)

Every interactive web or `<canvas>` scene built with `kinearc` should expose a **pure deterministic time hook** so visual audits, `kinearc_ui.py` live scene preview / `/api/render`, and native HTML/Canvas WebCodecs exports (`scripts/kinearc_cli.py` + `engine/render.mjs`) render any timestamp `t` (in seconds) identically without relying on wall-clock timers:

1. **`window.kinearc = { total, ready, seek }`:**
   * `total` (`number`): total timeline duration in seconds (alias `window.TOTAL`).
   * `ready` (`Promise<void>`): resolves once web fonts, images, and initial layout are settled (alias `window.ready`).
   * `seek(t)` (`(t: number) => void`): moves all timelines/transforms/canvas draws deterministically to `t` seconds (alias `window.renderAt(t)` for `<canvas>` scenes).
2. **URL Query Parameters:**
   * `?t=<seconds>`: immediately seeks to timestamp `t` on page load for still-frame audits (`?t=1.25`).
   * `?scale=2`: scales logical `1920×1080` (`16:9`) or `1080×1920` (`9:16`) `<canvas>` backing buffers to crisp **4K (`3840×2160` / `2160×3840`)** without changing logical coordinates.

### Minimal Deterministic HTML/Canvas Template
```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><title>kinearc Interactive Scene</title></head>
<body style="margin:0;overflow:hidden;background:#09090b;">
<canvas id="c"></canvas>
<script>
const q = new URLSearchParams(location.search);
const rawScale = parseFloat(q.get('scale') || '');
const S = Number.isFinite(rawScale) && rawScale > 0 ? rawScale : 1;
const W = 1920, H = 1080;
const canvas = document.getElementById('c');
canvas.width = W * S;
canvas.height = H * S;
canvas.style.width = '100vw';
canvas.style.height = '100vh';
const ctx = canvas.getContext('2d');

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const easeOutExpo = (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * clamp(x)));
const prog = (t, a, b) => clamp((t - a) / (b - a));

const TOTAL = 3.0;
const seek = (t) => {
  ctx.setTransform(S, 0, 0, S, 0, 0);
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#09090b';
  ctx.fillRect(0, 0, W, H);

  const p = easeOutExpo(prog(t, 0.2, 1.1));
  ctx.globalAlpha = p;
  ctx.fillStyle = '#f8fafc';
  ctx.font = '700 84px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('kinearc Motion', W / 2, H / 2 + (1 - p) * 48);
};

const rawT = parseFloat(q.get('t') || '');
const initialT = Number.isFinite(rawT) && rawT > 0 ? rawT : 0;
const ready = document.fonts.ready.then(() => seek(initialT));
window.TOTAL = TOTAL;
window.renderAt = seek;
window.ready = ready;
window.kinearc = { total: TOTAL, ready, seek };
</script>
</body>
</html>
```

---

## 3. GSAP `ScrollTrigger` Timeline Mapping

Build a **paused** master GSAP timeline so it can be scrubbed by scroll in production **and** seeked deterministically during visual verification (`window.kinearc.seek(t)`):

```ts
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

const TOTAL_SEC = 4.0;
const params = new URLSearchParams(location.search);
const isAuditMode = params.has('t');

let activeSeek = (_t: number) => {};

const mm = gsap.matchMedia();

mm.add(
  {
    allowMotion: '(prefers-reduced-motion: no-preference)',
    reduceMotion: '(prefers-reduced-motion: reduce)',
  },
  (context) => {
    const { reduceMotion } = context.conditions!;

    // Instantiate timeline inside matchMedia so re-evaluations never append duplicate tweens
    const tl = gsap.timeline({
      paused: true,
      defaults: { ease: 'power4.out' }, // Calibrated deceleration (comparable to Easing.bezier(0.16, 1, 0.3, 1))
    });

    if (reduceMotion) {
      // Settled final-state layout with <= 150ms opacity fade only; seek(t) remains deterministic
      gsap.set(['.hero-card', '.hero-pill'], { clearProps: 'transform' });
      tl.fromTo('.hero-card', { opacity: 0 }, { opacity: 1, duration: 0.15 }, 0);
      activeSeek = (t: number) => {
        tl.seek(Math.max(0, Math.min(TOTAL_SEC, t)), false);
      };
      tl.progress(1);
      return;
    }

    tl.fromTo('.hero-card', { y: 56, opacity: 0, scale: 0.96 }, { y: 0, opacity: 1, scale: 1, duration: 0.65 }, 0.0)
      // Compositor-only transform: use scaleX instead of layout property `width`
      .fromTo('.hero-pill', { scaleX: 0.35, transformOrigin: 'left center' }, { scaleX: 1, duration: 0.55 }, 0.50)
      // Respect HOLD_PLATEAU: keep card stationary during reading window 1.05s -> 2.15s
      .to({}, { duration: 1.10 }, 1.05)
      .to('.hero-card', { scale: 1.074, duration: 0.28 }, 2.15) // Measured card_bop_summary ratio
      .to('.hero-card', { y: -32, opacity: 0, duration: 0.45 }, 3.20);

    const trigger = isAuditMode
      ? null
      : ScrollTrigger.create({
          trigger: '.scroll-stage',
          start: 'top top',
          end: '+=2400',
          scrub: 0.6,
          pin: true,
          animation: tl,
        });

    activeSeek = (t: number) => {
      trigger?.disable(false);
      tl.seek(Math.max(0, Math.min(TOTAL_SEC, t)), false);
    };

    return () => {
      trigger?.kill();
    };
  }
);

const rawT = parseFloat(params.get('t') || '');
const initialT = Number.isFinite(rawT) && rawT > 0 ? rawT : 0;
const seek = (t: number) => activeSeek(t);
const ready = document.fonts.ready.then(() => {
  if (isAuditMode) seek(initialT);
});

// Exposed unconditionally across both motion and prefers-reduced-motion states
(window as any).kinearc = { total: TOTAL_SEC, ready, seek };
```

### GSAP Craft Rules
* **Compositor Properties Only:** Animate `x`, `y`, `scale`, `scaleX`/`scaleY`, `rotation`, and `opacity` rather than `width`/`height`/`top`/`left`/`margin` to avoid layout thrashing at 60/120 Hz.
* **Preserve Hold Plateaus:** Insert explicit flat hold intervals matching `CONTAINER_PHASES` (`HOLD_PLATEAU`) so resting UI elements never drift under linear scrub interpolation.
* **Respect `?t=` Audit Mode:** When `new URLSearchParams(location.search).has('t')`, guard `?t=` with `Number.isFinite(rawT) && rawT > 0 ? rawT : 0` and call `window.kinearc.seek(initialT)` after `document.fonts.ready` without starting autoplay loops.

---

## 4. Native Web Animations API (`Element.animate()` & `ScrollTimeline`)

When shipping zero-dependency DOM animations, pair `Element.animate()` with calibrated `cubic-bezier(...)` curves and attach either a `ScrollTimeline` for live scrolling or paused `currentTime` seeking for verification:

```ts
const card = document.querySelector<HTMLElement>('.hero-card')!;
const params = new URLSearchParams(location.search);
const isAuditMode = params.has('t');
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const keyframes: Keyframe[] = reduceMotion
  ? [
      { transform: 'none', opacity: 0, offset: 0, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' },
      { transform: 'none', opacity: 1, offset: 1 },
    ]
  : [
      { transform: 'translate3d(0, 48px, 0) scale(0.95)', opacity: 0, offset: 0, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' },
      { transform: 'translate3d(0, 0, 0) scale(1)', opacity: 1, offset: 0.35 },
      // Stationary HOLD_PLATEAU from 35% to 75% progress
      { transform: 'translate3d(0, 0, 0) scale(1)', opacity: 1, offset: 0.75, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' },
      { transform: 'translate3d(0, 0, 0) scale(1.074)', opacity: 1, offset: 1 },
    ];

const DURATION_MS = reduceMotion ? 150 : 2400;

let scrollAnim: Animation | null = null;
const anim = card.animate(keyframes, {
  duration: DURATION_MS,
  easing: 'linear',
  fill: 'both',
});
anim.pause();

// Attach ScrollTimeline only for live interactive browsing (skip in ?t= audit mode)
if (!isAuditMode && !reduceMotion) {
  if ('ScrollTimeline' in window) {
    const timeline = new (window as any).ScrollTimeline({
      source: document.documentElement,
      axis: 'block',
    });
    scrollAnim = card.animate(keyframes, { timeline, easing: 'linear', fill: 'both' });
  } else {
    anim.play();
  }
}

const seek = (t: number) => {
  // Cancel any live scroll-linked animation so deterministic seek(t) is never masked
  if (scrollAnim) {
    scrollAnim.cancel();
    scrollAnim = null;
  }
  anim.pause();
  anim.currentTime = Math.max(0, Math.min(DURATION_MS, t * 1000));
};

const rawT = parseFloat(params.get('t') || '');
const initialT = Number.isFinite(rawT) && rawT > 0 ? rawT : 0;
const ready = document.fonts.ready.then(() => {
  if (isAuditMode) {
    seek(initialT);
  } else if (reduceMotion) {
    seek(DURATION_MS / 1000);
  }
});

(window as any).kinearc = { total: DURATION_MS / 1000, ready, seek };
```

---

## 5. Integrating `motionTracks.ts` & Calibrated Curves

After running `scripts/track_objects.py` and `scripts/measure_shapes_colors.py`, import `.kinearc_analysis/motionTracks.ts` directly into your web bundle so interactive DOM/Canvas elements replay the exact measured Catmull-Rom trajectories and `bop_scale_ratio` physics:

```ts
import {
  SOURCE_FPS,
  ICON_CX,
  ICON_CY,
  ICON_SIZE,
  ICON_ANGLE_DEG,
  sampleLUT,
} from '../.kinearc_analysis/motionTracks';

export function applyTrackedMotion(el: HTMLElement, timeSec: number, scaleX = 1, scaleY = 1) {
  const srcFrame = timeSec * SOURCE_FPS;
  const cx = sampleLUT(ICON_CX, srcFrame, SOURCE_FPS) * scaleX;
  const cy = sampleLUT(ICON_CY, srcFrame, SOURCE_FPS) * scaleY;
  const angle = sampleLUT(ICON_ANGLE_DEG, srcFrame, SOURCE_FPS);
  const baseSize = Math.max(1, ICON_SIZE[0] || 1);
  const scale = sampleLUT(ICON_SIZE, srcFrame, SOURCE_FPS) / baseSize;

  el.style.transform = `translate3d(${cx.toFixed(2)}px, ${cy.toFixed(2)}px, 0) rotate(${angle.toFixed(2)}deg) scale(${scale.toFixed(4)})`;
}
```

* When pairing interactive DOM scenes with Remotion MP4 exports, share a single `easings.ts` module (`cubic-bezier(0.16, 1, 0.3, 1)`, spring overshoot values, and `card_bop_summary.bop_scale_ratio`) so web and video builds stay visually unified.

---

## 6. Accessibility Safeguard (`prefers-reduced-motion`)

Always honor user motion preferences in both CSS and JS:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
  }
}
```

```ts
export const prefersReducedMotion = (): boolean =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;
```

* **If `prefersReducedMotion()` is `true`:** Skip parallax scrubs, bounce overshoots, and particle orbits; render the settled final-state layout immediately (or apply a gentle `<= 150ms` opacity fade only) while keeping `window.kinearc.seek(t)` functional for automated frame audits.
