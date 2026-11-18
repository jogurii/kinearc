# FFmpeg Reference Guide

FFmpeg provides lightning-fast, headless media transformations directly from the command line. Use it for audio mixing, slicing, transcoding, watermarking, and subtitle burning.

---

## 1. Keyframe & Frame Extraction

```bash
# Extract frames at fixed FPS (e.g. 2 fps)
ffmpeg -i input.mp4 -vf "fps=2,scale=1280:-1" frames/frame_%04d.png

# Extract only scene cuts/changes
ffmpeg -i input.mp4 -vf "select='gt(scene,0.4)',scale=1280:-1" -vsync vfr frames/scene_%03d.png
```

---

## 2. Trimming & Slicing

```bash
# Fast trim without re-encoding (stream copy)
ffmpeg -ss 00:00:05 -to 00:00:15 -i input.mp4 -c copy trimmed.mp4

# Precise trim with re-encoding (frame-accurate)
ffmpeg -ss 00:00:05 -to 00:00:15 -i input.mp4 -c:v libx264 -crf 18 -c:a aac accurate_trimmed.mp4
```

---

## 3. Concatenation & Merging

Create a text file `clips.txt`:
```
file 'clip1.mp4'
file 'clip2.mp4'
file 'clip3.mp4'
```
Run:
```bash
ffmpeg -f concat -safe 0 -i clips.txt -c copy merged.mp4
```

---

## 4. Audio Mixing & Replacement

```bash
# Replace audio entirely
ffmpeg -i video.mp4 -i audio.mp3 -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -shortest output.mp4

# Mix background music (adjust volume to 30%) with original video audio
ffmpeg -i video.mp4 -i bgm.mp3 -filter_complex "[1:a]volume=0.3[a1];[0:a][a1]amix=inputs=2:duration=first" -c:v copy output.mp4
```

---

## 5. Side-by-Side Comparison

```bash
# Stack two videos side by side (useful for MotionClone verification)
ffmpeg -i original.mp4 -i clone.mp4 -filter_complex "[0:v]scale=960:540[v0];[1:v]scale=960:540[v1];[v0][v1]hstack" -c:v libx264 -crf 20 side_by_side.mp4
```
