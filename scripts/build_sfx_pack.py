#!/usr/bin/env python3
"""
build_sfx_pack.py — Physical-Modeled Organic Foley & Acoustic BGM Generator for kinearc.

Replaces raw sine-wave synthesis with inharmonic modal resonators (walnut/ceramic/glass
body modes excited by damped contact transients), overlap-add time-varying resonant
Doppler sweeps (linen/silk/wind motion), Karplus-Strong waveguide strings/bars (felt piano,
marimba, Rhodes tines), and stereo early-reflection acoustics across 3 selectable styles:
  - tactile-wood  (default): Warm desk foley, linen swishes, marimba & felt piano pocket
  - crisp-glass            : Matte ceramic clicks, crystal bars, silk sweeps & suitcase Rhodes
  - cinematic-sub          : Weighted leather latches, wide wind air, tape analog poly & sub
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
VALID_STYLES = ("tactile-wood", "crisp-glass", "cinematic-sub", "airy-clean")


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(samples, dtype=np.float64)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"Non-finite audio sample detected while writing {path}")
    if arr.ndim == 1:
        arr = np.column_stack((arr, arr))
    peak = float(np.max(np.abs(arr))) if arr.size else 1.0
    if peak > 0.96:
        arr = arr * (0.94 / peak)
    pcm = np.clip(arr * 32767.0, -32767.0, 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def _pink_noise(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    scale = 1.0 / np.maximum(np.sqrt(freqs), 1.0)
    scale[0] = 0.0
    pink = np.fft.irfft(np.fft.rfft(white) * scale, n=n)
    mx = float(np.max(np.abs(pink))) or 1.0
    return pink / mx


def _brown_noise(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    scale = 1.0 / np.maximum(freqs, 12.0)
    scale[0] = 0.0
    br = np.fft.irfft(np.fft.rfft(white) * scale, n=n)
    mx = float(np.max(np.abs(br))) or 1.0
    return br / mx


def _bandpass_fft(sig: np.ndarray, f_low: float, f_high: float) -> np.ndarray:
    n = len(sig)
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    center = 0.5 * (f_low + f_high)
    bw = max(40.0, f_high - f_low)
    gain = np.exp(-0.5 * ((freqs - center) / (bw * 0.48)) ** 2)
    out = np.fft.irfft(np.fft.rfft(sig) * gain, n=n)
    mx = float(np.max(np.abs(out))) or 1.0
    return out / mx


def _lowpass_fft(sig: np.ndarray, cutoff_hz: float, slope: float = 2.0) -> np.ndarray:
    n = len(sig)
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    gain = 1.0 / (1.0 + (freqs / max(30.0, cutoff_hz)) ** (2.0 * slope))
    return np.fft.irfft(np.fft.rfft(sig) * gain, n=n)


def _sweep_bandpass_ola(
    sig: np.ndarray,
    f_curve: np.ndarray,
    bw_ratio: float = 0.55,
) -> np.ndarray:
    """Overlap-add time-varying resonant filter producing authentic Doppler/cloth air sweeps."""
    n = len(sig)
    win_len = 512
    hop = 128
    hann = np.hanning(win_len)
    padded = np.pad(sig, (win_len // 2, win_len))
    n_frames = max(1, (n + win_len // 2) // hop)
    starts = np.arange(n_frames) * hop
    idx = starts[:, None] + np.arange(win_len)[None, :]
    frames = padded[idx] * hann[None, :]

    center_times = np.clip(starts, 0, n - 1)
    centers = f_curve[center_times][:, None]
    bws = np.maximum(65.0, centers * bw_ratio)
    freqs = np.fft.rfftfreq(win_len, d=1.0 / SAMPLE_RATE)[None, :]
    resp = np.exp(-0.5 * ((freqs - centers) / (bws * 0.5)) ** 2)
    filt_frames = np.fft.irfft(np.fft.rfft(frames, axis=-1) * resp, n=win_len, axis=-1) * hann[None, :]

    out = np.zeros(len(padded), dtype=np.float64)
    norm = np.zeros(len(padded), dtype=np.float64)
    h2 = hann * hann
    for k, st in enumerate(starts):
        out[st : st + win_len] += filt_frames[k]
        norm[st : st + win_len] += h2
    res = out[win_len // 2 : win_len // 2 + n] / np.maximum(norm[win_len // 2 : win_len // 2 + n], 1e-6)
    mx = float(np.max(np.abs(res))) or 1.0
    return res / mx


def _modal_body(
    dur: float,
    modes: list[tuple[float, float, float]],
    exc_lo: float,
    exc_hi: float,
    exc_ms: float,
    pitch_mult: float,
    seed: int,
    stereo_width: float = 0.012,
) -> np.ndarray:
    """Physical modal strike: nonlinear noise impulse exciting damped inharmonic body modes."""
    n = max(64, int(SAMPLE_RATE * dur))
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    raw = _pink_noise(n, seed)
    contact = _bandpass_fft(raw, exc_lo * pitch_mult, exc_hi * pitch_mult)
    exc_env = (1.0 - np.exp(-t / 0.0004)) * np.exp(-t / max(0.0006, exc_ms * 0.001))
    exc_sig = np.tanh(contact * 2.2) * exc_env

    # Short modal impulse response excited via FFT convolution with natural mallet noise
    ir_l = np.zeros(n, dtype=np.float64)
    ir_r = np.zeros(n, dtype=np.float64)
    rng = np.random.default_rng(seed + 17)
    for freq_hz, decay_s, amp in modes:
        ph0 = float(rng.uniform(0.0, 2.0 * np.pi))
        fl = freq_hz * pitch_mult * (1.0 - stereo_width * 0.5)
        fr = freq_hz * pitch_mult * (1.0 + stereo_width * 0.5)
        env = np.exp(-t / max(0.002, decay_s))
        ir_l += amp * np.sin(2.0 * np.pi * fl * t + ph0) * env
        ir_r += amp * np.sin(2.0 * np.pi * fr * t + ph0 + 0.14) * env

    nfft = 1 << (2 * n - 1).bit_length()
    ex_spec = np.fft.rfft(exc_sig, n=nfft)
    res_l = np.fft.irfft(ex_spec * np.fft.rfft(ir_l, n=nfft), n=nfft)[:n]
    res_r = np.fft.irfft(ex_spec * np.fft.rfft(ir_r, n=nfft), n=nfft)[:n]

    # Blend subtle dry contact snap so transient isn't overly smeared
    dry_snap = exc_sig * 0.28
    mx = max(float(np.max(np.abs(res_l))), float(np.max(np.abs(res_r))), 1e-6)
    res_l = (res_l / mx) * 0.85 + dry_snap
    res_r = (res_r / mx) * 0.85 + dry_snap * 0.92
    return np.column_stack((res_l, res_r))


def _early_stereo_room(sig: np.ndarray, room_amt: float, seed: int, damp_hz: float = 4200.0) -> np.ndarray:
    """Apply subtle asymmetric acoustic reflections so every WAV sits in a real physical space."""
    arr = np.column_stack((sig, sig)) if sig.ndim == 1 else sig.copy()
    if room_amt <= 1e-4:
        return arr
    n = len(arr)
    ir_len = int(0.085 * SAMPLE_RATE)
    ir = np.zeros((ir_len, 2), dtype=np.float64)
    ir[0, 0] = 1.0
    ir[0, 1] = 1.0
    rng = np.random.default_rng(seed + 91)
    for ms, lg, rg in ((5.5, 0.22, 0.11), (11.2, 0.10, 0.20), (19.8, 0.14, 0.08), (29.4, 0.06, 0.11)):
        idx = int(ms * 0.001 * SAMPLE_RATE)
        if idx < ir_len:
            ir[idx, 0] += lg * room_amt
            ir[idx, 1] += rg * room_amt
    # Velvet micro-diffusion
    diff_start = int(0.014 * SAMPLE_RATE)
    t_d = np.arange(ir_len - diff_start, dtype=np.float64) / SAMPLE_RATE
    for ch in range(2):
        ir[diff_start:, ch] += rng.choice([-1.0, 0.0, 0.0, 1.0], size=len(t_d)) * np.exp(-t_d / 0.022) * 0.09 * room_amt
    ir[:, 0] = _lowpass_fft(ir[:, 0], damp_hz, slope=1.5)
    ir[:, 1] = _lowpass_fft(ir[:, 1], damp_hz, slope=1.5)

    nfft = 1 << (n + ir_len - 1).bit_length()
    out = np.empty((n, 2), dtype=np.float64)
    for ch in range(2):
        out[:, ch] = np.fft.irfft(np.fft.rfft(arr[:, ch], n=nfft) * np.fft.rfft(ir[:, ch], n=nfft), n=nfft)[:n]
    return out


def _sculpt_airy_clean(
    sig: np.ndarray,
    *,
    mud_scoop: float = 0.72,
    air_lift: float = 1.85,
    sub_keep: float = 1.0,
    side_max: float = 0.44,
) -> np.ndarray:
    """Carve boxy 100-260Hz mud, preserve <85Hz sub, lift 4-16kHz sparkle air & focus stereo core."""
    arr = np.column_stack((sig, sig)) if sig.ndim == 1 else sig.copy()
    n = len(arr)
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)

    # Scoop mid-low boxiness cleanly around 165 Hz while keeping sub <85 Hz intact
    mud_dip = 1.0 - mud_scoop * np.exp(-0.5 * ((freqs - 165.0) / 72.0) ** 2)
    # Silky presence & air shelf from 3.5 kHz -> 16 kHz, soft taper above 18.5 kHz
    air_curve = 1.0 + (air_lift - 1.0) * (1.0 / (1.0 + np.exp(-(freqs - 4200.0) / 1400.0)))
    hi_taper = 1.0 / (1.0 + (freqs / 18500.0) ** 4)
    sub_boost = 1.0 + (sub_keep - 1.0) * np.exp(-0.5 * (freqs / 72.0) ** 2)
    eq = np.maximum(0.18, mud_dip) * air_curve * hi_taper * sub_boost

    out = np.empty_like(arr)
    for ch in range(2):
        out[:, ch] = np.fft.irfft(np.fft.rfft(arr[:, ch]) * eq, n=n)

    # Keep focused mid core so headphone localization feels crisp instead of hollow/phasey
    mid = 0.5 * (out[:, 0] + out[:, 1])
    side = 0.5 * (out[:, 0] - out[:, 1])
    m_rms = float(np.sqrt(np.mean(mid ** 2))) + 1e-9
    s_rms = float(np.sqrt(np.mean(side ** 2))) + 1e-9
    if s_rms > m_rms * side_max:
        side *= (m_rms * side_max) / s_rms
    return np.column_stack((mid + side, mid - side))


def _tape_saturate(sig: np.ndarray, drive: float = 1.22, cutoff_hz: float = 12500.0) -> np.ndarray:
    arr = np.column_stack((sig, sig)) if sig.ndim == 1 else sig.copy()
    warm = np.tanh(arr * drive + 0.035 * (arr ** 2))
    out = np.empty_like(warm)
    for ch in range(2):
        out[:, ch] = _lowpass_fft(warm[:, ch], cutoff_hz, slope=1.4)
    return out


def _karplus_note(
    freq: float,
    dur: float,
    brightness: float,
    decay_factor: float,
    seed: int,
    felt_thump: float = 0.22,
) -> np.ndarray:
    """Physical waveguide string/bar/tine generator with felt hammer strike & stiffness."""
    n = max(128, int(SAMPLE_RATE * dur))
    delay_n = max(4, int(round(SAMPLE_RATE / max(28.0, freq))))
    rng = np.random.default_rng(seed)

    # Felt-damped white/pink noise excitation scaled to hammer hardness (brightness)
    exc = _lowpass_fft(rng.standard_normal(delay_n + 16), 900.0 + 4800.0 * brightness, slope=1.2)
    exc = exc[:delay_n]
    buf = list(float(x) for x in exc)
    out = np.zeros(n, dtype=np.float64)
    b = 0.50 * (0.25 + 0.72 * brightness)
    inv_b = 1.0 - b
    g = min(0.9992, max(0.92, decay_factor))
    pos = 0
    prev = 0.0
    for i in range(n):
        cur = buf[pos]
        out[i] = cur
        nxt = g * (inv_b * cur + b * prev)
        buf[pos] = nxt
        prev = cur
        pos = (pos + 1) % delay_n

    # Organic hammer thump at attack (real upright felt / wood mallet body)
    if felt_thump > 1e-3:
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        hammer = _bandpass_fft(_pink_noise(n, seed + 5), 110.0, 520.0) * np.exp(-t / 0.0085) * felt_thump
        out += hammer
    mx = float(np.max(np.abs(out))) or 1.0
    fade = min(n, int(0.012 * SAMPLE_RATE))
    out[-fade:] *= np.linspace(1.0, 0.0, fade)
    return out / mx


# ---------------------------------------------------------------------------
# Style-Parameterized Acoustic Generators
# ---------------------------------------------------------------------------

def _synth_ui_tap(style: str, variant: int) -> np.ndarray:
    pm = (0.95, 1.00, 1.06)[variant % 3]
    seed = 200 + variant * 19
    if style == "airy-clean":
        # Tactile glass water-droplet pop + crisp 6-15kHz capacitive spark
        dur = 0.048
        n = int(SAMPLE_RATE * dur)
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        f_drop = (340.0 * pm) + (540.0 * pm) * (1.0 - np.exp(-t / 0.0045))
        ph = np.cumsum(2.0 * np.pi * f_drop / SAMPLE_RATE)
        pop = np.sin(ph) * (1.0 - np.exp(-t / 0.0005)) * np.exp(-t / 0.0065) * 0.72
        spark_air = _bandpass_fft(_pink_noise(n, seed + 50), 4500.0 * pm, 15500.0) * (1.0 - np.exp(-t / 0.0003)) * np.exp(-t / 0.0028) * 0.58
        rim = _modal_body(dur, [(1880.0, 0.006, 0.36), (5200.0, 0.0025, 0.34)], 2800.0, 14500.0, 0.9, pm, seed, stereo_width=0.004)
        stereo = np.column_stack((pop + spark_air, pop + spark_air * 0.96)) * 0.76 + rim * 0.42
        return _sculpt_airy_clean(_early_stereo_room(stereo, 0.16, seed, damp_hz=15500.0), mud_scoop=0.78, air_lift=1.95) * 0.84
    if style == "airy-clean":
        # Tactile glass water-droplet pop + crisp 6-15kHz capacitive spark
        dur = 0.048
        n = int(SAMPLE_RATE * dur)
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        f_drop = (340.0 * pm) + (540.0 * pm) * (1.0 - np.exp(-t / 0.0045))
        ph = np.cumsum(2.0 * np.pi * f_drop / SAMPLE_RATE)
        pop = np.sin(ph) * (1.0 - np.exp(-t / 0.0005)) * np.exp(-t / 0.0065) * 0.72
        spark_air = _bandpass_fft(_pink_noise(n, seed + 50), 4500.0 * pm, 15500.0) * (1.0 - np.exp(-t / 0.0003)) * np.exp(-t / 0.0028) * 0.58
        rim = _modal_body(dur, [(1880.0, 0.006, 0.36), (5200.0, 0.0025, 0.34)], 2800.0, 14500.0, 0.9, pm, seed, stereo_width=0.004)
        stereo = np.column_stack((pop + spark_air, pop + spark_air * 0.96)) * 0.76 + rim * 0.42
        return _sculpt_airy_clean(_early_stereo_room(stereo, 0.16, seed, damp_hz=15500.0), mud_scoop=0.78, air_lift=1.95) * 0.84
    if style == "tactile-wood":
        # Damped walnut desk wood/ceramic micro-contact
        modes = [(275.0, 0.016, 1.0), (545.0, 0.009, 0.58), (1180.0, 0.0045, 0.34), (2140.0, 0.0022, 0.16)]
        body = _modal_body(0.068, modes, 320.0, 2200.0, 2.2, pm, seed, stereo_width=0.025)
        return _tape_saturate(_early_stereo_room(body, 0.55, seed), drive=1.18, cutoff_hz=7800.0) * 0.84
    if style == "crisp-glass":
        # Tight frosted ceramic & precision shutter micro-click
        modes = [(520.0, 0.013, 0.90), (1380.0, 0.008, 0.62), (3120.0, 0.0038, 0.38)]
        body = _modal_body(0.058, modes, 700.0, 4400.0, 1.4, pm, seed + 100, stereo_width=0.022)
        return _tape_saturate(_early_stereo_room(body, 0.45, seed), drive=1.12, cutoff_hz=11500.0) * 0.82
    # cinematic-sub: weighted soft-touch pad press
    modes = [(165.0, 0.024, 1.0), (340.0, 0.012, 0.52), (890.0, 0.004, 0.24)]
    body = _modal_body(0.082, modes, 180.0, 1450.0, 3.1, pm, seed + 200, stereo_width=0.03)
    return _tape_saturate(_early_stereo_room(body, 0.65, seed), drive=1.32, cutoff_hz=6400.0) * 0.86


def _synth_key_clack(style: str, variant: int) -> np.ndarray:
    pm = (0.94, 1.00, 1.06)[variant % 3]
    seed = 101 + variant * 13
    dur = 0.092
    n = int(SAMPLE_RATE * dur)
    if style == "airy-clean":
        # Silky low-profile tactile key-tick: damped 230Hz soft matte thud + airy 4.5-15kHz keycap click (no ringy cavity)
        n_ac = int(SAMPLE_RATE * 0.044)
        t_ac = np.arange(n_ac, dtype=np.float64) / SAMPLE_RATE
        stem_air = _bandpass_fft(_pink_noise(n_ac, seed + 22), 4200.0, 15500.0) * (1.0 - np.exp(-t_ac / 0.0003)) * np.exp(-t_ac / 0.0018) * 0.72
        thud = np.sin(2.0 * np.pi * (230.0 * pm) * t_ac) * np.exp(-t_ac / 0.0038) * 0.42
        cav_air = _bandpass_fft(_pink_noise(n_ac, seed + 7), 1600.0, 5200.0) * np.exp(-t_ac / 0.0025) * 0.34
        sb = int(0.005 * SAMPLE_RATE)
        l = stem_air * 0.75 + thud * 0.65
        r = stem_air * 0.71 + thud * 0.65
        l[sb:] += cav_air[: n_ac - sb] * 0.55
        r[sb:] += cav_air[: n_ac - sb] * 0.52
        return _sculpt_airy_clean(_early_stereo_room(np.column_stack((l, r)), 0.12, seed, damp_hz=15500.0), mud_scoop=0.85, air_lift=2.15, sub_keep=0.75) * 0.80
    if style == "crisp-glass":
        stem_modes = [(1480.0, 0.006, 0.52), (3340.0, 0.0032, 0.38)]
        cav_modes = [(310.0, 0.018, 0.95), (690.0, 0.011, 0.52), (1240.0, 0.005, 0.25)]
    elif style == "cinematic-sub":
        stem_modes = [(860.0, 0.007, 0.44), (2180.0, 0.003, 0.26)]
        cav_modes = [(210.0, 0.024, 1.0), (470.0, 0.014, 0.54), (920.0, 0.006, 0.22)]
    else:  # tactile-wood PBT thock on oiled wood desk
        stem_modes = [(1120.0, 0.006, 0.48), (2640.0, 0.0028, 0.30)]
        cav_modes = [(255.0, 0.020, 1.0), (585.0, 0.011, 0.55), (1080.0, 0.005, 0.24)]

    stem = _modal_body(dur, stem_modes, 900.0, 4200.0, 1.8, pm, seed, stereo_width=0.018)
    cav = _modal_body(dur, cav_modes, 240.0, 1500.0, 2.8, pm, seed + 7, stereo_width=0.022)
    rel = _modal_body(dur, [(1650.0, 0.004, 0.32), (820.0, 0.006, 0.24)], 700.0, 2800.0, 1.4, pm, seed + 19)

    shift_bot = int(0.0085 * SAMPLE_RATE)
    shift_rel = int(0.044 * SAMPLE_RATE)
    sig = stem * 0.58
    sig[shift_bot:] += cav[: n - shift_bot] * 0.88
    sig[shift_rel:] += rel[: n - shift_rel] * 0.24
    return _tape_saturate(_early_stereo_room(sig, 0.48, seed), drive=1.24, cutoff_hz=9200.0) * 0.85


def _synth_scrubber_tick(style: str, variant: int) -> np.ndarray:
    pm = (0.96, 1.04)[variant % 2]
    seed = 310 + variant * 17
    if style == "airy-clean":
        n_sc = int(SAMPLE_RATE * 0.022)
        t_sc = np.arange(n_sc, dtype=np.float64) / SAMPLE_RATE
        air_tick = _bandpass_fft(_pink_noise(n_sc, seed), 5200.0 * pm, 15500.0) * np.exp(-t_sc / 0.0014) * 0.72
        micro_body = np.sin(2.0 * np.pi * (820.0 * pm) * t_sc) * np.exp(-t_sc / 0.0020) * 0.35
        stereo = np.column_stack((air_tick + micro_body, air_tick * 0.94 + micro_body))
        return _sculpt_airy_clean(_early_stereo_room(stereo, 0.10, seed, damp_hz=16000.0), mud_scoop=0.84, air_lift=2.15, sub_keep=0.75) * 0.74
    if style == "crisp-glass":
        modes = [(1180.0, 0.006, 0.72), (2890.0, 0.003, 0.42)]
        body = _modal_body(0.036, modes, 1100.0, 5200.0, 1.0, pm, seed)
        return _tape_saturate(_early_stereo_room(body, 0.35, seed), drive=1.15, cutoff_hz=11000.0) * 0.76
    modes = [(460.0, 0.007, 0.85), (1040.0, 0.004, 0.48), (1960.0, 0.0022, 0.22)]
    body = _modal_body(0.040, modes, 480.0, 2800.0, 1.3, pm, seed)
    return _tape_saturate(_early_stereo_room(body, 0.42, seed), drive=1.22, cutoff_hz=7200.0) * 0.78


def _synth_switch_latch(style: str, variant: int) -> np.ndarray:
    pm = (0.98, 1.03)[variant % 2]
    seed = 410 + variant * 29
    dur = 0.135
    n = int(SAMPLE_RATE * dur)
    if style == "airy-clean":
        pre = _modal_body(dur, [(2200.0, 0.004, 0.58), (6200.0, 0.0022, 0.44)], 2200.0, 14500.0, 1.0, pm, seed, stereo_width=0.004)
        lock = _modal_body(dur, [(340.0, 0.016, 0.78), (1180.0, 0.009, 0.52), (4200.0, 0.0035, 0.36)], 500.0, 14000.0, 1.5, pm, seed + 5, stereo_width=0.004)
        off = int(0.019 * SAMPLE_RATE)
        mix = pre * 0.58
        mix[off:] += lock[: n - off] * 0.90
        return _sculpt_airy_clean(_early_stereo_room(mix, 0.18, seed, damp_hz=15500.0), mud_scoop=0.78, air_lift=1.95) * 0.84
    if style == "crisp-glass":
        pre = _modal_body(dur, [(980.0, 0.005, 0.6), (2420.0, 0.003, 0.35)], 900.0, 4000.0, 1.3, pm, seed)
        lock = _modal_body(dur, [(295.0, 0.022, 0.95), (760.0, 0.012, 0.58), (1920.0, 0.005, 0.32)], 300.0, 3200.0, 2.2, pm, seed + 5)
    elif style == "cinematic-sub":
        pre = _modal_body(dur, [(540.0, 0.006, 0.55), (1320.0, 0.003, 0.25)], 450.0, 2200.0, 1.8, pm, seed)
        lock = _modal_body(dur, [(135.0, 0.032, 1.0), (310.0, 0.018, 0.62), (790.0, 0.007, 0.28)], 140.0, 1800.0, 3.0, pm, seed + 5)
    else:  # tactile-wood: walnut/brass magnetic lock
        pre = _modal_body(dur, [(720.0, 0.0055, 0.58), (1780.0, 0.003, 0.32)], 600.0, 2900.0, 1.5, pm, seed)
        lock = _modal_body(dur, [(220.0, 0.024, 1.0), (510.0, 0.013, 0.56), (1260.0, 0.005, 0.28)], 220.0, 2300.0, 2.5, pm, seed + 5)

    offset = int(0.022 * SAMPLE_RATE)
    mix = pre * 0.56
    mix[offset:] += lock[: n - offset] * 0.92
    return _tape_saturate(_early_stereo_room(mix, 0.55, seed), drive=1.24, cutoff_hz=8600.0) * 0.86


def _synth_air_swish(style: str, deep: bool, variant: int) -> np.ndarray:
    seed = (520 if deep else 480) + variant * 31
    if style == "airy-clean":
        if deep:
            dur = 0.44
            n = int(SAMPLE_RATE * dur)
            u = np.arange(n, dtype=np.float64) / SAMPLE_RATE / dur
            env = (np.sin(np.pi * u) ** 1.75) * np.exp(-np.maximum(0.0, u - 0.55) * 1.4)
            f_curve = 320.0 + 3600.0 * (np.sin(np.pi * u) ** 1.3)
            raw = _pink_noise(n, seed)
            a_l = _sweep_bandpass_ola(raw, f_curve, bw_ratio=0.65)
            a_r = _sweep_bandpass_ola(_pink_noise(n, seed + 1), f_curve * 1.02, bw_ratio=0.65)
            silk = _bandpass_fft(_pink_noise(n, seed + 7), 4500.0, 14500.0) * (np.sin(np.pi * u) ** 2.0) * 0.28
            sub_p = np.sin(np.cumsum(2.0 * np.pi * (42.0 + 52.0 * np.sin(np.pi * u)) / SAMPLE_RATE)) * (np.sin(np.pi * u) ** 2.3) * 0.42
            stereo = np.column_stack((a_l * env + silk + sub_p, a_r * env + silk * 0.95 + sub_p))
            return _sculpt_airy_clean(_early_stereo_room(stereo, 0.20, seed, damp_hz=15500.0), mud_scoop=0.84, air_lift=2.10, sub_keep=1.18) * 0.84
        dur = 0.22
        n = int(SAMPLE_RATE * dur)
        u = np.arange(n, dtype=np.float64) / SAMPLE_RATE / dur
        env = (u ** 0.65) * ((1.0 - u) ** 1.40) * 3.1
        f_curve = 700.0 + 6800.0 * (np.sin(np.pi * (u ** 0.85)) ** 1.2)
        a_l = _sweep_bandpass_ola(_pink_noise(n, seed), f_curve, bw_ratio=0.58)
        a_r = _sweep_bandpass_ola(_pink_noise(n, seed + 1), f_curve * 1.02, bw_ratio=0.58)
        silk = _bandpass_fft(_pink_noise(n, seed + 9), 5200.0, 15500.0) * env * 0.34
        stereo = np.column_stack((a_l * env + silk, a_r * env + silk * 0.96))
        return _sculpt_airy_clean(_early_stereo_room(stereo, 0.16, seed, damp_hz=16000.0), mud_scoop=0.85, air_lift=2.15) * 0.84

    if deep:
        dur = 0.46 if style != "cinematic-sub" else 0.54
        n = int(SAMPLE_RATE * dur)
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        u = t / dur
        env = (np.sin(np.pi * u) ** 1.75) * np.exp(-np.maximum(0.0, u - 0.55) * 1.4)
        f_hi = 880.0 if style == "tactile-wood" else (1180.0 if style == "crisp-glass" else 720.0)
        f_curve = 115.0 + f_hi * (np.sin(np.pi * u) ** 1.45)
        bw = 0.65
    else:
        dur = 0.24
        n = int(SAMPLE_RATE * dur)
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        u = t / dur
        env = (u ** 0.7) * ((1.0 - u) ** 1.35) * 3.1
        f_hi = 1750.0 if style == "tactile-wood" else (2650.0 if style == "crisp-glass" else 1350.0)
        f_curve = 240.0 + f_hi * (np.sin(np.pi * (u ** 0.85)) ** 1.25)
        bw = 0.52

    air_l = _sweep_bandpass_ola(_pink_noise(n, seed) * 0.7 + _brown_noise(n, seed + 1) * 0.3, f_curve, bw_ratio=bw)
    air_r = _sweep_bandpass_ola(_pink_noise(n, seed + 2) * 0.7 + _brown_noise(n, seed + 3) * 0.3, f_curve * 1.04, bw_ratio=bw)

    pan_l = np.clip(1.05 - 0.32 * u, 0.72, 1.0)
    pan_r = np.clip(0.73 + 0.32 * u, 0.72, 1.0)
    sig_l = air_l * env * pan_l
    sig_r = air_r * env * pan_r
    if deep:
        sub_f = 48.0 + 62.0 * np.sin(np.pi * u)
        sub_env = (np.sin(np.pi * u) ** 2.2) * (0.28 if style == "crisp-glass" else 0.44)
        sub_l = _bandpass_fft(_brown_noise(n, seed + 9), 50.0, 140.0) * sub_env * 0.65
        sub_p = np.sin(np.cumsum(2.0 * np.pi * sub_f / SAMPLE_RATE)) * sub_env * 0.55
        sig_l += sub_l + sub_p
        sig_r += sub_l + sub_p
    stereo = np.column_stack((sig_l, sig_r))
    return _tape_saturate(_early_stereo_room(stereo, 0.52, seed), drive=1.18, cutoff_hz=9600.0) * 0.84


def _synth_sub_impact(style: str, portal: bool = False) -> np.ndarray:
    dur = 0.64 if portal else 0.50
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    u = t / dur
    seed = 615 if portal else 605

    if style == "airy-clean":
        # Balanced <82Hz sub anchor drop + prominent silk 4-15kHz shimmer breath (keeps sub from overpowering mix)
        f_drop = 39.0 + 72.0 * np.exp(-t / (0.045 if portal else 0.020))
        ph = np.cumsum(2.0 * np.pi * f_drop / SAMPLE_RATE)
        body_env = (1.0 - np.exp(-t / (0.009 if portal else 0.003))) * np.exp(-t / (0.19 if portal else 0.12))
        sub = np.sin(ph) * body_env * 0.52
        silk_air = _bandpass_fft(_pink_noise(n, seed + 3), 3800.0, 15500.0) * (1.0 - np.exp(-t / 0.002)) * np.exp(-t / (0.20 if portal else 0.05)) * (0.48 if portal else 0.36)
        if portal:
            sw = _sweep_bandpass_ola(_pink_noise(n, seed + 9), 5800.0 * np.exp(-u * 1.35) + 750.0, bw_ratio=0.75) * (np.sin(np.pi * u) ** 1.4) * 0.44
            silk_air += sw
        stereo = np.column_stack((sub + silk_air, sub + silk_air * 0.94))
        return _sculpt_airy_clean(_early_stereo_room(stereo, 0.18, seed, damp_hz=15800.0), mud_scoop=0.88, air_lift=2.35, sub_keep=0.74) * 0.84

    f_low = 38.0 if style == "cinematic-sub" else 44.0
    f_drop = (f_low + 96.0 * np.exp(-t / (0.052 if portal else 0.028)))
    ph = np.cumsum(2.0 * np.pi * f_drop / SAMPLE_RATE)
    body_env = (1.0 - np.exp(-t / (0.011 if portal else 0.0035))) * np.exp(-t / (0.22 if portal else 0.145))
    sub = (np.sin(ph) + 0.18 * np.sin(2.0 * ph) * np.exp(-t / 0.06)) * body_env

    skin_modes = [(95.0, 0.045, 0.75), (168.0, 0.025, 0.45), (340.0, 0.012, 0.22)]
    skin = _modal_body(dur, skin_modes, 90.0, 680.0, 4.0, 1.0, seed, stereo_width=0.02)

    air_rush = np.zeros((n, 2), dtype=np.float64)
    if portal:
        f_air = 620.0 * np.exp(-u * 1.9) + 120.0
        a_l = _sweep_bandpass_ola(_pink_noise(n, seed + 3), f_air, bw_ratio=0.7) * (np.sin(np.pi * u) ** 1.5)
        a_r = _sweep_bandpass_ola(_pink_noise(n, seed + 4), f_air * 1.03, bw_ratio=0.7) * (np.sin(np.pi * u) ** 1.5)
        air_rush = np.column_stack((a_l, a_r)) * 0.34

    mix = np.column_stack((sub, sub)) * 0.78 + skin * 0.36 + air_rush
    return _tape_saturate(_early_stereo_room(mix, 0.48, seed), drive=1.28, cutoff_hz=6800.0) * 0.88


def _synth_crystal_glint(style: str, variant: int) -> np.ndarray:
    pm = (0.98, 1.03)[variant % 2]
    seed = 710 + variant * 23
    dur = 0.20
    if style == "airy-clean":
        # Ascending crystal dewdrop chime + luminous 6-15.5kHz air sparkle
        n = int(SAMPLE_RATE * dur)
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        p1 = _karplus_note(1975.53 * pm, dur, 0.84, 0.9965, seed, felt_thump=0.02)
        p2 = _karplus_note(2959.96 * pm, dur, 0.88, 0.9960, seed + 3, felt_thump=0.02)
        sh = int(0.018 * SAMPLE_RATE)
        air_dust = _bandpass_fft(_pink_noise(n, seed + 17), 5500.0, 15800.0) * (1.0 - np.exp(-t / 0.0015)) * np.exp(-t / 0.042) * 0.34
        l = p1 * 0.62 + air_dust
        r = p1 * 0.58 + air_dust * 0.95
        l[sh:] += p2[: n - sh] * 0.44
        r[sh:] += p2[: n - sh] * 0.48
        return _sculpt_airy_clean(_early_stereo_room(np.column_stack((l, r)), 0.24, seed, damp_hz=16000.0), mud_scoop=0.82, air_lift=2.05) * 0.80
    if style == "tactile-wood":
        note1 = _karplus_note(1318.51 * pm, dur, 0.42, 0.996, seed, felt_thump=0.16)
        note2 = _karplus_note(1975.53 * pm, dur, 0.36, 0.994, seed + 3, felt_thump=0.08)
        bar = _modal_body(dur, [(659.25, 0.048, 0.55), (1815.0, 0.018, 0.32)], 600.0, 3200.0, 2.0, pm, seed)
        stereo = np.column_stack((note1 * 0.52 + note2 * 0.34, note1 * 0.46 + note2 * 0.40)) + bar * 0.38
        return _tape_saturate(_early_stereo_room(stereo, 0.72, seed), drive=1.14, cutoff_hz=9200.0) * 0.80
    if style == "crisp-glass":
        modes = [(1567.98, 0.046, 0.85), (4321.0, 0.018, 0.42), (784.0, 0.038, 0.38)]
        bar = _modal_body(dur, modes, 1200.0, 6200.0, 1.4, pm, seed, stereo_width=0.025)
        pl = _karplus_note(2349.32 * pm, dur, 0.58, 0.995, seed + 9, felt_thump=0.10)
        stereo = bar * 0.68 + np.column_stack((pl, np.roll(pl, 9))) * 0.32
        return _tape_saturate(_early_stereo_room(stereo, 0.78, seed), drive=1.10, cutoff_hz=12800.0) * 0.80
    pl = _karplus_note(1046.50 * pm, dur, 0.34, 0.996, seed, felt_thump=0.22)
    bar = _modal_body(dur, [(523.25, 0.055, 0.65), (1440.0, 0.020, 0.32)], 380.0, 2400.0, 2.5, pm, seed + 5)
    stereo = np.column_stack((pl, np.roll(pl, 11))) * 0.55 + bar * 0.45
    return _tape_saturate(_early_stereo_room(stereo, 0.75, seed), drive=1.20, cutoff_hz=8200.0) * 0.82


def _synth_glass_ping(style: str) -> np.ndarray:
    dur = 0.64
    seed = 760
    if style == "airy-clean":
        n = int(SAMPLE_RATE * dur)
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        b1 = _karplus_note(987.77, dur, 0.86, 0.9986, seed, felt_thump=0.02)
        b2 = _karplus_note(1479.98, dur, 0.88, 0.9984, seed + 4, felt_thump=0.02)
        b3 = _karplus_note(2959.96, dur, 0.90, 0.9970, seed + 8, felt_thump=0.01)
        sh = int(0.022 * SAMPLE_RATE)
        air = _bandpass_fft(_pink_noise(n, seed + 19), 5000.0, 15500.0) * (1.0 - np.exp(-t / 0.002)) * np.exp(-t / 0.085) * 0.24
        l = b1 * 0.55 + air
        r = b1 * 0.52 + air * 0.95
        l[sh:] += b2[: n - sh] * 0.42 + b3[: n - sh] * 0.22
        r[sh:] += b2[: n - sh] * 0.46 + b3[: n - sh] * 0.20
        return _sculpt_airy_clean(_early_stereo_room(np.column_stack((l, r)), 0.30, seed, damp_hz=15800.0), mud_scoop=0.80, air_lift=2.0) * 0.82
    if style == "tactile-wood":
        n1 = _karplus_note(880.0, dur, 0.45, 0.9984, seed, felt_thump=0.18)
        n2 = _karplus_note(1318.51, dur, 0.40, 0.9980, seed + 4, felt_thump=0.10)
        pad_shift = int(0.016 * SAMPLE_RATE)
        l = n1 * 0.68
        r = n1 * 0.60
        l[pad_shift:] += n2[: len(l) - pad_shift] * 0.46
        r[pad_shift:] += n2[: len(r) - pad_shift] * 0.54
        return _tape_saturate(_early_stereo_room(np.column_stack((l, r)), 0.85, seed), drive=1.14, cutoff_hz=9600.0) * 0.82
    if style == "crisp-glass":
        modes = [(1174.66, 0.19, 0.85), (3237.4, 0.065, 0.35), (1760.0, 0.15, 0.52)]
        bar = _modal_body(dur, modes, 900.0, 5200.0, 1.8, 1.0, seed, stereo_width=0.016)
        n1 = _karplus_note(1174.66, dur, 0.55, 0.9985, seed + 8, felt_thump=0.12)
        stereo = bar * 0.55 + np.column_stack((n1, np.roll(n1, 14))) * 0.45
        return _tape_saturate(_early_stereo_room(stereo, 0.90, seed), drive=1.10, cutoff_hz=12400.0) * 0.82
    n1 = _karplus_note(698.46, dur, 0.38, 0.9986, seed, felt_thump=0.20)
    n2 = _karplus_note(1046.50, dur, 0.35, 0.9982, seed + 6, felt_thump=0.12)
    stereo = np.column_stack((n1 * 0.62 + np.roll(n2, 220) * 0.44, np.roll(n1, 18) * 0.58 + n2 * 0.48))
    return _tape_saturate(_early_stereo_room(stereo, 0.85, seed), drive=1.22, cutoff_hz=8400.0) * 0.84


def _synth_harmonic_swell(style: str) -> np.ndarray:
    dur = 0.72
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    u = t / dur
    seed = 811
    swell_env = (np.sin(np.pi * u) ** 1.35) * np.exp(-t / 0.50)

    if style == "airy-clean":
        notes = [659.25, 987.77, 1318.51, 1975.53]
        l_acc = np.zeros(n, dtype=np.float64)
        r_acc = np.zeros(n, dtype=np.float64)
        for idx, f in enumerate(notes):
            w1 = _karplus_note(f * 0.9996, dur, 0.85, 0.9992, seed + idx * 5, felt_thump=0.0)
            w2 = _karplus_note(f * 1.0004, dur, 0.85, 0.9992, seed + idx * 5 + 1, felt_thump=0.0)
            l_acc += w1 * 0.25
            r_acc += w2 * 0.25
        # Soft breath fade-in so swell blooms smoothly rather than plucking at t=0
        breath_env = (np.sin(np.pi * u) ** 1.75) * (1.0 - np.exp(-t / 0.11)) * np.exp(-t / 0.55)
        air_f = 1800.0 + 6200.0 * np.sin(np.pi * u)
        air_l = _sweep_bandpass_ola(_pink_noise(n, seed + 30), air_f, bw_ratio=0.75) * 0.28
        air_r = _sweep_bandpass_ola(_pink_noise(n, seed + 31), air_f * 1.02, bw_ratio=0.75) * 0.28
        stereo = np.column_stack(((l_acc + air_l) * breath_env, (r_acc + air_r) * breath_env))
        return _sculpt_airy_clean(_early_stereo_room(stereo, 0.34, seed, damp_hz=15800.0), mud_scoop=0.82, air_lift=2.10, sub_keep=0.78) * 0.82

    if style == "crisp-glass":
        notes = [329.63, 493.88, 659.25]
        br = 0.52
    elif style == "cinematic-sub":
        notes = [220.00, 329.63, 440.00]
        br = 0.32
    else:
        notes = [329.63, 493.88, 659.25]
        br = 0.38

    l_acc = np.zeros(n, dtype=np.float64)
    r_acc = np.zeros(n, dtype=np.float64)
    for idx, f in enumerate(notes):
        w1 = _karplus_note(f * 0.999, dur, br, 0.9991, seed + idx * 5, felt_thump=0.12)
        w2 = _karplus_note(f * 1.001, dur, br, 0.9991, seed + idx * 5 + 1, felt_thump=0.10)
        l_acc += w1 * (0.42 if idx == 0 else 0.29)
        r_acc += w2 * (0.42 if idx == 0 else 0.29)

    air_f = 550.0 + 1800.0 * np.sin(np.pi * u)
    air_l = _sweep_bandpass_ola(_pink_noise(n, seed + 30), air_f, bw_ratio=0.75) * 0.14
    air_r = _sweep_bandpass_ola(_pink_noise(n, seed + 31), air_f * 1.04, bw_ratio=0.75) * 0.14
    stereo = np.column_stack(((l_acc * swell_env + air_l * swell_env), (r_acc * swell_env + air_r * swell_env)))
    return _tape_saturate(_early_stereo_room(stereo, 0.90, seed), drive=1.18, cutoff_hz=8800.0) * 0.84


def _synth_warm_riser(style: str) -> np.ndarray:
    dur = 0.88
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    u = t / dur
    seed = 707
    env = (u ** 2.15) * np.exp(-np.maximum(0.0, u - 0.90) / 0.032)
    if style == "airy-clean":
        f_curve = 650.0 + 8200.0 * (u ** 1.75)
        air_l = _sweep_bandpass_ola(_pink_noise(n, seed), f_curve, bw_ratio=0.45)
        air_r = _sweep_bandpass_ola(_pink_noise(n, seed + 1), f_curve * 1.02, bw_ratio=0.45)
        f_tone = 261.63 + 520.0 * (u ** 1.65)
        ph = np.cumsum(2.0 * np.pi * f_tone / SAMPLE_RATE)
        shimmer = (0.34 * np.sin(ph) + 0.22 * np.sin(2.0 * ph) + 0.16 * np.sin(4.0 * ph)) * 0.45
        stereo = np.column_stack(((air_l * 0.72 + shimmer) * env, (air_r * 0.72 + np.roll(shimmer, 6)) * env))
        return _sculpt_airy_clean(_early_stereo_room(stereo, 0.26, seed, damp_hz=15800.0), mud_scoop=0.84, air_lift=2.10) * 0.84

    f_end = 1850.0 if style == "tactile-wood" else (2800.0 if style == "crisp-glass" else 1350.0)
    f_curve = 180.0 + f_end * (u ** 1.85)
    air_l = _sweep_bandpass_ola(_pink_noise(n, seed), f_curve, bw_ratio=0.42)
    air_r = _sweep_bandpass_ola(_pink_noise(n, seed + 1), f_curve * 1.03, bw_ratio=0.42)

    f_tone = 146.83 + 220.0 * (u ** 1.65)
    ph = np.cumsum(2.0 * np.pi * f_tone / SAMPLE_RATE)
    reed = (0.42 * np.sin(ph) + 0.24 * np.sin(2.0 * ph) + 0.14 * np.sin(3.0 * ph)) * 0.55
    stereo = np.column_stack(((air_l * 0.62 + reed) * env, (air_r * 0.62 + np.roll(reed, 9)) * env))
    return _tape_saturate(_early_stereo_room(stereo, 0.72, seed), drive=1.20, cutoff_hz=9600.0) * 0.82


def _synth_analog_chord(style: str, bloom: bool = False) -> np.ndarray:
    dur = 1.05 if bloom else 1.35
    n = int(SAMPLE_RATE * dur)
    seed = 918 if bloom else 845
    if style == "airy-clean":
        # Luminous crystal celesta/harp Emaj9 shimmer + clean <80Hz root (no 160Hz clump)
        notes = [329.63, 493.88, 659.25, 987.77, 1318.51, 1975.53] if bloom else [246.94, 329.63, 493.88, 659.25, 987.77, 1479.98]
        l_acc = np.zeros(n, dtype=np.float64)
        r_acc = np.zeros(n, dtype=np.float64)
        for idx, f in enumerate(notes):
            strum = int(round((idx * (0.010 if bloom else 0.014)) * SAMPLE_RATE))
            nl = _karplus_note(f * 0.9996, dur, 0.82, 0.9993, seed + idx * 7, felt_thump=0.02)
            nr = _karplus_note(f * 1.0004, dur, 0.82, 0.9993, seed + idx * 7 + 1, felt_thump=0.02)
            w = 0.26 if idx == 0 else (0.72 / max(1, len(notes) - 1))
            if strum < n:
                l_acc[strum:] += nl[: n - strum] * w
                r_acc[strum:] += nr[: n - strum] * w
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        root = np.sin(2.0 * np.pi * (82.41 if bloom else 73.42) * t) * (1.0 - np.exp(-t / 0.012)) * np.exp(-t / 0.45) * 0.14
        air = _bandpass_fft(_pink_noise(n, seed + 55), 4800.0, 15600.0) * 0.24 * (1.0 - np.exp(-t / 0.015)) * np.exp(-t / 0.30)
        atk = 1.0 - np.exp(-t / 0.008)
        rel = np.exp(-t / (0.50 if bloom else 0.72))
        fade_end = min(n, int(0.06 * SAMPLE_RATE))
        stereo = np.column_stack((l_acc * atk * rel + root + air, r_acc * atk * rel + root + air * 0.94))
        stereo[-fade_end:] *= np.linspace(1.0, 0.0, fade_end)[:, None]
        return _sculpt_airy_clean(_early_stereo_room(stereo, 0.30, seed, damp_hz=15800.0), mud_scoop=0.84, air_lift=2.25, sub_keep=0.78) * 0.86

    if bloom:
        notes = [329.63, 493.88, 659.25, 783.99, 1046.50] if style != "cinematic-sub" else [261.63, 392.00, 523.25, 659.25, 783.99]
        br = 0.44 if style == "tactile-wood" else (0.58 if style == "crisp-glass" else 0.36)
    else:
        notes = [146.83, 220.00, 261.63, 329.63, 440.00, 523.25] if style != "crisp-glass" else [164.81, 246.94, 329.63, 415.30, 493.88]
        br = 0.34 if style == "tactile-wood" else (0.48 if style == "crisp-glass" else 0.28)

    l_acc = np.zeros(n, dtype=np.float64)
    r_acc = np.zeros(n, dtype=np.float64)
    for idx, f in enumerate(notes):
        strum = int(round((idx * (0.006 if bloom else 0.009)) * SAMPLE_RATE))
        nl = _karplus_note(f * 0.9992, dur, br, 0.9992, seed + idx * 7, felt_thump=0.14 if idx < 2 else 0.08)
        nr = _karplus_note(f * 1.0008, dur, br, 0.9992, seed + idx * 7 + 1, felt_thump=0.14 if idx < 2 else 0.08)
        w = 0.30 if idx == 0 else (0.68 / max(1, len(notes) - 1))
        if strum < n:
            l_acc[strum:] += nl[: n - strum] * w
            r_acc[strum:] += nr[: n - strum] * w

    if bloom:
        t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
        air = _bandpass_fft(_pink_noise(n, seed + 55), 900.0, 5200.0) * 0.14 * (1.0 - np.exp(-t / 0.015)) * np.exp(-t / 0.24)
        l_acc += air
        r_acc += np.roll(air, 23)

    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    atk = 1.0 - np.exp(-t / 0.009)
    rel = np.exp(-t / (0.46 if bloom else 0.72))
    fade_end = min(n, int(0.06 * SAMPLE_RATE))
    stereo = np.column_stack((l_acc * atk * rel, r_acc * atk * rel))
    stereo[-fade_end:] *= np.linspace(1.0, 0.0, fade_end)[:, None]
    return _tape_saturate(_early_stereo_room(stereo, 0.95, seed), drive=1.22, cutoff_hz=8800.0 if style != "crisp-glass" else 11800.0) * 0.86


def _synth_bgm_groove(style: str) -> np.ndarray:
    """12.0s warm felt-piano / Rhodes / brushed acoustic pocket groove (seamless stereo loop)."""
    dur = 12.0
    n = int(SAMPLE_RATE * dur)
    mix = np.zeros((n, 2), dtype=np.float64)

    if style == "airy-clean":
        # Open minimalist glass/harp plucks with breathing air pockets & light crisp shaker (no heavy low-mid thud)
        notes = [
            (0.0, [329.63, 493.88, 659.25, 987.77]),
            (3.0, [293.66, 440.00, 587.33, 880.00]),
            (6.0, [246.94, 392.00, 587.33, 880.00]),
            (9.0, [220.00, 329.63, 493.88, 783.99]),
        ]
        for c_idx, (start, freqs) in enumerate(notes):
            s_idx = int(round(start * SAMPLE_RATE))
            for n_i, f in enumerate(freqs):
                pos = s_idx + int(round(n_i * 0.14 * SAMPLE_RATE))
                if pos >= n:
                    continue
                w = _karplus_note(f, 2.2, brightness=0.80, decay_factor=0.9993, seed=2100 + c_idx * 10 + n_i, felt_thump=0.02)
                tw = np.arange(len(w), dtype=np.float64) / SAMPLE_RATE
                w *= (1.0 - np.exp(-tw / 0.008)) * np.exp(-tw / 1.1) * 0.18
                take = min(len(w), n - pos)
                mix[pos : pos + take, 0] += w[:take] * (0.94 if n_i % 2 == 0 else 0.82)
                mix[pos : pos + take, 1] += w[:take] * (0.82 if n_i % 2 == 0 else 0.94)
        # Subtle wispy hi-air shaker pulse on quarter notes
        for b in range(16):
            bt = int(round(b * 0.75 * SAMPLE_RATE))
            bl = int(0.045 * SAMPLE_RATE)
            tb = np.arange(bl, dtype=np.float64) / SAMPLE_RATE
            shk = _bandpass_fft(_pink_noise(bl, 400 + b), 6500.0, 15500.0) * (1.0 - np.exp(-tb / 0.004)) * np.exp(-tb / 0.014) * (0.06 if b % 2 == 0 else 0.04)
            tk = min(bl, n - bt)
            mix[bt : bt + tk, 0] += shk[:tk]
            mix[bt : bt + tk, 1] += shk[:tk] * 0.92
        fade_n = int(0.06 * SAMPLE_RATE)
        ramp = np.linspace(0.0, 1.0, fade_n)[:, None]
        mix[:fade_n] *= ramp
        mix[-fade_n:] *= ramp[::-1]
        return _sculpt_airy_clean(_early_stereo_room(mix, 0.28, 991, damp_hz=15500.0), mud_scoop=0.85, air_lift=1.95) * 0.68

    chords = [
        (0.0, [73.42, 146.83, 220.00, 261.63, 329.63]),
        (3.0, [58.27, 116.54, 174.61, 220.00, 293.66]),
        (6.0, [49.00, 98.00, 146.83, 220.00, 293.66]),
        (9.0, [55.00, 110.00, 164.81, 246.94, 293.66]),
    ]
    br = 0.26 if style == "tactile-wood" else (0.38 if style == "crisp-glass" else 0.22)
    note_dur = 3.15
    for c_idx, (start, freqs) in enumerate(chords):
        s_idx = int(round(start * SAMPLE_RATE))
        for n_i, f in enumerate(freqs):
            strum = int(round(n_i * 0.012 * SAMPLE_RATE))
            pos = s_idx + strum
            if pos >= n:
                continue
            w = _karplus_note(
                f,
                note_dur,
                brightness=br * (0.65 if n_i == 0 else 1.0),
                decay_factor=0.99935,
                seed=1200 + c_idx * 20 + n_i,
                felt_thump=0.18 if n_i == 0 else 0.09,
            )
            t_w = np.arange(len(w), dtype=np.float64) / SAMPLE_RATE
            env = (1.0 - np.exp(-t_w / 0.014)) * np.exp(-t_w / 2.4)
            w *= env * (0.38 if n_i == 0 else 0.16)
            take = min(len(w), n - pos)
            pan_l = 0.92 if (n_i % 2 == 0) else 0.78
            pan_r = 0.78 if (n_i % 2 == 0) else 0.92
            mix[pos : pos + take, 0] += w[:take] * pan_l
            mix[pos : pos + take, 1] += w[:take] * pan_r

    step = 0.75
    beat_idx = 0
    while beat_idx * step < dur - 0.15:
        swing = 0.005 if (beat_idx % 2 == 1) else 0.0
        bt = int(round((beat_idx * step + swing) * SAMPLE_RATE))
        if beat_idx % 2 == 0:
            k_len = int(0.24 * SAMPLE_RATE)
            tk = np.arange(k_len, dtype=np.float64) / SAMPLE_RATE
            fk = 42.0 + 68.0 * np.exp(-tk / 0.024)
            phk = np.cumsum(2.0 * np.pi * fk / SAMPLE_RATE)
            kick = (0.30 * np.sin(phk) * np.exp(-tk / 0.09)
                    + 0.08 * _bandpass_fft(_pink_noise(k_len, 30 + beat_idx), 120.0, 540.0) * np.exp(-tk / 0.012))
            take = min(k_len, n - bt)
            mix[bt : bt + take, 0] += kick[:take]
            mix[bt : bt + take, 1] += kick[:take]
        else:
            b_len = int(0.085 * SAMPLE_RATE)
            tb = np.arange(b_len, dtype=np.float64) / SAMPLE_RATE
            brush = _bandpass_fft(_pink_noise(b_len, 90 + beat_idx), 1600.0, 6200.0) * (1.0 - np.exp(-tb / 0.006)) * np.exp(-tb / 0.022) * 0.10
            take = min(b_len, n - bt)
            mix[bt : bt + take, 0] += brush[:take] * 0.85
            mix[bt : bt + take, 1] += brush[:take] * 1.0
        beat_idx += 1

    fade_n = int(0.05 * SAMPLE_RATE)
    ramp = np.linspace(0.0, 1.0, fade_n)[:, None]
    mix[:fade_n] *= ramp
    mix[-fade_n:] *= ramp[::-1]
    return _tape_saturate(_early_stereo_room(mix, 0.72, 991), drive=1.18, cutoff_hz=7600.0 if style == "tactile-wood" else 9800.0) * 0.72


def _synth_bgm_ambient(style: str) -> np.ndarray:
    """12.0s warm breathing felt-pad & room bed (no drums, leaves wide clarity for SFX)."""
    dur = 12.0
    n = int(SAMPLE_RATE * dur)
    mix = np.zeros((n, 2), dtype=np.float64)
    blocks = [
        (0.0, [329.63, 493.88, 659.25, 987.77] if style == "airy-clean" else [164.81, 246.94, 329.63, 415.30]),
        (6.0, [293.66, 440.00, 587.33, 880.00] if style == "airy-clean" else [138.59, 207.65, 277.18, 329.63]),
    ]
    br = 0.78 if style == "airy-clean" else (0.34 if style == "crisp-glass" else 0.24)
    for b_idx, (start, freqs) in enumerate(blocks):
        st = int(round(start * SAMPLE_RATE))
        b_len = int(round(6.1 * SAMPLE_RATE))
        tb = np.arange(b_len, dtype=np.float64) / SAMPLE_RATE
        swell = np.maximum(0.0, np.sin(np.pi * np.clip(tb / 6.0, 0.0, 1.0))) ** (2.1 if style == "airy-clean" else 1.25)
        for f_i, f in enumerate(freqs):
            wl = _karplus_note(f * 0.9995, 6.1, br, 0.9995, 1400 + b_idx * 10 + f_i * 2, felt_thump=0.02 if style == "airy-clean" else 0.06)
            wr = _karplus_note(f * 1.0005, 6.1, br, 0.9995, 1401 + b_idx * 10 + f_i * 2, felt_thump=0.02 if style == "airy-clean" else 0.06)
            take = min(b_len, n - st)
            mix[st : st + take, 0] += wl[:take] * swell[:take] * 0.15
            mix[st : st + take, 1] += wr[:take] * swell[:take] * 0.15

    fade_n = int(0.06 * SAMPLE_RATE)
    ramp = np.linspace(0.0, 1.0, fade_n)[:, None]
    mix[:fade_n] *= ramp
    mix[-fade_n:] *= ramp[::-1]
    if style == "airy-clean":
        res = _sculpt_airy_clean(_early_stereo_room(mix, 0.28, 995, damp_hz=15500.0), mud_scoop=0.85, air_lift=1.95)
        pk = float(np.max(np.abs(res))) or 1.0
        return (res / pk) * 0.36
    return _tape_saturate(_early_stereo_room(mix, 0.85, 995), drive=1.10, cutoff_hz=7200.0) * 0.56


def _catalog_spec(style: str) -> dict[str, Any]:
    return {
        "version": "3.0",
        "style": style,
        "bgm_default": "sfx/bgm_groove.wav",
        "events": {
            "key": {
                "files": ["sfx/key_clack_01.wav", "sfx/key_clack_02.wav", "sfx/key_clack_03.wav"],
                "default_volume": 0.66,
                "preroll_sec": 0.0,
                "description": "Physical modal mechanical switch keystrokes (3 round-robin takes)",
            },
            "tap": {
                "files": ["sfx/ui_tap.wav", "sfx/ui_tap_02.wav", "sfx/ui_tap_03.wav"],
                "default_volume": 0.70,
                "preroll_sec": 0.0,
                "description": "Organic modal UI contact micro-tap (3 round-robin takes)",
            },
            "click": {
                "files": ["sfx/ui_tap.wav", "sfx/ui_tap_02.wav", "sfx/ui_tap_03.wav"],
                "default_volume": 0.72,
                "preroll_sec": 0.0,
                "description": "Alias for tactile UI click/tap",
            },
            "latch": {
                "files": ["sfx/switch_latch.wav", "sfx/switch_latch_02.wav"],
                "default_volume": 0.80,
                "preroll_sec": 0.0,
                "description": "Dual-stage magnetic lock & mechanical detent",
            },
            "lock": {
                "files": ["sfx/switch_latch.wav", "sfx/switch_latch_02.wav"],
                "default_volume": 0.80,
                "preroll_sec": 0.0,
                "description": "Alias for magnetic latch lock",
            },
            "tick": {
                "files": ["sfx/scrubber_tick.wav", "sfx/scrubber_tick_02.wav"],
                "default_volume": 0.56,
                "preroll_sec": 0.0,
                "description": "Knurled mechanical dial micro-detent for scrubbing",
            },
            "swish": {
                "files": ["sfx/air_swish_fast.wav", "sfx/air_swish_fast_02.wav"],
                "default_volume": 0.72,
                "preroll_sec": 0.030,
                "description": "Time-varying Doppler air/cloth swish for panel transitions",
            },
            "whoosh": {
                "files": ["sfx/air_whoosh_deep.wav"],
                "default_volume": 0.76,
                "preroll_sec": 0.035,
                "description": "Warm low-mid turbulent air transition whoosh",
            },
            "sub_impact": {
                "files": ["sfx/sub_impact.wav"],
                "default_volume": 0.84,
                "preroll_sec": 0.010,
                "description": "Felt-beater warm sub-bass thud for heavy hero landings",
            },
            "ping": {
                "files": ["sfx/glass_ping.wav"],
                "default_volume": 0.74,
                "preroll_sec": 0.0,
                "description": "Waveguide marimba/crystal double-chime for confirmations",
            },
            "riser": {
                "files": ["sfx/warm_riser.wav"],
                "default_volume": 0.68,
                "preroll_sec": 0.0,
                "description": "Filtered Doppler air + reed tension swell",
            },
            "chord": {
                "files": ["sfx/analog_chord.wav"],
                "default_volume": 0.88,
                "preroll_sec": 0.0,
                "description": "Strummed physical felt-piano/Rhodes minor-9th resolution",
            },
            "swell": {
                "files": ["sfx/harmonic_swell.wav"],
                "default_volume": 0.78,
                "preroll_sec": 0.040,
                "description": "Breathing harmonic waveguide swell for focus locks",
            },
            "glint": {
                "files": ["sfx/crystal_glint.wav", "sfx/crystal_glint_02.wav"],
                "default_volume": 0.72,
                "preroll_sec": 0.0,
                "description": "Warm marimba/glass spark with soft mallet attack",
            },
            "bloom": {
                "files": ["sfx/bloom_chime.wav"],
                "default_volume": 0.82,
                "preroll_sec": 0.020,
                "description": "Radiant strummed harmonic bloom for portal transitions",
            },
            "portal": {
                "files": ["sfx/portal_drop.wav"],
                "default_volume": 0.86,
                "preroll_sec": 0.015,
                "description": "Velvety Light-to-Dark sub sink with sweeping air pull",
            },
        },
    }


def _apply_custom_spectral_eq(samples: np.ndarray, custom_eq: dict[str, Any]) -> np.ndarray:
    """Apply continuous spectral profile parameters (mud_scoop, air_lift, sub_keep, cutoff_hz) from a reference DNA."""
    arr = np.column_stack((samples, samples)) if samples.ndim == 1 else samples.copy()
    n = len(arr)
    if n < 32:
        return arr
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    mud_scoop = float(custom_eq.get("mud_scoop", 0.0))
    air_lift = float(custom_eq.get("air_lift", 1.0))
    sub_keep = float(custom_eq.get("sub_keep", 1.0))
    cutoff_hz = float(custom_eq.get("cutoff_hz", 17500.0))

    mud_dip = 1.0 - mud_scoop * 0.55 * np.exp(-0.5 * ((freqs - 165.0) / 75.0) ** 2)
    air_curve = 1.0 + (air_lift - 1.0) * 0.45 * (1.0 / (1.0 + np.exp(-(freqs - 4000.0) / 1400.0)))
    sub_curve = 1.0 + (sub_keep - 1.0) * 0.55 * np.exp(-0.5 * (freqs / 78.0) ** 2)
    hi_taper = 1.0 / (1.0 + (freqs / max(3500.0, cutoff_hz)) ** 3)
    eq = np.maximum(0.22, mud_dip) * np.maximum(0.35, air_curve) * np.maximum(0.35, sub_curve) * hi_taper

    out = np.empty_like(arr)
    for ch in range(2):
        out[:, ch] = np.fft.irfft(np.fft.rfft(arr[:, ch]) * eq, n=n)
    mx_in = float(np.max(np.abs(arr))) + 1e-9
    mx_out = float(np.max(np.abs(out))) + 1e-9
    return out * min(1.35, mx_in / mx_out)


def build_sfx_pack(
    out_dir: str | os.PathLike[str] | None = None,
    *,
    style: str = "airy-clean",
    custom_eq: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate organic modal/waveguide WAV assets and catalog.json into out_dir."""
    if style not in VALID_STYLES:
        raise ValueError(f"Unknown SFX style {style!r}; expected one of {VALID_STYLES}")

    target = Path(out_dir) if out_dir is not None else DEFAULT_OUT_DIR
    target.mkdir(parents=True, exist_ok=True)

    generators: dict[str, np.ndarray] = {
        "key_clack_01.wav": _synth_key_clack(style, 0),
        "key_clack_02.wav": _synth_key_clack(style, 1),
        "key_clack_03.wav": _synth_key_clack(style, 2),
        "ui_tap.wav": _synth_ui_tap(style, 0),
        "ui_tap_02.wav": _synth_ui_tap(style, 1),
        "ui_tap_03.wav": _synth_ui_tap(style, 2),
        "switch_latch.wav": _synth_switch_latch(style, 0),
        "switch_latch_02.wav": _synth_switch_latch(style, 1),
        "scrubber_tick.wav": _synth_scrubber_tick(style, 0),
        "scrubber_tick_02.wav": _synth_scrubber_tick(style, 1),
        "air_swish_fast.wav": _synth_air_swish(style, deep=False, variant=0),
        "air_swish_fast_02.wav": _synth_air_swish(style, deep=False, variant=1),
        "air_whoosh_deep.wav": _synth_air_swish(style, deep=True, variant=0),
        "sub_impact.wav": _synth_sub_impact(style, portal=False),
        "glass_ping.wav": _synth_glass_ping(style),
        "warm_riser.wav": _synth_warm_riser(style),
        "analog_chord.wav": _synth_analog_chord(style, bloom=False),
        "harmonic_swell.wav": _synth_harmonic_swell(style),
        "crystal_glint.wav": _synth_crystal_glint(style, 0),
        "crystal_glint_02.wav": _synth_crystal_glint(style, 1),
        "bloom_chime.wav": _synth_analog_chord(style, bloom=True),
        "portal_drop.wav": _synth_sub_impact(style, portal=True),
        "bgm_groove.wav": _synth_bgm_groove(style),
        "bgm_ambient.wav": _synth_bgm_ambient(style),
    }

    written: list[str] = []
    for filename, samples in generators.items():
        if custom_eq:
            samples = _apply_custom_spectral_eq(samples, custom_eq)
        wav_path = target / filename
        _write_wav(wav_path, samples)
        written.append(str(wav_path))

    catalog = _catalog_spec(style)
    if custom_eq:
        catalog["remake_params"] = dict(custom_eq)
    catalog_path = target / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return {"out_dir": str(target), "style": style, "files": written, "catalog": str(catalog_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the bundled kinearc organic tactile SFX & BGM pack.")
    parser.add_argument("--out_dir", default=str(DEFAULT_OUT_DIR), help="Destination directory for WAVs and catalog.json")
    parser.add_argument(
        "--style",
        choices=VALID_STYLES,
        default="airy-clean",
        help="Acoustic palette style (airy-clean, tactile-wood, crisp-glass, or cinematic-sub)",
    )
    parser.add_argument("--profile", default=None, help="Optional audio_profile.json from extract_audio_style to sculpt the remade pack")
    args = parser.parse_args(argv)

    chosen_style = args.style
    custom_eq = None
    if args.profile:
        prof = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        chosen_style = prof.get("recommended_style", chosen_style)
        custom_eq = prof.get("remake_params")
    res = build_sfx_pack(args.out_dir, style=chosen_style, custom_eq=custom_eq)
    print(f"[build_sfx_pack] Generated {len(res['files'])} audio files ({res['style']}) -> {res['out_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
