#!/usr/bin/env python3
"""
extract_audio_style.py — Universal Reference Audio Analyzer, Stem Slicer & SFX Pack Remaker.

Works with any reference video (.mp4/.mov/.webm) or audio file (.wav/.mp3/.m4a/.aac):
  1. Measures 5-band spectral DNA (<90Hz sub, 90-250Hz bass, 250-1kHz lowmid, 1k-4kHz highmid, 4kHz+ air),
     stereo imaging, dynamic silence pockets, and recommended BGM mode (none / ambient / groove).
  2. Slices isolated onset/transient SFX stems cleanly into `<out_dir>/stems/` with semantic labels
     (tap, key, tick, glint, swish, whoosh, sub_impact, ping, chord) + onset timeline cues.
  3. Optionally builds a 100% copyright-clean custom organic SFX pack (`sfx/` + `catalog.json`)
     remade to match the exact brightness, airiness, sub weight, clarity, and room scale of the reference.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any
import wave

import numpy as np

ANALYSIS_SR = 48000
SCRIPTS_DIR = Path(__file__).resolve().parent


def _has_audio_stream(path: str) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        path,
    ]
    out = subprocess.check_output(cmd, text=True, encoding="utf-8").strip()
    return len(out) > 0


def _decode_stereo_48k(path: str) -> np.ndarray:
    """Decode any audio/video audio stream to float64 stereo (N, 2) at 48kHz via FFmpeg."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            path,
            "-vn",
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            "2",
            "-ar",
            str(ANALYSIS_SR),
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    arr = np.frombuffer(proc.stdout, dtype="<f4").astype(np.float64)
    if arr.size == 0:
        return np.zeros((0, 2), dtype=np.float64)
    return arr.reshape(-1, 2)


def _write_stereo_wav(path: Path, samples: np.ndarray, sr: int = ANALYSIS_SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(samples, dtype=np.float64)
    if arr.ndim == 1:
        arr = np.column_stack((arr, arr))
    peak = float(np.max(np.abs(arr))) if arr.size else 1.0
    if peak > 0.96:
        arr = arr * (0.94 / peak)
    pcm = np.clip(arr * 32767.0, -32767.0, 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def analyze_samples_dna(samples: np.ndarray, sr: int = ANALYSIS_SR) -> dict[str, Any]:
    """Compute spectral band DNA, dynamics, silence pockets, BGM mode, and custom remake parameters."""
    if len(samples) < max(256, int(0.05 * sr)):
        raise ValueError("Audio stream is too short to analyze (< 50 ms)")

    mono = 0.5 * (samples[:, 0] + samples[:, 1])
    side = 0.5 * (samples[:, 0] - samples[:, 1])
    rms = float(np.sqrt(np.mean(mono ** 2))) + 1e-12
    peak = float(np.max(np.abs(samples))) + 1e-12
    rms_dbfs = round(20.0 * math.log10(rms), 2)
    crest_db = round(20.0 * math.log10(peak / rms), 2)
    stereo_side = round(float(np.sqrt(np.mean(side ** 2))) / rms, 3)

    spec = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / sr)
    p2 = spec ** 2
    e_total = float(np.sum(p2)) + 1e-12

    sub_pct = round(100.0 * float(np.sum(p2[freqs < 90.0])) / e_total, 2)
    bass_pct = round(100.0 * float(np.sum(p2[(freqs >= 90.0) & (freqs < 250.0)])) / e_total, 2)
    lowmid_pct = round(100.0 * float(np.sum(p2[(freqs >= 250.0) & (freqs < 1000.0)])) / e_total, 2)
    highmid_pct = round(100.0 * float(np.sum(p2[(freqs >= 1000.0) & (freqs < 4000.0)])) / e_total, 2)
    air_pct = round(100.0 * float(np.sum(p2[freqs >= 4000.0])) / e_total, 2)
    centroid_hz = round(float(np.sum(freqs * p2) / e_total), 1)

    hop = max(1, int(0.05 * sr))
    n_frames = len(mono) // hop
    if n_frames >= 1:
        frames = mono[: n_frames * hop].reshape(n_frames, hop)
        erms = np.sqrt(np.mean(frames ** 2, axis=1))
        p10 = float(np.percentile(erms, 10))
        p50 = float(np.percentile(erms, 50))
        p90 = float(np.percentile(erms, 90))
        silence_frac = round(float(np.mean(erms < 0.0056)), 3)  # ~ -45 dBFS threshold
    else:
        p10, p50, p90, silence_frac = rms, rms, rms, 0.0

    if silence_frac >= 0.22:
        bgm_mode = "none"
    elif p10 < 0.009:
        bgm_mode = "ambient"
    else:
        bgm_mode = "groove"

    # Select closest organic base style + compute continuous acoustic sculpting targets
    if air_pct >= 8.0 and bass_pct <= 6.5:
        rec_style = "airy-clean"
    elif air_pct >= 4.5 or highmid_pct >= 26.0:
        rec_style = "crisp-glass"
    elif sub_pct >= 38.0 and air_pct < 4.5:
        rec_style = "cinematic-sub"
    else:
        rec_style = "tactile-wood"

    # Map measured reference bands cleanly into custom remake DSP modifiers
    air_lift = round(max(0.85, min(2.45, 1.0 + (air_pct / 12.0) * 1.15)), 3)
    mud_scoop = round(max(0.0, min(0.90, 0.88 - (bass_pct / 18.0) * 0.65)), 3)
    sub_keep = round(max(0.65, min(1.35, 0.72 + (sub_pct / 45.0) * 0.45)), 3)
    cutoff_hz = round(max(6200.0, min(17500.0, 6800.0 + (air_pct / 16.0) * 9800.0)), 1)
    room_wet = round(0.05 if bgm_mode == "none" else (0.09 if air_pct >= 8.0 else 0.14), 3)

    return {
        "duration_sec": round(len(mono) / sr, 3),
        "sample_rate": sr,
        "rms_dbfs": rms_dbfs,
        "crest_db": crest_db,
        "stereo_side_ratio": stereo_side,
        "centroid_hz": centroid_hz,
        "bands_pct": {
            "sub_lt_90hz": sub_pct,
            "bass_90_250hz": bass_pct,
            "lowmid_250_1khz": lowmid_pct,
            "highmid_1k_4khz": highmid_pct,
            "air_4khz_plus": air_pct,
        },
        "dynamics": {
            "p10_rms": round(p10, 5),
            "p50_rms": round(p50, 5),
            "p90_rms": round(p90, 5),
            "silence_fraction": silence_frac,
        },
        "recommended_bgm_mode": bgm_mode,
        "recommended_style": rec_style,
        "remake_params": {
            "air_lift": air_lift,
            "mud_scoop": mud_scoop,
            "sub_keep": sub_keep,
            "cutoff_hz": cutoff_hz,
            "room_wet": room_wet,
        },
    }


def _classify_stem(clip: np.ndarray, sr: int) -> dict[str, Any]:
    mono = 0.5 * (clip[:, 0] + clip[:, 1])
    dur = len(mono) / sr
    spec = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / sr)
    p2 = spec ** 2
    e = float(np.sum(p2)) + 1e-12
    cent = float(np.sum(freqs * p2) / e)
    sub_r = float(np.sum(p2[freqs < 110.0]) / e)
    air_r = float(np.sum(p2[freqs >= 4000.0]) / e)
    # Spectral flatness helps distinguish broadband swishes from pitched chimes/chords
    geo_mean = float(np.exp(np.mean(np.log(spec + 1e-9))))
    flatness = geo_mean / (float(np.mean(spec)) + 1e-9)

    if sub_r >= 0.55:
        kind = "portal" if dur > 0.38 else "sub_impact"
    elif dur < 0.085 and flatness > 0.14:
        kind = "key" if air_r > 0.25 else "tick"
    elif dur < 0.14 and cent >= 2200.0:
        kind = "tap" if air_r >= 0.20 else "latch"
    elif flatness > 0.22 and 0.12 <= dur <= 0.58:
        kind = "whoosh" if cent < 1800.0 else "swish"
    elif dur >= 0.50:
        kind = "chord" if cent < 1400.0 else "bloom"
    else:
        kind = "glint" if cent >= 2200.0 else "ping"

    return {
        "kind": kind,
        "duration_sec": round(dur, 3),
        "centroid_hz": round(cent, 1),
        "sub_ratio": round(sub_r, 3),
        "air_ratio": round(air_r, 3),
    }


def extract_onset_stems(
    samples: np.ndarray,
    stems_dir: Path,
    sr: int = ANALYSIS_SR,
    max_stems: int = 18,
    min_gap_sec: float = 0.12,
) -> list[dict[str, Any]]:
    """Slice isolated transient SFX events from a reference audio track into stereo WAV stems."""
    mono = 0.5 * (samples[:, 0] + samples[:, 1])
    hop = int(0.005 * sr)  # 5 ms envelope step
    n_frames = len(mono) // hop
    if n_frames < 4:
        return []

    frames = mono[: n_frames * hop].reshape(n_frames, hop)
    rms_env = np.sqrt(np.mean(frames ** 2, axis=1))
    diff = np.maximum(0.0, np.diff(rms_env, prepend=rms_env[0]))
    thresh = max(0.012, float(np.percentile(rms_env, 75)) * 0.45)

    # Local peak onset detection with cooldown gap
    min_gap_frames = max(1, int(round(min_gap_sec / 0.005)))
    onsets: list[int] = []
    last_f = -min_gap_frames
    for fi in range(1, n_frames - 1):
        if fi - last_f < min_gap_frames:
            continue
        if (diff[fi] >= thresh or rms_env[fi] >= thresh * 1.4) and rms_env[fi] >= rms_env[fi - 1]:
            # Step back slightly to capture initial transient edge
            start_f = max(0, fi - 2)
            onsets.append(start_f)
            last_f = fi

    # Keep strongest peaks up to max_stems if track is busy, ordered chronologically
    if len(onsets) > max_stems:
        scored = sorted(
            onsets,
            key=lambda sf: float(np.max(rms_env[sf : min(n_frames, sf + 12)])),
            reverse=True,
        )[:max_stems]
        onsets = sorted(scored)

    stems_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    kind_counts: dict[str, int] = {}

    for idx, sf in enumerate(onsets):
        next_sf = onsets[idx + 1] if idx + 1 < len(onsets) else n_frames
        max_len_frames = min(n_frames - sf, int(round(0.95 / 0.005)), max(10, next_sf - sf - 1))
        seg_env = rms_env[sf : sf + max_len_frames]
        pk = float(np.max(seg_env)) if len(seg_env) else 0.0
        if pk < 0.015:
            continue

        # Find decay point below 3% of local peak (with >= 45 ms minimum slice)
        min_keep = min(len(seg_env), max(9, int(round(0.045 / 0.005))))
        tail_f = len(seg_env)
        for j in range(min_keep, len(seg_env)):
            if seg_env[j] < pk * 0.03:
                tail_f = j + 2
                break
        tail_f = min(len(seg_env), tail_f)

        s0 = max(0, sf * hop)
        s1 = min(len(samples), (sf + tail_f) * hop)
        if s1 - s0 < int(0.035 * sr):
            continue

        clip = samples[s0:s1].copy()
        fade_in = min(len(clip) // 4, int(0.003 * sr))
        fade_out = min(len(clip) // 3, int(0.014 * sr))
        if fade_in > 1:
            clip[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
        if fade_out > 1:
            clip[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None]

        meta = _classify_stem(clip, sr)
        kind = meta["kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        fname = f"ref_{kind}_{kind_counts[kind]:02d}.wav"
        out_wav = stems_dir / fname
        _write_stereo_wav(out_wav, clip, sr=sr)

        results.append({
            "file": f"stems/{fname}",
            "time": round(s0 / sr, 3),
            "volume": round(min(0.92, max(0.45, pk * 1.8)), 2),
            **meta,
        })

    return results


def extract_audio_style(
    input_path: str | os.PathLike[str],
    out_dir: str | os.PathLike[str],
    *,
    remake_pack: bool = True,
    max_stems: int = 18,
    allow_silent: bool = False,
) -> dict[str, Any]:
    """Analyze any reference video/audio, extract onset stems, and optionally remake a custom SFX pack."""
    src = Path(os.path.abspath(os.fspath(input_path)))
    if not src.is_file():
        raise FileNotFoundError(f"Reference video or audio file not found: {src}")

    out_root = Path(os.path.abspath(os.fspath(out_dir)))
    out_root.mkdir(parents=True, exist_ok=True)

    if not _has_audio_stream(str(src)):
        if allow_silent:
            silent_rep = {
                "source": str(src),
                "has_audio": False,
                "recommended_style": "airy-clean",
                "recommended_bgm_mode": "none",
            }
            prof_p = out_root / "audio_profile.json"
            prof_p.write_text(json.dumps(silent_rep, indent=2) + "\n", encoding="utf-8")
            return silent_rep
        raise ValueError(f"Reference file contains no audio stream: {src}")

    samples = _decode_stereo_48k(str(src))
    profile = analyze_samples_dna(samples, sr=ANALYSIS_SR)
    stems = extract_onset_stems(samples, out_root / "stems", sr=ANALYSIS_SR, max_stems=max_stems)

    report: dict[str, Any] = {
        "source": str(src),
        "has_audio": True,
        **profile,
        "extracted_stems": stems,
    }

    if remake_pack:
        import importlib

        if str(SCRIPTS_DIR) not in os.sys.path:
            os.sys.path.insert(0, str(SCRIPTS_DIR))
        build_sfx_pack = importlib.import_module("build_sfx_pack")
        remake_res = build_sfx_pack.build_sfx_pack(
            out_root / "sfx",
            style=profile["recommended_style"],
            custom_eq=profile["remake_params"],
        )
        report["remake_sfx_dir"] = remake_res["out_dir"]
        report["remake_catalog"] = remake_res["catalog"]
        report["remake_file_count"] = len(remake_res["files"])

    profile_path = out_root / "audio_profile.json"
    profile_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # Write extracted timeline cues template cleanly for instant experimentation
    cues_out = out_root / "extracted_cues.json"
    cues_payload = [{"file": s["file"], "time": s["time"], "volume": s["volume"]} for s in stems]
    cues_out.write_text(json.dumps(cues_payload, indent=2) + "\n", encoding="utf-8")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="extract_audio_style.py",
        description="Analyze any reference video/audio, extract onset stems, and remake a matching organic SFX pack.",
    )
    parser.add_argument("--input", required=True, help="Path to reference video (.mp4/.mov/.webm) or audio file")
    parser.add_argument("--out_dir", default=".kinearc_analysis/audio", help="Output directory for profile, stems, and remade SFX pack")
    parser.add_argument("--no-remake", action="store_true", help="Skip building a custom copyright-clean sfx/ pack from the profile")
    parser.add_argument("--max_stems", type=int, default=18, help="Maximum isolated onset stems to slice (default 18)")
    parser.add_argument("--allow-silent", action="store_true", help="Return structured silent report instead of failing if input has no audio")
    args = parser.parse_args(argv)

    rep = extract_audio_style(
        args.input,
        args.out_dir,
        remake_pack=not args.no_remake,
        max_stems=args.max_stems,
        allow_silent=bool(args.allow_silent),
    )
    print(
        f"[extract-audio] style={rep.get('recommended_style')} bgm={rep.get('recommended_bgm_mode')} "
        f"stems={len(rep.get('extracted_stems', []))} -> {args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
