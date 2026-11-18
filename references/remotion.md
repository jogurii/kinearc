# Remotion Reference Guide

Remotion allows developers to build programmatic MP4/WebM videos using **React, TypeScript, Tailwind CSS, and standard web APIs**.

---

## 1. Project Initialization

### Fast Scaffolding
```bash
# Blank template
npx create-video@latest my-video --template=blank

# With Tailwind CSS (Recommended)
npx create-video@latest my-video --template=tailwind
```

### Adding to an Existing Project
```bash
npm install remotion @remotion/cli react react-dom
```

---

## 2. Core Architecture

### Entry Point & Composition (`src/Root.tsx`)
```tsx
import { Composition } from 'remotion';
import { MainScene } from './MainScene';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="MainScene"
      component={MainScene}
      durationInFrames={150} // 5s at 30 FPS
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{
        title: "Default Title",
        brandColor: "#6366f1"
      }}
    />
  );
};
```

---

## 3. Essential Animation Hooks & Helpers

### `useCurrentFrame` & `useVideoConfig`
```tsx
import { useCurrentFrame, useVideoConfig } from 'remotion';

export const AnimatedCard = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  return <div>Frame: {frame}</div>;
};
```

### `interpolate` (Value Mapping)
Maps frame ranges to visual properties (opacity, position, scale):
```tsx
import { interpolate, useCurrentFrame } from 'remotion';

const frame = useCurrentFrame();
const opacity = interpolate(frame, [0, 20], [0, 1], {
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
});
```

### `spring` (Physics-Based Motion)
Provides natural spring bounce:
```tsx
import { spring, useCurrentFrame, useVideoConfig } from 'remotion';

const frame = useCurrentFrame();
const { fps } = useVideoConfig();

const scale = spring({
  frame,
  fps,
  config: {
    damping: 12,
    mass: 0.5,
    stiffness: 120,
  },
});
```

### `<Sequence>` & `<Series>`
* `<Sequence from={30} durationInFrames={60}>`: Starts at frame 30; resets internal `useCurrentFrame()` to 0.
* `<Series>`: Chains clips sequentially without manually computing frame offsets.

---

## 4. CLI Commands

```bash
# Start local interactive Remotion preview
npx remotion preview

# Render composition to MP4
npx remotion render src/index.ts MainScene out.mp4

# Render a single still frame as PNG
npx remotion still src/index.ts MainScene out.png --frame=45
```

---

## 5. 4K Rendering & High-Bitrate Export

Render sharp **4K (3840×2160 Landscape or 2160×3840 Vertical)** without recalculating font sizes or CSS coordinates by authoring at `1080p` logical dimensions (`1920×1080` or `1080×1920`) and scaling at render time:

```bash
# Scale a 1920x1080 or 1080x1920 composition cleanly 2x to native 4K @ 60fps
npx remotion render src/index.ts MainScene out_4k.mp4 --scale=2 --crf=16 --pixel-format=yuv420p

# Hardware WebGL acceleration for 4K 3D (@remotion/three) scenes
npx remotion render src/index.ts Scene3D out_4k_3d.mp4 --scale=2 --gl=angle --crf=16
```

* Alternatively, declare native `width={3840} height={2160}` (or `2160×3840`) directly in `<Composition>` when compositing native 4K camera plates (`<OffthreadVideo>`).
* For high-throughput preview during layout iteration, pass `--scale=0.5` first, then export `--scale=2` for final delivery.
