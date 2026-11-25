#!/usr/bin/env python3
"""
audio_mix.py — Automated Audio Mixing (Voiceover + Auto-Ducking BGM + Beat-Synced SFX) & Pause Cutter
Part of the kinearc skill toolkit.

Requires: ffmpeg & ffprobe on PATH.

Subcommands:
1. mix: Mixes video + optional voiceover + optional BGM (with automatic sidechain ducking under voice)
        + optional timestamped SFX cues JSON -> finished MP4 or WAV/AAC.
   Example:
     python audio_mix.py mix --video render.mp4 --bgm music.mp3 --voice vo.wav --sfx cues.json --out final.mp4

2. cut-pauses: Uses ffmpeg silencedetect to find dead pauses in a voiceover or talking-head clip,
               writes cuts.json, and optionally exports a tight pause-free clip.
   Example:
     python audio_mix.py cut-pauses --input talking.mp4 --out tight.mp4 --threshold -32 --min_silence 0.45
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from typing import Any
import wave
import zlib

import numpy as np

MIX_SAMPLE_RATE = 48000
# Harmonic / sustained tonal stems stay pitch-locked so chords never clash musically;
# percussive / noise-driven stems accept subtle human pitch micro-variation.
PITCH_LOCKED_TOKENS = ("chord", "swell", "bloom", "ping", "riser", "sub_impact", "portal", "bgm")


def get_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.check_output(cmd, text=True, encoding="utf-8").strip()
    return float(out) if out else 0.0


def has_audio_stream(path: str) -> bool:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        path,
    ]
    out = subprocess.check_output(cmd, text=True, encoding="utf-8").strip()
    return len(out) > 0


def _decode_audio_48k_stereo(path: str) -> np.ndarray:
    """Decode any audio file once into float32 stereo (N, 2) at 48 kHz."""
    if path.lower().endswith(".wav"):
        try:
            with wave.open(path, "rb") as wf:
                ch = wf.getnchannels()
                sw = wf.getsampwidth()
                sr = wf.getframerate()
                nframes = wf.getnframes()
                if sw in (1, 2, 4) and sr > 0 and nframes > 0:
                    raw = wf.readframes(nframes)
                    if sw == 1:
                        arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
                    elif sw == 2:
                        arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                    else:
                        arr = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
                    arr = arr.reshape(-1, ch)
                    if ch == 1:
                        stereo = np.repeat(arr, 2, axis=1)
                    else:
                        stereo = arr[:, :2]
                    if sr != MIX_SAMPLE_RATE:
                        new_len = max(1, int(round(len(stereo) * MIX_SAMPLE_RATE / sr)))
                        old_idx = np.linspace(0.0, len(stereo) - 1, new_len, dtype=np.float64)
                        l_res = np.interp(old_idx, np.arange(len(stereo)), stereo[:, 0]).astype(np.float32)
                        r_res = np.interp(old_idx, np.arange(len(stereo)), stereo[:, 1]).astype(np.float32)
                        stereo = np.column_stack((l_res, r_res))
                    return stereo
        except wave.Error:
            pass

    proc = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", path,
            "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-ar", str(MIX_SAMPLE_RATE),
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    arr = np.frombuffer(proc.stdout, dtype="<f4")
    if arr.size == 0:
        return np.zeros((0, 2), dtype=np.float32)
    return arr.reshape(-1, 2)


def _resample_ratio_stereo(clip: np.ndarray, ratio: float) -> np.ndarray:
    """Smooth linear pitch/speed resample for subtle foley variation."""
    if len(clip) < 4 or abs(ratio - 1.0) < 1e-4:
        return clip
    new_len = max(4, int(round(len(clip) / ratio)))
    idx = np.linspace(0.0, len(clip) - 1, new_len, dtype=np.float64)
    l_res = np.interp(idx, np.arange(len(clip)), clip[:, 0]).astype(np.float32)
    r_res = np.interp(idx, np.arange(len(clip)), clip[:, 1]).astype(np.float32)
    return np.column_stack((l_res, r_res))


def _generate_acoustic_room_ir(sample_rate: int = MIX_SAMPLE_RATE, duration: float = 0.20) -> np.ndarray:
    """Create a tight, warm wood-booth stereo room IR (early reflections + soft velvet tail)."""
    n = max(128, int(round(duration * sample_rate)))
    rng = np.random.default_rng(7719)
    ir = np.zeros((n, 2), dtype=np.float64)

    # Asymmetric booth early reflections (ms, L_gain, R_gain)
    taps = [
        (0.0045, 0.24, 0.14),
        (0.0072, 0.12, 0.23),
        (0.0118, 0.17, 0.11),
        (0.0165, 0.09, 0.16),
        (0.0230, 0.13, 0.08),
        (0.0315, 0.07, 0.11),
        (0.0420, 0.08, 0.06),
    ]
    for d_sec, lg, rg in taps:
        pos = int(round(d_sec * sample_rate))
        if pos < n:
            ir[pos, 0] += lg
            ir[pos, 1] += rg

    # Decorrelated late diffuse tail starting around 18 ms
    tail_start = int(0.018 * sample_rate)
    t_tail = np.arange(max(0, n - tail_start), dtype=np.float64) / sample_rate
    decay = np.exp(-t_tail / 0.048) * 0.085
    for ch in range(2):
        velvet = rng.choice([-1.0, 0.0, 0.0, 0.0, 1.0], size=len(t_tail))
        ir[tail_start:, ch] += velvet * decay

    # Gentle high-frequency room absorption (~4.8 kHz low-pass tilt in frequency domain)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    air_damp = 1.0 / (1.0 + (freqs / 4800.0) ** 2)
    ir[:, 0] = np.fft.irfft(np.fft.rfft(ir[:, 0]) * air_damp, n=n)
    ir[:, 1] = np.fft.irfft(np.fft.rfft(ir[:, 1]) * air_damp, n=n)
    return ir.astype(np.float32)


def _apply_stereo_pan(clip: np.ndarray, pan: float) -> np.ndarray:
    """Peak-preserving Haas + attenuation stereo placement (pan in [-1.0, +1.0])."""
    p = max(-1.0, min(1.0, float(pan)))
    if abs(p) < 1e-3 or len(clip) == 0:
        return clip
    # Dominant channel stays at 1.0 so quiet-cue peak parity holds; far ear gently attenuates + 0.35ms ITD
    delay_samples = int(round(abs(p) * 0.00035 * MIX_SAMPLE_RATE))
    att = np.float32(1.0 - 0.34 * abs(p))
    out = np.empty_like(clip)
    if p > 0:  # panned right -> delay/attenuate left
        out[:, 1] = clip[:, 1]
        if delay_samples > 0 and delay_samples < len(clip):
            out[:delay_samples, 0] = np.float32(0.0)
            out[delay_samples:, 0] = clip[:-delay_samples, 0] * att
        else:
            out[:, 0] = clip[:, 0] * att
    else:  # panned left -> delay/attenuate right
        out[:, 0] = clip[:, 0]
        if delay_samples > 0 and delay_samples < len(clip):
            out[:delay_samples, 1] = np.float32(0.0)
            out[delay_samples:, 1] = clip[:-delay_samples, 1] * att
        else:
            out[:, 1] = clip[:, 1] * att
    return out


def _deterministic_cue_variation(sfx_file: str, t_sec: float) -> tuple[float, float, float]:
    """Deterministic, order-independent (pan, pitch_ratio, gain_mult) from filename & timestamp."""
    base = os.path.basename(sfx_file).lower()
    key = f"{base}@{int(round(t_sec * 1000))}".encode("utf-8")
    h = zlib.crc32(key)
    u1 = ((h & 0xFF) / 255.0) * 2.0 - 1.0          # [-1, 1]
    u2 = (((h >> 8) & 0xFF) / 255.0) * 2.0 - 1.0   # [-1, 1]
    u3 = (((h >> 16) & 0xFF) / 255.0) * 2.0 - 1.0  # [-1, 1]

    pan = u1 * 0.26
    if any(tok in base for tok in PITCH_LOCKED_TOKENS):
        pitch_ratio = 1.0
        gain_mult = 1.0
    else:
        pitch_ratio = 1.0 + u2 * 0.028  # ~±48 cents organic strike shift
        gain_mult = 1.0 + u3 * 0.045    # subtle ±4.5% dynamic touch
    return pan, pitch_ratio, gain_mult


def _convolve_room_bus(wet_send_bus: np.ndarray) -> np.ndarray:
    """Fast FFT stereo convolution turning accumulated room-send energy into physical reflections."""
    if len(wet_send_bus) < 32:
        return np.zeros((0, 2), dtype=np.float32)
    ir = _generate_acoustic_room_ir(MIX_SAMPLE_RATE, 0.20)
    conv_len = len(wet_send_bus) + len(ir) - 1
    nfft = 1 << (conv_len - 1).bit_length()
    wet = np.empty((conv_len, 2), dtype=np.float32)
    for ch in range(2):
        spec = np.fft.rfft(wet_send_bus[:, ch].astype(np.float64), n=nfft) * np.fft.rfft(ir[:, ch].astype(np.float64), n=nfft)
        wet[:, ch] = np.fft.irfft(spec, n=nfft)[:conv_len].astype(np.float32)
    return wet


def _apply_cue_tone_filter(
    clip: np.ndarray,
    *,
    tilt_db: float = 0.0,
    cutoff_hz: float | None = None,
    sub_boost: float = 1.0,
) -> np.ndarray:
    """Shape per-cue spectral tilt, high-frequency air ceiling, and sub anchor cleanly."""
    if len(clip) < 32 or (abs(tilt_db) < 0.05 and cutoff_hz is None and abs(sub_boost - 1.0) < 0.02):
        return clip
    n = len(clip)
    freqs = np.fft.rfftfreq(n, d=1.0 / MIX_SAMPLE_RATE)
    eq = np.ones_like(freqs, dtype=np.float64)
    if abs(tilt_db) >= 0.05:
        # Smooth spectral tilt around 1.2 kHz pivot (-4dB..+4dB high/low balance)
        octaves = np.log2(np.maximum(freqs, 40.0) / 1200.0)
        tilt_curve = np.power(10.0, np.clip(octaves / 3.5, -1.0, 1.0) * (tilt_db / 20.0))
        eq *= tilt_curve
    if cutoff_hz is not None and cutoff_hz > 200.0:
        eq *= 1.0 / (1.0 + (freqs / float(cutoff_hz)) ** 3)
    if abs(sub_boost - 1.0) >= 0.02:
        eq *= 1.0 + (float(sub_boost) - 1.0) * np.exp(-0.5 * (freqs / 82.0) ** 2)
    out = np.empty_like(clip)
    for ch in range(2):
        out[:, ch] = np.fft.irfft(np.fft.rfft(clip[:, ch].astype(np.float64)) * eq, n=n).astype(np.float32)
    return out


def _normalize_sfx_item(item: tuple | dict) -> dict[str, Any]:
    if isinstance(item, dict):
        return {
            "file": item["file"],
            "time": float(item.get("time", 0.0)),
            "volume": float(item.get("volume", 0.85)),
            "pan": float(item["pan"]) if item.get("pan") is not None else None,
            "pitch": float(item["pitch"]) if item.get("pitch") is not None else None,
            "room": float(item["room"]) if item.get("room") is not None else None,
            "tilt_db": float(item.get("tilt_db", 0.0) or 0.0),
            "cutoff_hz": float(item["cutoff_hz"]) if item.get("cutoff_hz") is not None else None,
            "sub_boost": float(item.get("sub_boost", 1.0) if item.get("sub_boost") is not None else 1.0),
        }
    return {
        "file": str(item[0]),
        "time": float(item[1]),
        "volume": float(item[2]),
        "pan": float(item[3]) if len(item) >= 4 and item[3] is not None else None,
        "pitch": float(item[4]) if len(item) >= 5 and item[4] is not None else None,
        "room": None,
        "tilt_db": 0.0,
        "cutoff_hz": None,
        "sub_boost": 1.0,
    }


def _precomposite_sfx_bus(
    sfx_items: list[tuple[Any, ...]] | list[dict[str, Any]],
    target_dur: float | None,
    out_wav: str,
    *,
    humanize: bool = True,
    room_wet: float = 0.11,
) -> None:
    """Sample-accurately composite any number of SFX cues with per-scene tone, pan, jitter & room glue."""
    parsed = [_normalize_sfx_item(it) for it in sfx_items]
    decoded_cache: dict[str, np.ndarray] = {}
    for c in parsed:
        if c["file"] not in decoded_cache:
            decoded_cache[c["file"]] = _decode_audio_48k_stereo(c["file"])

    rendered_clips: list[tuple[np.ndarray, int, float, float]] = []
    max_end_samples = int(round((target_dur or 0.0) * MIX_SAMPLE_RATE))

    for c in parsed:
        sfx_file = c["file"]
        t_sec = c["time"]
        vol = c["volume"]
        clip = decoded_cache[sfx_file]
        if len(clip) == 0:
            continue
        auto_pan, auto_pitch, auto_gain = _deterministic_cue_variation(sfx_file, t_sec) if humanize else (0.0, 1.0, 1.0)
        pan = c["pan"] if c["pan"] is not None else auto_pan
        pitch_ratio = c["pitch"] if c["pitch"] is not None else auto_pitch
        cue_room = c["room"] if c["room"] is not None else room_wet

        clip_proc = _resample_ratio_stereo(clip, pitch_ratio)
        clip_proc = _apply_cue_tone_filter(
            clip_proc,
            tilt_db=c["tilt_db"],
            cutoff_hz=c["cutoff_hz"],
            sub_boost=c["sub_boost"],
        )
        clip_proc = _apply_stereo_pan(clip_proc, pan)
        start_idx = max(0, int(round(t_sec * MIX_SAMPLE_RATE)))
        max_end_samples = max(max_end_samples, start_idx + len(clip_proc))
        rendered_clips.append((clip_proc, start_idx, vol * auto_gain, cue_room))

    bus = np.zeros((max(1, max_end_samples), 2), dtype=np.float32)
    wet_send = np.zeros((max(1, max_end_samples), 2), dtype=np.float32)
    has_wet = False
    for clip_proc, start_idx, eff_vol, cue_room in rendered_clips:
        end_idx = min(len(bus), start_idx + len(clip_proc))
        if end_idx > start_idx:
            seg = clip_proc[: end_idx - start_idx] * np.float32(eff_vol)
            bus[start_idx:end_idx] += seg
            if cue_room > 1e-4:
                wet_send[start_idx:end_idx] += seg * np.float32(cue_room)
                has_wet = True

    # Shared acoustic room glue weighted per-scene / per-cue
    if has_wet and len(rendered_clips) > 0:
        wet_tail = _convolve_room_bus(wet_send)
        if target_dur is not None:
            bus += wet_tail[: len(bus)]
        else:
            out_len = max(len(bus), len(wet_tail))
            if out_len > len(bus):
                padded = np.zeros((out_len, 2), dtype=np.float32)
                padded[: len(bus)] = bus
                bus = padded
            bus[: len(wet_tail)] += wet_tail

    abs_bus = np.abs(bus)
    knee = np.float32(0.85)
    # Local sample-wise soft-knee limiting preserves 1:1 unity gain for all quiet cues while taming overlaps smoothly.
    bus = np.where(
        abs_bus > knee,
        np.sign(bus) * (knee + np.float32(0.13) * np.tanh((abs_bus - knee) / np.float32(0.35))),
        bus,
    )

    pcm = np.clip(bus * 32767.0, -32767.0, 32767.0).astype("<i2")
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(MIX_SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())


def cmd_mix(args):
    if not args.video and not args.out:
        raise ValueError("--out is required")

    target_dur = get_duration(args.video) if args.video else None
    inputs = []
    filter_parts = []
    idx = 0

    vid_idx = None
    if args.video:
        vid_idx = idx
        inputs += ["-i", args.video]
        idx += 1

    voice_idx = None
    if args.voice:
        voice_idx = idx
        inputs += ["-i", args.voice]
        idx += 1

    bgm_idx = None
    if args.bgm:
        bgm_idx = idx
        # Loop BGM if shorter than video
        if target_dur:
            inputs += ["-stream_loop", "-1", "-i", args.bgm]
        else:
            inputs += ["-i", args.bgm]
        idx += 1

    sfx_items: list[dict[str, Any]] = []
    if args.sfx:
        sfx_dir = os.path.dirname(os.path.abspath(args.sfx))
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        search_roots = (
            sfx_dir,
            os.path.dirname(sfx_dir),
            os.path.join(repo_root, "assets"),
            repo_root,
        )
        with open(args.sfx, "r", encoding="utf-8") as f:
            cues = json.load(f)
        for cue in cues:
            cue_file = cue["file"]
            if not os.path.exists(cue_file) and not os.path.isabs(cue_file):
                for base_dir in search_roots:
                    candidate = os.path.join(base_dir, cue_file)
                    if os.path.exists(candidate):
                        cue_file = candidate
                        break
            if not os.path.exists(cue_file):
                print(f"[audio_mix] Warning: SFX file not found, skipping: {cue['file']}", file=sys.stderr)
                continue
            sfx_items.append({
                "file": cue_file,
                "time": float(cue.get("time", 0.0)),
                "volume": float(cue.get("volume", 0.85)),
                "pan": cue.get("pan"),
                "pitch": cue.get("pitch"),
                "room": cue.get("room"),
                "tilt_db": cue.get("tilt_db", 0.0),
                "cutoff_hz": cue.get("cutoff_hz"),
                "sub_boost": cue.get("sub_boost", 1.0),
            })

    mix_labels = []

    with tempfile.TemporaryDirectory(prefix="kinearc_amix_") as tmp_dir:
        sfx_bus_idx = None
        if sfx_items:
            sfx_bus_wav = os.path.join(tmp_dir, "sfx_bus.wav")
            _precomposite_sfx_bus(
                sfx_items,
                target_dur,
                sfx_bus_wav,
                humanize=not getattr(args, "no_humanize", False),
                room_wet=float(getattr(args, "room", 0.11)),
            )
            sfx_bus_idx = idx
            inputs += ["-i", sfx_bus_wav]
            idx += 1

        # Keep original video audio if requested and present
        if args.keep_video_audio and args.video and has_audio_stream(args.video):
            filter_parts.append(f"[{vid_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={args.video_vol}[va]")
            mix_labels.append("[va]")

        # Prepare voice track (and split for sidechain ducking if BGM is present)
        if voice_idx is not None:
            voice_pad = f",apad=whole_dur={target_dur:.3f},atrim=0:{target_dur:.3f}" if target_dur else ""
            if bgm_idx is not None:
                filter_parts.append(f"[{voice_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={args.voice_vol}{voice_pad},asplit=2[vo_mix][vo_sc]")
            else:
                filter_parts.append(f"[{voice_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={args.voice_vol}{voice_pad}[vo_mix]")
            mix_labels.append("[vo_mix]")

        # Prepare BGM track with fade out, voiceover sidechain, and subtle punch ducking on heavy SFX hits
        if bgm_idx is not None:
            dur_trim = f",atrim=0:{target_dur:.3f}" if target_dur else ""
            fade_out = f",afade=t=out:st={max(0.0, target_dur - args.fade_out):.3f}:d={args.fade_out:.3f}" if (target_dur and args.fade_out > 0) else ""
            filter_parts.append(f"[{bgm_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo{dur_trim},volume={args.bgm_vol}{fade_out}[bgm_base]")
            bgm_cur = "[bgm_base]"
            if voice_idx is not None:
                # Automatic sidechain compression: lowers BGM smoothly whenever voiceover speaks
                filter_parts.append(f"{bgm_cur}[vo_sc]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=350:makeup=1[bgm_duck]")
                bgm_cur = "[bgm_duck]"
            if sfx_bus_idx is not None:
                filter_parts.append(f"[{sfx_bus_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[sfx_bus][sfx_sc]")
                filter_parts.append(f"{bgm_cur}[sfx_sc]sidechaincompress=threshold=0.22:ratio=2.4:attack=6:release=220:makeup=1[bgm_final]")
                mix_labels.append("[bgm_final]")
                mix_labels.append("[sfx_bus]")
            else:
                mix_labels.append(bgm_cur)
        elif sfx_bus_idx is not None:
            filter_parts.append(f"[{sfx_bus_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo[sfx_bus]")
            mix_labels.append("[sfx_bus]")

        if not mix_labels:
            raise RuntimeError("No audio tracks provided to mix (specify at least --voice, --bgm, or --sfx).")

        out_dur_fix = f",apad=whole_dur={target_dur:.3f},atrim=0:{target_dur:.3f}" if target_dur else ""
        if len(mix_labels) == 1:
            filter_parts.append(f"{mix_labels[0]}alimiter=limit=0.95{out_dur_fix}[aout]")
        else:
            joined = "".join(mix_labels)
            filter_parts.append(f"{joined}amix=inputs={len(mix_labels)}:duration=longest:normalize=0,alimiter=limit=0.95{out_dur_fix}[aout]")

        filter_complex = ";".join(filter_parts)
        cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex]
        if vid_idx is not None:
            cmd += ["-map", f"{vid_idx}:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", args.out]
        else:
            cmd += ["-map", "[aout]", "-c:a", "aac" if args.out.endswith(".aac") or args.out.endswith(".m4a") else "pcm_s16le", args.out]

        subprocess.run(cmd, check=True)
        print(f"[audio_mix] Mixed {len(mix_labels)} audio stream(s) ({len(sfx_items)} SFX cues) -> {args.out}")


def cmd_cut_pauses(args):
    dur = get_duration(args.input)
    cmd = [
        "ffmpeg", "-i", args.input,
        "-af", f"silencedetect=noise={args.threshold}dB:d={args.min_silence}",
        "-f", "null", "-",
    ]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    stderr = res.stderr

    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]
    if len(ends) < len(starts):
        ends.append(dur)

    pad = args.pad
    silences = list(zip(starts, ends))
    keep_segments = []
    cursor = 0.0
    for s_start, s_end in silences:
        seg_end = min(dur, s_start + pad)
        if seg_end - cursor > 0.08:
            keep_segments.append({"start": round(cursor, 3), "end": round(seg_end, 3)})
        cursor = max(cursor, s_end - pad)
    if dur - cursor > 0.08:
        keep_segments.append({"start": round(cursor, 3), "end": round(dur, 3)})

    cuts_out = args.cuts_json or os.path.splitext(args.out or args.input)[0] + "_cuts.json"
    with open(cuts_out, "w", encoding="utf-8") as f:
        json.dump({"input": args.input, "original_duration": round(dur, 3), "keep_segments": keep_segments}, f, indent=2)
    print(f"[audio_mix] Found {len(silences)} pauses -> {len(keep_segments)} active segments saved to {cuts_out}")

    if args.out and keep_segments:
        has_vid = False
        probe_v = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=index", "-of", "csv=p=0", args.input],
            text=True,
            encoding="utf-8",
        ).strip()
        has_vid = len(probe_v) > 0

        parts = []
        concat_inputs = []
        for i, seg in enumerate(keep_segments):
            s, e = seg["start"], seg["end"]
            if has_vid:
                parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
                parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
                concat_inputs.append(f"[v{i}][a{i}]")
            else:
                parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
                concat_inputs.append(f"[a{i}]")

        if has_vid:
            parts.append(f"{''.join(concat_inputs)}concat=n={len(keep_segments)}:v=1:a=1[outv][outa]")
            fc = ";".join(parts)
            subprocess.run([
                "ffmpeg", "-y", "-i", args.input, "-filter_complex", fc,
                "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "256k", args.out
            ], check=True)
        else:
            parts.append(f"{''.join(concat_inputs)}concat=n={len(keep_segments)}:v=0:a=1[outa]")
            fc = ";".join(parts)
            subprocess.run([
                "ffmpeg", "-y", "-i", args.input, "-filter_complex", fc,
                "-map", "[outa]", args.out
            ], check=True)
        print(f"[audio_mix] Exported pause-free clip -> {args.out}")


def main():
    parser = argparse.ArgumentParser(description="kinearc automated audio mixing & pause-cutting toolkit.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_mix = sub.add_parser("mix", help="Mix video + voiceover + auto-ducking BGM + timestamped SFX cues.")
    p_mix.add_argument("--video", help="Input video file (video stream copied losslessly)")
    p_mix.add_argument("--voice", help="Voiceover audio file")
    p_mix.add_argument("--bgm", help="Background music audio file (auto-looped & auto-ducked under voice)")
    p_mix.add_argument("--sfx", help="JSON file of SFX cues: [{\"file\": \"...\", \"time\": 1.5, \"volume\": 0.8}]")
    p_mix.add_argument("--out", required=True, help="Output MP4 or audio path")
    p_mix.add_argument("--voice_vol", type=float, default=1.0)
    p_mix.add_argument("--bgm_vol", type=float, default=0.35)
    p_mix.add_argument("--video_vol", type=float, default=1.0)
    p_mix.add_argument("--fade_out", type=float, default=1.5, help="BGM fade-out seconds at end of video")
    p_mix.add_argument("--keep_video_audio", action="store_true", help="Include original audio from --video in mix")
    p_mix.add_argument("--room", type=float, default=0.11, help="Shared acoustic room reflection wetness (0.0 disables, default 0.11)")
    p_mix.add_argument("--no_humanize", action="store_true", help="Disable deterministic micro pitch/pan/velocity humanization on SFX")

    p_cut = sub.add_parser("cut-pauses", help="Detect and trim silent pauses from voiceover or talking-head video.")
    p_cut.add_argument("--input", required=True, help="Input audio or video file")
    p_cut.add_argument("--out", help="Optional output trimmed audio/video file")
    p_cut.add_argument("--cuts_json", help="Path to write detected keep_segments JSON")
    p_cut.add_argument("--threshold", type=float, default=-32.0, help="Silence threshold in dB (default -32)")
    p_cut.add_argument("--min_silence", type=float, default=0.45, help="Minimum silence duration in seconds")
    p_cut.add_argument("--pad", type=float, default=0.08, help="Keep padding seconds around speech edges")

    args = parser.parse_args()
    if args.command == "mix":
        cmd_mix(args)
    elif args.command == "cut-pauses":
        cmd_cut_pauses(args)


if __name__ == "__main__":
    main()
