#!/usr/bin/env python3
"""
build_sfx_pack.py — Acoustic-Modeled Tactile Foley & Groove BGM Generator for kinearc.

Synthesizes 12 multi-layered tactile SFX WAV files + 1 seamless groove BGM WAV + catalog.json
into `assets/sfx/` using physical acoustic envelopes (mechanical switch double-transients,
bandpass-swept pink noise, 808 pitch-drop sub impacts, harmonic crystal chimes, and warm
detuned chord progressions).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
import wave

import numpy as np

SAMPLE_RATE = 44100
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "assets" / "sfx"


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = float(np.max(np.abs(samples))) if samples.size else 1.0
    if peak > 0.98:
        samples = samples * (0.96 / peak)
    pcm = np.clip(samples * 32767.0, -32767.0, 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def _pink_noise(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    scale = 1.0 / np.maximum(np.sqrt(freqs), 1.0)
    scale[0] = 0.0
    spec = np.fft.rfft(white) * scale
    pink = np.fft.irfft(spec, n=n)
    mx = float(np.max(np.abs(pink))) or 1.0
    return pink / mx


def _bandpass_fft(sig: np.ndarray, f_low: float, f_high: float) -> np.ndarray:
    n = len(sig)
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    center = 0.5 * (f_low + f_high)
    bw = max(40.0, f_high - f_low)
    gain = np.exp(-0.5 * ((freqs - center) / (bw * 0.5)) ** 2)
    out = np.fft.irfft(np.fft.rfft(sig) * gain, n=n)
    mx = float(np.max(np.abs(out))) or 1.0
    return out / mx


def _synth_key_clack(pitch_mult: float, seed: int) -> np.ndarray:
    dur = 0.085
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    noise = _pink_noise(n, seed)

    # 1. Tactile stem bump at t=0ms
    env_stem = np.exp(-t / 0.0025)
    f_stem = (2650.0 * pitch_mult) * t
    stem = (
        0.55 * np.sin(2.0 * np.pi * f_stem)
        + 0.35 * np.sin(2.0 * np.pi * (4100.0 * pitch_mult) * t)
        + 0.45 * _bandpass_fft(noise, 1400.0 * pitch_mult, 4200.0 * pitch_mult)
    ) * env_stem

    # 2. Keycap PBT cavity thock at t=9ms
    t_bot = np.maximum(0.0, t - 0.009)
    mask_bot = (t >= 0.009).astype(np.float64)
    f_cavity = (640.0 * pitch_mult) * np.exp(-t_bot / 0.018) + (195.0 * pitch_mult)
    phase_cav = np.cumsum(2.0 * np.pi * f_cavity / SAMPLE_RATE)
    env_bot = np.exp(-t_bot / 0.011) * mask_bot
    thock = (
        0.75 * np.sin(phase_cav)
        + 0.40 * np.sin(2.0 * np.pi * (310.0 * pitch_mult) * t_bot)
        + 0.35 * _bandpass_fft(noise, 300.0 * pitch_mult, 1200.0 * pitch_mult)
    ) * env_bot

    # 3. Subtle top-out release tick at t=44ms
    t_rel = np.maximum(0.0, t - 0.044)
    mask_rel = (t >= 0.044).astype(np.float64)
    env_rel = np.exp(-t_rel / 0.003) * mask_rel
    rel = 0.18 * np.sin(2.0 * np.pi * (1950.0 * pitch_mult) * t_rel) * env_rel

    sig = stem + thock + rel
    return np.tanh(sig * 1.35) * 0.85


def _synth_ui_tap() -> np.ndarray:
    dur = 0.050
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    freq = 110.0 + 310.0 * np.exp(-t / 0.0055)
    phase = np.cumsum(2.0 * np.pi * freq / SAMPLE_RATE)
    env = np.exp(-t / 0.0085)
    click = 0.30 * np.sin(2.0 * np.pi * 2900.0 * t) * np.exp(-t / 0.0018)
    return np.tanh((np.sin(phase) * env + click) * 1.25) * 0.84


def _synth_switch_latch() -> np.ndarray:
    dur = 0.115
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    # Pre-click at t=0
    pre = 0.42 * np.sin(2.0 * np.pi * 1850.0 * t) * np.exp(-t / 0.0032)
    # Main magnetic lock at t=22ms
    t2 = np.maximum(0.0, t - 0.022)
    m2 = (t >= 0.022).astype(np.float64)
    f_lock = 140.0 + 360.0 * np.exp(-t2 / 0.007)
    ph_lock = np.cumsum(2.0 * np.pi * f_lock / SAMPLE_RATE)
    latch = (
        0.75 * np.sin(ph_lock) * np.exp(-t2 / 0.016)
        + 0.45 * np.sin(2.0 * np.pi * 2750.0 * t2) * np.exp(-t2 / 0.0035)
    ) * m2
    return np.tanh((pre + latch) * 1.3) * 0.88


def _synth_scrubber_tick() -> np.ndarray:
    dur = 0.030
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    body = 0.65 * np.sin(2.0 * np.pi * 880.0 * t) * np.exp(-t / 0.0038)
    edge = 0.45 * np.sin(2.0 * np.pi * 3650.0 * t) * np.exp(-t / 0.0014)
    return (body + edge) * 0.78


def _synth_air_swish_fast() -> np.ndarray:
    dur = 0.23
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    u = t / dur
    env = np.sin(np.pi * u) ** 2.1
    noise = _pink_noise(n, 404)
    low_band = _bandpass_fft(noise, 240.0, 750.0)
    mid_band = _bandpass_fft(noise, 650.0, 1950.0)
    sweep_mix = (1.0 - env) * low_band + env * mid_band
    sub_glide = 0.28 * np.sin(2.0 * np.pi * (95.0 + 90.0 * env) * t) * env
    return np.tanh((sweep_mix * 0.75 + sub_glide) * env * 1.35) * 0.82


def _synth_air_whoosh_deep() -> np.ndarray:
    dur = 0.42
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    u = t / dur
    env = np.sin(np.pi * u) ** 1.8
    noise = _pink_noise(n, 505)
    warm_air = 0.65 * _bandpass_fft(noise, 180.0, 920.0) + 0.35 * _bandpass_fft(noise, 800.0, 2100.0) * env
    f_sub = 58.0 + 115.0 * np.sin(np.pi * u)
    ph_sub = np.cumsum(2.0 * np.pi * f_sub / SAMPLE_RATE)
    sub = 0.52 * np.sin(ph_sub) * env
    return np.tanh((warm_air * env + sub) * 1.25) * 0.85


def _synth_sub_impact() -> np.ndarray:
    dur = 0.48
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    f_sub = 48.0 + 118.0 * np.exp(-t / 0.032)
    phase = np.cumsum(2.0 * np.pi * f_sub / SAMPLE_RATE)
    env = (1.0 - np.exp(-t / 0.004)) * np.exp(-t / 0.145)
    punch = 0.25 * np.sin(2.0 * np.pi * 420.0 * t) * np.exp(-t / 0.008)
    sig = (np.sin(phase) + 0.22 * np.sin(2.0 * phase)) * env + punch
    return np.tanh(sig * 1.35) * 0.90


def _synth_glass_ping() -> np.ndarray:
    dur = 0.56
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    attack = 1.0 - np.exp(-t / 0.0025)
    sig = (
        0.55 * np.sin(2.0 * np.pi * 1174.66 * t) * np.exp(-t / 0.18)
        + 0.32 * np.sin(2.0 * np.pi * 1760.00 * t) * np.exp(-t / 0.13)
        + 0.20 * np.sin(2.0 * np.pi * 2637.02 * t) * np.exp(-t / 0.09)
        + 0.10 * np.sin(2.0 * np.pi * 3520.00 * t) * np.exp(-t / 0.05)
    ) * attack
    return sig * 0.82


def _synth_warm_riser() -> np.ndarray:
    dur = 0.85
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    u = t / dur
    env = (u ** 2.2) * np.exp(-np.maximum(0.0, u - 0.90) / 0.035)
    f1 = 165.0 + 330.0 * (u ** 1.7)
    f2 = f1 * 1.498
    ph1 = np.cumsum(2.0 * np.pi * f1 / SAMPLE_RATE)
    ph2 = np.cumsum(2.0 * np.pi * f2 / SAMPLE_RATE)
    air = _bandpass_fft(_pink_noise(n, 707), 350.0, 2400.0) * (u ** 1.5) * 0.35
    sig = (0.48 * np.sin(ph1) + 0.36 * np.sin(ph2) + air) * env
    return np.tanh(sig * 1.2) * 0.82


def _synth_analog_chord() -> np.ndarray:
    dur = 1.25
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    # Warm Dmin9 voicing: D3, F3, A3, C4, E4
    notes = [146.83, 174.61, 220.00, 261.63, 329.63, 440.00]
    attack = 1.0 - np.exp(-t / 0.012)
    decay = np.exp(-t / 0.48)
    sig = np.zeros(n, dtype=np.float64)
    for idx, f in enumerate(notes):
        detune = 1.0 + (idx - 2.5) * 0.0014
        tone = np.sin(2.0 * np.pi * f * detune * t) + 0.25 * np.sin(4.0 * np.pi * f * t) * np.exp(-t / 0.16)
        sig += tone / len(notes)
    sub = 0.35 * np.sin(2.0 * np.pi * 73.42 * t) * np.exp(-t / 0.38)
    return np.tanh((sig * attack * decay + sub * attack) * 1.45) * 0.88


def _synth_bgm_groove() -> np.ndarray:
    """Synthesize a 12.0s warm Rhodes & sub-bass instrumental groove at 80 BPM pocket tempo (seamless loop)."""
    dur = 12.0
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    sig = np.zeros(n, dtype=np.float64)

    # 4 chords across 12.0s (3.0s each): Dm9 -> Bbmaj7 -> Gm9 -> A7sus4
    chords = [
        (0.0, 3.0, [73.42, 146.83, 174.61, 220.00, 261.63, 329.63]),
        (3.0, 6.0, [58.27, 116.54, 174.61, 220.00, 293.66, 349.23]),
        (6.0, 9.0, [49.00, 98.00, 146.83, 174.61, 220.00, 293.66]),
        (9.0, 12.0, [55.00, 110.00, 164.81, 196.00, 246.94, 293.66]),
    ]
    for start, end, freqs in chords:
        mask = (t >= start) & (t < end)
        lt = t[mask] - start
        env = (1.0 - np.exp(-lt / 0.035)) * np.exp(-lt / 2.2)
        chord_wave = np.zeros_like(lt)
        for i, f in enumerate(freqs):
            weight = 0.42 if i == 0 else (0.24 / (len(freqs) - 1))
            chord_wave += weight * (
                np.sin(2.0 * np.pi * f * lt)
                + 0.18 * np.sin(2.0 * np.pi * (f * 2.0) * lt) * np.exp(-lt / 0.55)
            )
        sig[mask] += chord_wave * env

    # Soft pocket kick + rimshot pulse every 0.75s (80 BPM half-time / 160 pulse)
    step = 0.75
    beat_idx = 0
    while beat_idx * step < dur - 0.15:
        bt = beat_idx * step
        if beat_idx % 2 == 0:
            # Soft warm sub kick
            mask = (t >= bt) & (t < bt + 0.22)
            lt = t[mask] - bt
            f_k = 46.0 + 75.0 * np.exp(-lt / 0.022)
            ph_k = np.cumsum(2.0 * np.pi * f_k / SAMPLE_RATE)
            sig[mask] += 0.36 * np.sin(ph_k) * np.exp(-lt / 0.095)
        else:
            # Crisp pocket rim/tap
            mask = (t >= bt) & (t < bt + 0.045)
            lt = t[mask] - bt
            sig[mask] += 0.14 * np.sin(2.0 * np.pi * 1420.0 * lt) * np.exp(-lt / 0.006)
        beat_idx += 1

    # Smooth loop boundary crossfade (first/last 40ms)
    fade_n = int(0.04 * SAMPLE_RATE)
    ramp = np.linspace(0.0, 1.0, fade_n)
    sig[:fade_n] *= ramp
    sig[-fade_n:] *= ramp[::-1]
    return np.tanh(sig * 1.15) * 0.72


def _synth_harmonic_swell() -> np.ndarray:
    """Warm E4+E5 airy harmonic swell (inspired by focus-pull reveal locks)."""
    dur = 0.65
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    env = np.sin(np.pi * (t / dur)) ** 1.4 * np.exp(-t / 0.42)
    air = _bandpass_fft(_pink_noise(n, 811), 600.0, 3400.0) * 0.16 * np.sin(np.pi * t / dur)
    tone = (
        0.55 * np.sin(2.0 * np.pi * 329.63 * t)
        + 0.30 * np.sin(2.0 * np.pi * 659.25 * t)
        + 0.18 * np.sin(2.0 * np.pi * 493.88 * t)
    )
    return np.tanh((tone * env + air) * 1.15) * 0.84


def _synth_crystal_glint() -> np.ndarray:
    """Feather-light UI sparkle & 2.7kHz/5.7kHz air glint for pill stretches and tile bops."""
    dur = 0.14
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    env = (1.0 - np.exp(-t / 0.002)) * np.exp(-t / 0.028)
    air = _bandpass_fft(_pink_noise(n, 912), 2800.0, 8200.0) * 0.28 * env
    bell = (
        0.52 * np.sin(2.0 * np.pi * 2793.8 * t) * np.exp(-t / 0.032)
        + 0.28 * np.sin(2.0 * np.pi * 5587.7 * t) * np.exp(-t / 0.014)
        + 0.25 * np.sin(2.0 * np.pi * 392.0 * t) * np.exp(-t / 0.024)
    ) * (1.0 - np.exp(-t / 0.0015))
    return np.tanh((bell + air) * 1.1) * 0.80


def _synth_bloom_chime() -> np.ndarray:
    """Radiant C6+E5 radial bloom burst for Light<->Dark portal completion."""
    dur = 0.92
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    atk = 1.0 - np.exp(-t / 0.008)
    tail = np.exp(-t / 0.34)
    air = _bandpass_fft(_pink_noise(n, 913), 1200.0, 6800.0) * 0.22 * np.exp(-t / 0.16)
    chime = (
        0.48 * np.sin(2.0 * np.pi * 659.25 * t)
        + 0.36 * np.sin(2.0 * np.pi * 1046.50 * t)
        + 0.22 * np.sin(2.0 * np.pi * 783.99 * t)
        + 0.14 * np.sin(2.0 * np.pi * 1567.98 * t) * np.exp(-t / 0.20)
    )
    return np.tanh((chime * atk * tail + air * atk) * 1.2) * 0.85


def _synth_portal_drop() -> np.ndarray:
    """Deep velvety Light->Dark portal sub sink with air sweep."""
    dur = 0.62
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    f_sub = 42.0 + 108.0 * np.exp(-t / 0.065)
    ph = np.cumsum(2.0 * np.pi * f_sub / SAMPLE_RATE)
    env = (1.0 - np.exp(-t / 0.012)) * np.exp(-t / 0.22)
    air = _bandpass_fft(_pink_noise(n, 914), 160.0, 950.0) * 0.32 * np.sin(np.pi * t / dur)
    return np.tanh((np.sin(ph) * env + air) * 1.3) * 0.88


def _synth_bgm_ambient() -> np.ndarray:
    """Breathable warm minimal floating pad (no percussion) leaving open space for crisp SFX."""
    dur = 12.0
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    sig = np.zeros(n, dtype=np.float64)
    # Softly breathing Emaj9 -> C#m9 two-chord bed
    blocks = [
        (0.0, 6.0, [164.81, 246.94, 329.63, 415.30]),
        (6.0, 12.0, [138.59, 207.65, 277.18, 329.63]),
    ]
    for start, end, freqs in blocks:
        mask = (t >= start) & (t < end)
        lt = t[mask] - start
        swell = np.sin(np.pi * (lt / (end - start))) ** 1.3
        wave_pad = np.zeros_like(lt)
        for idx, f in enumerate(freqs):
            wave_pad += (0.28 / len(freqs)) * np.sin(2.0 * np.pi * f * lt + idx * 0.3)
        sig[mask] += wave_pad * swell
    fade_n = int(0.05 * SAMPLE_RATE)
    ramp = np.linspace(0.0, 1.0, fade_n)
    sig[:fade_n] *= ramp
    sig[-fade_n:] *= ramp[::-1]
    return sig * 0.45


CATALOG_SPEC: dict[str, Any] = {
    "version": "3.0",
    "bgm_default": "sfx/bgm_groove.wav",
    "events": {
        "key": {
            "files": ["sfx/key_clack_01.wav", "sfx/key_clack_02.wav", "sfx/key_clack_03.wav"],
            "default_volume": 0.66,
            "preroll_sec": 0.0,
            "description": "Tactile mechanical switch keystrokes with 3 pitch variations",
        },
        "tap": {
            "files": ["sfx/ui_tap.wav"],
            "default_volume": 0.70,
            "preroll_sec": 0.0,
            "description": "Crisp capacitive haptic micro-tap for cursor hovers and button clicks",
        },
        "click": {
            "files": ["sfx/ui_tap.wav"],
            "default_volume": 0.72,
            "preroll_sec": 0.0,
            "description": "Alias for tactile UI click/tap",
        },
        "latch": {
            "files": ["sfx/switch_latch.wav"],
            "default_volume": 0.80,
            "preroll_sec": 0.0,
            "description": "Dual-transient magnetic snap for toggles, locks, and state transitions",
        },
        "lock": {
            "files": ["sfx/switch_latch.wav"],
            "default_volume": 0.80,
            "preroll_sec": 0.0,
            "description": "Alias for magnetic latch lock",
        },
        "tick": {
            "files": ["sfx/scrubber_tick.wav"],
            "default_volume": 0.56,
            "preroll_sec": 0.0,
            "description": "Precision rotary detent micro-tick for timeline scrubbing and counters",
        },
        "swish": {
            "files": ["sfx/air_swish_fast.wav"],
            "default_volume": 0.72,
            "preroll_sec": 0.030,
            "description": "Fast bandpass-swept foley swish for card entrances and panel slides",
        },
        "whoosh": {
            "files": ["sfx/air_whoosh_deep.wav"],
            "default_volume": 0.76,
            "preroll_sec": 0.035,
            "description": "Warm low-mid doppler transition whoosh for camera shifts and cuts",
        },
        "sub_impact": {
            "files": ["sfx/sub_impact.wav"],
            "default_volume": 0.84,
            "preroll_sec": 0.010,
            "description": "Warm 808-style sub-bass thud for heavy landings and hero reveals",
        },
        "ping": {
            "files": ["sfx/glass_ping.wav"],
            "default_volume": 0.74,
            "preroll_sec": 0.0,
            "description": "Harmonic crystal chime for verification badges and completed actions",
        },
        "riser": {
            "files": ["sfx/warm_riser.wav"],
            "default_volume": 0.68,
            "preroll_sec": 0.0,
            "description": "Warm filtered tension swell leading into a major transition or export",
        },
        "chord": {
            "files": ["sfx/analog_chord.wav"],
            "default_volume": 0.88,
            "preroll_sec": 0.0,
            "description": "Lush detuned minor-9th chord hit for hero reveals and finale resolution",
        },
        "swell": {
            "files": ["sfx/harmonic_swell.wav"],
            "default_volume": 0.78,
            "preroll_sec": 0.040,
            "description": "Airy E4+E5 harmonic reveal swell for rack-focus locks and card expansions",
        },
        "glint": {
            "files": ["sfx/crystal_glint.wav"],
            "default_volume": 0.72,
            "preroll_sec": 0.0,
            "description": "Silky glass sparkle & high air tap for tile bops and pill stretches",
        },
        "bloom": {
            "files": ["sfx/bloom_chime.wav"],
            "default_volume": 0.82,
            "preroll_sec": 0.020,
            "description": "Radiant C6+E5 harmonic bloom burst for portal resolution transitions",
        },
        "portal": {
            "files": ["sfx/portal_drop.wav"],
            "default_volume": 0.86,
            "preroll_sec": 0.015,
            "description": "Velvety Light-to-Dark sub-bass sink with warm air sweep",
        },
    },
}


def build_sfx_pack(out_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Generate all tactile WAV assets and catalog.json into out_dir."""
    target = Path(out_dir) if out_dir is not None else DEFAULT_OUT_DIR
    target.mkdir(parents=True, exist_ok=True)

    generators: dict[str, np.ndarray] = {
        "key_clack_01.wav": _synth_key_clack(0.96, 101),
        "key_clack_02.wav": _synth_key_clack(1.00, 102),
        "key_clack_03.wav": _synth_key_clack(1.05, 103),
        "ui_tap.wav": _synth_ui_tap(),
        "switch_latch.wav": _synth_switch_latch(),
        "scrubber_tick.wav": _synth_scrubber_tick(),
        "air_swish_fast.wav": _synth_air_swish_fast(),
        "air_whoosh_deep.wav": _synth_air_whoosh_deep(),
        "sub_impact.wav": _synth_sub_impact(),
        "glass_ping.wav": _synth_glass_ping(),
        "warm_riser.wav": _synth_warm_riser(),
        "analog_chord.wav": _synth_analog_chord(),
        "harmonic_swell.wav": _synth_harmonic_swell(),
        "crystal_glint.wav": _synth_crystal_glint(),
        "bloom_chime.wav": _synth_bloom_chime(),
        "portal_drop.wav": _synth_portal_drop(),
        "bgm_groove.wav": _synth_bgm_groove(),
        "bgm_ambient.wav": _synth_bgm_ambient(),
    }

    written: list[str] = []
    for filename, samples in generators.items():
        wav_path = target / filename
        _write_wav(wav_path, samples)
        written.append(str(wav_path))

    catalog_path = target / "catalog.json"
    catalog_path.write_text(json.dumps(CATALOG_SPEC, indent=2) + "\n", encoding="utf-8")
    return {"out_dir": str(target), "files": written, "catalog": str(catalog_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the bundled kinearc tactile SFX & BGM pack.")
    parser.add_argument("--out_dir", default=str(DEFAULT_OUT_DIR), help="Destination directory for WAVs and catalog.json")
    args = parser.parse_args(argv)
    res = build_sfx_pack(args.out_dir)
    print(f"[build_sfx_pack] Generated {len(res['files'])} audio files -> {res['out_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
