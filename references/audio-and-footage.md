# Audio Mixing, Auto-Ducking, Pause Cutting & Real Footage Guide

This guide covers post-production audio engineering (`scripts/audio_mix.py`) and embedding real screen recordings, camera footage, or talking-head clips inside programmatic `kinearc` compositions.

> Requires `ffmpeg` and `ffprobe` on `PATH`. Zero extra Python packages required.

---

## 1. Automated Mixing, Auto-Ducking & SFX Sync (`scripts/audio_mix.py mix`)

Instead of manually balancing volume automation curves in a GUI editor, render your clean programmatic visuals first and run `audio_mix.py mix` to copy the video stream **losslessly (`-c:v copy`)** while producing a broadcast-ready `320kbps` AAC stereo mix.

### Capabilities
* **Auto-Looping & Fade-Out BGM:** Automatically loops background music if shorter than `--video`, trims cleanly to exact video length, and applies a smooth `--fade_out`.
* **Automatic Sidechain Ducking:** Whenever `--voice` audio is present, `sidechaincompress` automatically lowers `--bgm` during speech and swells it cleanly back up during pauses/CTA endings.
* **Frame-Accurate SFX Placement (`--sfx cues.json`):** Places timestamped sound effects (`whoosh`, `pop`, `click`, `impact`) at exact second offsets via `adelay` without distorting peaks (`alimiter=limit=0.95`).
* **Duration Lock:** Pads trailing silence cleanly so shorter voiceovers or SFX tracks never truncate your final MP4 video length.

### SFX Cues Schema (`cues.json`) & Scene Matching
```json
[
  { "file": "sfx/sub_impact.wav", "time": 0.00, "volume": 0.90, "pan": 0.0, "room": 0.16, "tilt_db": -2.2, "cutoff_hz": 7800.0, "sub_boost": 1.24 },
  { "file": "sfx/air_swish_fast.wav", "time": 2.45, "volume": 0.75, "pan": -0.35, "room": 0.05, "tilt_db": 1.8, "cutoff_hz": 17200.0 },
  { "file": "sfx/ui_tap_02.wav", "time": 6.10, "volume": 0.85, "pitch": 1.02 }
]
```
*(Tip: `python scripts/kinearc_cli.py autocue` automatically analyzes each scene HTML's material `crystal`/`paper-wood`/`metal`/`deep-space`, luminance, and color temperature — or reads `// @scene-audio material=... temp=... space=...` — to populate per-cue `room`, `tilt_db`, `cutoff_hz`, and `sub_boost`.)*

### Reference Audio Extractor & SFX Pack Remaker (`extract-audio`)
Extract the spectral DNA, dynamic silence ratio, isolated onset stems, and a custom copyright-clean remade SFX pack from any reference video or audio file:
```bash
python "<skill_dir>/scripts/kinearc_cli.py" extract-audio --input reference.mp4 --out_dir .kinearc_analysis/audio
# Optional: switch bundled SFX pack style directly (airy-clean, tactile-wood, crisp-glass, cinematic-sub)
python "<skill_dir>/scripts/kinearc_cli.py" sfx-pack --style airy-clean
```

### Command Usage
```bash
# Full mix: Rendered MP4 + Voiceover + Auto-Ducked BGM + SFX cues
python "<skill_dir>/scripts/audio_mix.py" mix \
  --video render_4k.mp4 \
  --voice voiceover.wav \
  --bgm soundtrack.mp3 \
  --sfx cues.json \
  --out final_master_4k.mp4 \
  --voice_vol 1.0 --bgm_vol 0.35 --fade_out 1.5

# Mix keeping original audio already inside --video (e.g. screen demo audio)
python "<skill_dir>/scripts/audio_mix.py" mix \
  --video render_with_ui_audio.mp4 --bgm soundtrack.mp3 --keep_video_audio --video_vol 0.9 --out final.mp4
```

| Flag | Default | Purpose |
| :--- | :--- | :--- |
| `--video` | optional | Input video MP4 (stream-copied losslessly without re-encoding pixels). |
| `--voice` | optional | Narration / voiceover track; triggers BGM sidechain ducking when paired with `--bgm`. |
| `--bgm` | optional | Background music track (auto-looped to video length). |
| `--sfx` | optional | Path to `cues.json` (`[{"file", "time", "volume"}]`). |
| `--out` | required | Output `.mp4` (or `.wav`/`.m4a`/`.aac` if no `--video`). |
| `--voice_vol`, `--bgm_vol`, `--video_vol` | `1.0`, `0.35`, `1.0` | Linear gain multipliers per bus. |
| `--fade_out` | `1.5` | Seconds of smooth BGM fade-out at video end. |
| `--keep_video_audio` | `false` | Preserve and mix original audio track from `--video`. |

---

## 2. Dead-Air & Pause Cutting (`scripts/audio_mix.py cut-pauses`)

Clean up hesitant pauses in recorded voiceovers or talking-head footage **before** animating visuals or captions around them:

```bash
# 1. Detect silences quieter than -32 dB lasting >= 0.45s, save JSON + trimmed clip
python "<skill_dir>/scripts/audio_mix.py" cut-pauses \
  --input raw_recording.mp4 \
  --out tight_recording.mp4 \
  --cuts_json cuts.json \
  --threshold -32 --min_silence 0.45 --pad 0.08
```

* Writes `cuts.json` with `original_duration` and `keep_segments: [{"start": ..., "end": ...}, ...]`.
* Works on both audio-only files (`.wav`, `.mp3`, `.m4a`) and `.mp4` video+audio clips (using trim+concat).
* Use `tight_recording.mp4` duration & timestamps directly to schedule Remotion `<Sequence>` beats and kinetic captions!

### Interactive Waveform & Audio Controls (`kinearc_ui.py` — `Audio & Out` Tab)
When launching `scripts/kinearc_ui.py` with `--voice`, `--bgm`, `--sfx`, and/or a video render (`clone.mp4`), the timeline automatically renders real audio waveform peaks alongside clickable `--sfx` (`cues.json`) markers, and the **`Audio & Out`** drawer tab exposes live controls:
* **`Trim Pauses (cut-pauses)`:** Runs `audio_mix.cmd_cut_pauses` (`-32 dB`, `0.45s` min silence, `0.08s` pad), saving `<stem>_tight*` + `*_cuts.json` into `.kinearc_analysis/renders/` and refreshing the active voice waveform.
* **`Auto-Duck Mix (audio_mix)`:** Mixes configured tracks with live `Voice Volume`, `BGM Duck Volume`, `Video Audio Volume`, `Include original video audio`, and `BGM Fade-out (s)` controls, outputting the finished media into `.kinearc_analysis/renders/`.

---

## 3. Compositing Screen Recordings & Footage Inside Motion Graphics

SaaS promos and explainers feel 10× more authentic when **real product UI recordings** sit inside stylized animated device bezels with smooth camera zooms.

### Remotion: Always Use `<OffthreadVideo>` for Renders
Never use HTML `<video>` for headless Remotion renders (`<video>` drops frames under seek pressure). Use `<OffthreadVideo>` from `'remotion'`:

```tsx
import { OffthreadVideo, staticFile, interpolate, useCurrentFrame } from 'remotion';

export const ScreenMockupScene: React.FC = () => {
  const frame = useCurrentFrame();
  // Smooth focus zoom into top-right feature panel between frame 40 and 85
  const zoom = interpolate(frame, [40, 85], [1, 1.38], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const panX = interpolate(frame, [40, 85], [0, -180], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  return (
    <div style={{
      width: 1440, height: 860, borderRadius: 24, overflow: 'hidden',
      boxShadow: '0 40px 100px rgba(0,0,0,0.45)', border: '2px solid rgba(255,255,255,0.14)',
    }}>
      <div style={{ transform: `scale(${zoom}) translateX(${panX}px)`, transformOrigin: 'center center', width: '100%', height: '100%' }}>
        <OffthreadVideo
          src={staticFile('demo_recording.mp4')}
          startFrom={60}
          playbackRate={1.25}
          muted
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </div>
    </div>
  );
};
```

### Best Practices for Screen Recordings & Footage
1. **Normalize FPS before compositing:** If mixing a variable-framerate (`VFR`) phone/OBS recording into a 60fps project, transcode to constant 60fps first via FFmpeg:
   `ffmpeg -i obs_raw.mp4 -vf "fps=60" -c:v libx264 -crf 16 -pix_fmt yuv420p demo_cfr60.mp4`
2. **Loudness Normalization for Raw Mic Audio:** Apply EBU R128 loudness normalization before final mix so voiceovers sit consistently around `-14 LUFS`:
   `ffmpeg -i vo_raw.wav -af loudnorm=I=-14:TP=-1.5:LRA=7 vo_norm.wav`
3. **Device Frames & Depth:** Pair `<OffthreadVideo>` with subtle macOS window chrome or phone mockup bezels, `perspective(1200px) rotateY(...)` entrances, and floating highlight cursor/callouts synced to video timestamps.
