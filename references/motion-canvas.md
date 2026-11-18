# Motion Canvas Reference Guide

Motion Canvas is an open-source (MIT licensed) programmatic animation tool written in **TypeScript**. It is designed specifically for creating **high-craft explainer videos, smooth vector animations, and tech tutorials**.

---

## 1. Project Initialization

### Fast Scaffolding
```bash
npm create @motion-canvas@latest my-animation
cd my-animation
npm install
npm run serve
```

---

## 2. Core Architecture

Motion Canvas relies on **JavaScript Generator Functions (`function*`)** and **Signals**. This makes sequencing and parallel animations readable and intuitive.

### Scene Definition (`src/scenes/example.tsx`)
```tsx
import { makeScene2D, Circle, Txt, all, chain } from '@motion-canvas/2d';
import { createRef, easeInOutCubic, DEFAULT } from '@motion-canvas/core';

export default makeScene2D(function* (view) {
  const circle = createRef<Circle>();
  const label = createRef<Txt>();

  view.add(
    <Circle
      ref={circle}
      width={120}
      height={120}
      fill={'#e74c3c'}
      scale={0}
    >
      <Txt
        ref={label}
        text={'Hello'}
        fill={'#ffffff'}
        fontSize={24}
        opacity={0}
      />
    </Circle>
  );

  // Animate: scale up circle, then fade in label
  yield* circle().scale(1, 1, easeInOutCubic);
  yield* label().opacity(1, 0.5);

  // Wait 1 second
  yield* view.wait(1);

  // Parallel animation: move circle and change color at the same time
  yield* all(
    circle().position.x(200, 1),
    circle().fill('#3498db', 1)
  );
});
```

---

## 3. Key Concepts

### Signals
Properties in Motion Canvas are reactive signals (e.g. `circle().position.x`). You read them by calling them as functions, and animate them by passing target value, duration, and easing.

### Generator Flow Controls
* `yield* all(...)`: Runs multiple animations simultaneously.
* `yield* chain(...)`: Runs animations sequentially.
* `yield* view.wait(seconds)`: Pauses for a specified duration.

---

## 4. CLI & Visual Editor

* Start the visual editor with real-time timeline scrubber, zoom, and visual inspector:
  ```bash
  npm run serve
  ```
* Render the animation directly from the browser UI or CLI to video (WebM/MP4) or image sequences.

---

## 5. 4K Rendering & Resolution Setup

Motion Canvas works on pure resolution-independent vector coordinates, so every scene upgrades cleanly to **4K @ 60fps**:

1. Author shapes, strokes, and paths at standard logical coordinates (`1920×1080` or `1080×1920`).
2. In the Visual Editor **Video Settings** tab (or `meta` resolution config), set **Size** to `1920×1080` and **Scale** to `2` (or directly `3840×2160` / `2160×3840`) with **Frame Rate** `60 fps`.
3. Export as a PNG sequence (or direct MP4 via FFmpeg plugin) and finalize audio mixing/ducking via `scripts/audio_mix.py`.
