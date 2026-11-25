#!/usr/bin/env python3
"""
auto_cue.py — Scene-Aware Automated Tactile Foley Cue Generator for kinearc.

Scans a `kinearc.project.json` manifest or standalone `.html` scene for semantic `@cue`
directives (or falls back to detecting `springProgress` / transition keyframes in code),
analyzes each scene's visual material (crystal, paper-wood, metal, deep-space), luminance
(light vs dark), color temperature (cool vs warm), and acoustic space scale (or honours explicit
`// @scene-audio ...` directives), applies psychoacoustic pre-rolls, rotates round-robins,
and writes a sorted `cues.json` with per-cue acoustic tone & room tags for `scripts/audio_mix.py`.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "assets" / "sfx" / "catalog.json"

STRING_LITERAL_RE = re.compile(r'(["\'`])(?:\\.|(?!\1)[^\\\r\n])*\1')
CUE_DIRECTIVE_RE = re.compile(
    r"(?://|/\*)\s*@cue\s+([0-9]+(?:\.[0-9]+)?)\s+([a-zA-Z0-9_-]+)(.*?)(?:\*/|$)",
    re.MULTILINE,
)
SCENE_AUDIO_RE = re.compile(r"(?://|/\*)\s*@scene-audio\s+(.*?)(?:\*/|$)", re.MULTILINE)
KV_TOKEN_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^\s*]+)")
TOTAL_DURATION_RE = re.compile(
    r"(?:totalDuration|(?:window\.)?TOTAL|(?:const|let|var)\s+TOTAL)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)"
)
SPRING_DELAY_RE = re.compile(r"springProgress\s*\([^,]+,\s*\{[^}]*?\bdelay\s*:\s*([0-9]+(?:\.[0-9]+)?)")
THEME_RE = re.compile(r"""theme\s*:\s*["'](pearl|midnight|obsidian|editorial|optical)["']""", re.IGNORECASE)
BG_HEX_RE = re.compile(r"background\s*:\s*(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b")
RGBA_POOL_RE = re.compile(r"(?:warmPool|coolPool|tint|accent)[^;{}]*?rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")
GL_COLOR_RE = re.compile(r"(?:keyColor|fillColor)\s*:\s*\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]")

TONAL_LOCKED_KINDS = {"chord", "swell", "bloom", "ping", "riser", "sub_impact", "portal"}


def load_catalog(catalog_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    path = Path(catalog_path) if catalog_path else CATALOG_PATH
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": "3.0", "events": {}}


def _parse_kv_options(raw_tail: str) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    for key, val in KV_TOKEN_RE.findall(raw_tail or ""):
        clean = val.strip().strip(",;")
        try:
            if "." in clean:
                opts[key] = float(clean)
            else:
                opts[key] = int(clean)
        except ValueError:
            opts[key] = clean
    return opts


def _hex_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return 0.5
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def analyze_scene_audio_profile(html_text: str) -> dict[str, Any]:
    """Infer scene material, brightness, color temperature, and acoustic space -> SFX EQ/room params."""
    explicit: dict[str, Any] = {}
    for raw_tail in SCENE_AUDIO_RE.findall(html_text):
        explicit.update(_parse_kv_options(raw_tail))

    # 1. Brightness (light vs neutral vs dark)
    brightness = "light"
    theme_m = THEME_RE.search(html_text)
    if theme_m:
        th = theme_m.group(1).lower()
        brightness = "dark" if th in {"midnight", "obsidian"} else ("light" if th in {"pearl", "editorial", "optical"} else "neutral")
    else:
        bg_m = BG_HEX_RE.search(html_text)
        if bg_m:
            lum = _hex_luminance(bg_m.group(1))
            brightness = "dark" if lum < 0.28 else ("light" if lum >= 0.65 else "neutral")

    # 2. Material detection from 3D mesh constructors & surface UI primitives
    lower = html_text.lower()
    if "drawportalflash" in lower or ("createtorusknotmesh" in lower and brightness == "dark"):
        material = "deep-space"
    elif "createcrystalmesh" in lower or "prism" in lower or "crystal" in lower:
        material = "crystal"
    elif "drawmachinedpanel" in lower or "createtorusmesh" in lower or "machined" in lower or "knurled" in lower:
        material = "metal"
    else:
        material = "paper-wood"

    # 3. Color temperature balance from warmPool/coolPool/gl lighting colors
    rb_balance = 0.0
    color_samples = 0
    for r_s, _, b_s in RGBA_POOL_RE.findall(html_text):
        rb_balance += (int(r_s) - int(b_s)) / 255.0
        color_samples += 1
    for r_s, _, b_s in GL_COLOR_RE.findall(html_text):
        rb_balance += float(r_s) - float(b_s)
        color_samples += 1
    avg_rb = rb_balance / color_samples if color_samples else 0.0
    temp = "warm" if avg_rb > 0.08 else ("cool" if avg_rb < -0.08 else "neutral")

    # 4. Acoustic room scale
    space = "wide" if (brightness == "dark" or material == "deep-space" or "drawportalflash" in lower) else "intimate"

    # Override cleanly if user declared explicit attributes in @scene-audio
    brightness = str(explicit.get("brightness", brightness)).lower()
    material = str(explicit.get("material", material)).lower()
    temp = str(explicit.get("temp", temp)).lower()
    space = str(explicit.get("space", space)).lower()

    # Compute continuous acoustic target (tilt_db, cutoff_hz, sub_boost, room, pitch_shift)
    if brightness == "dark" or material == "deep-space":
        tilt_db = -2.2
        cutoff_hz = 7800.0
        sub_boost = 1.24
        room_wet = 0.16
        pitch_shift = 0.95
    elif material == "crystal":
        tilt_db = 1.8 if temp == "cool" else 1.2
        cutoff_hz = 17200.0
        sub_boost = 1.0
        room_wet = 0.05 if space == "intimate" else 0.11
        pitch_shift = 1.02 if temp == "cool" else 1.0
    elif material == "metal":
        tilt_db = 1.1
        cutoff_hz = 15800.0
        sub_boost = 1.04
        room_wet = 0.07 if space == "intimate" else 0.12
        pitch_shift = 1.01
    else:  # paper-wood
        tilt_db = 0.5
        cutoff_hz = 14800.0
        sub_boost = 1.0
        room_wet = 0.055
        pitch_shift = 1.0

    if temp == "warm":
        tilt_db -= 0.7
        cutoff_hz = min(cutoff_hz, 12600.0)
    elif temp == "cool" and brightness != "dark":
        tilt_db += 0.4

    if space == "wide":
        room_wet = max(room_wet, 0.15)
    elif space == "medium":
        room_wet = max(room_wet, 0.09)

    return {
        "material": material,
        "brightness": brightness,
        "temp": temp,
        "space": space,
        "tilt_db": round(float(explicit.get("tilt_db", tilt_db)), 2),
        "cutoff_hz": round(float(explicit.get("cutoff_hz", cutoff_hz)), 1),
        "sub_boost": round(float(explicit.get("sub_boost", sub_boost)), 2),
        "room": round(float(explicit.get("room", room_wet)), 3),
        "pitch_shift": round(float(explicit.get("pitch", pitch_shift)), 3),
    }


def _infer_scene_duration(html_text: str, explicit_duration: float | None) -> float:
    if explicit_duration is not None and explicit_duration > 0:
        return float(explicit_duration)
    m = TOTAL_DURATION_RE.search(html_text)
    if m:
        return float(m.group(1))
    return 3.0


def _apply_scene_tags(
    entry: dict[str, Any],
    kind_norm: str,
    opts: dict[str, Any],
    scene_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    if scene_profile is None:
        return entry
    entry["room"] = float(opts.get("room", scene_profile["room"]))
    entry["tilt_db"] = float(opts.get("tilt_db", scene_profile["tilt_db"]))
    entry["cutoff_hz"] = float(opts.get("cutoff_hz", scene_profile["cutoff_hz"]))
    if float(opts.get("sub_boost", scene_profile["sub_boost"])) > 1.02:
        entry["sub_boost"] = float(opts.get("sub_boost", scene_profile["sub_boost"]))
    if "pitch" in opts:
        entry["pitch"] = float(opts["pitch"])
    elif kind_norm not in TONAL_LOCKED_KINDS and abs(float(scene_profile["pitch_shift"]) - 1.0) >= 0.01:
        entry["pitch"] = float(scene_profile["pitch_shift"])
    return entry


def _expand_event(
    local_t: float,
    kind: str,
    opts: dict[str, Any],
    scene_offset: float,
    events_spec: dict[str, Any],
    rr_counts: dict[str, int] | None = None,
    scene_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    base_t = scene_offset + max(0.0, float(local_t))
    kind_norm = kind.lower().strip()
    out: list[dict[str, Any]] = []
    explicit_pan = float(opts["pan"]) if "pan" in opts else None

    if kind_norm == "transition":
        vol = float(opts.get("volume", 0.80))
        out.append(_apply_scene_tags({"file": "sfx/air_swish_fast.wav", "time": round(max(0.0, base_t - 0.035), 3), "volume": round(min(0.95, vol * 0.88), 2)}, "swish", opts, scene_profile))
        out.append(_apply_scene_tags({"file": "sfx/sub_impact.wav", "time": round(max(0.0, base_t), 3), "volume": round(min(0.95, vol), 2)}, "sub_impact", opts, scene_profile))
        out.append(_apply_scene_tags({"file": "sfx/switch_latch.wav", "time": round(max(0.0, base_t + 0.016), 3), "volume": round(min(0.95, vol * 0.84), 2)}, "latch", opts, scene_profile))
        return out

    if kind_norm == "typing":
        dur = max(0.08, float(opts.get("duration", 0.55)))
        count = max(1, int(opts.get("count", max(3, int(round(dur / 0.075))))))
        base_vol = float(opts.get("volume", 0.65))
        files = events_spec.get("key", {}).get("files", [
            "sfx/key_clack_01.wav",
            "sfx/key_clack_02.wav",
            "sfx/key_clack_03.wav",
        ])
        jitter_cycle = (0.0, -0.006, 0.008, -0.004, 0.005, -0.007)
        vol_cycle = (1.0, 0.91, 1.04, 0.94, 0.98, 0.89)
        step = dur / max(1, count - 1) if count > 1 else 0.0
        for i in range(count):
            jit = jitter_cycle[i % len(jitter_cycle)] if i > 0 else 0.0
            t_i = max(0.0, base_t + i * step + jit)
            v_i = min(0.95, max(0.25, base_vol * vol_cycle[i % len(vol_cycle)]))
            f_i = files[i % len(files)]
            entry: dict[str, Any] = {"file": f_i, "time": round(t_i, 3), "volume": round(v_i, 2)}
            if explicit_pan is not None:
                entry["pan"] = explicit_pan
            out.append(_apply_scene_tags(entry, "key", opts, scene_profile))
        return out

    if kind_norm == "scrub":
        dur = max(0.06, float(opts.get("duration", 0.45)))
        ticks = max(1, int(opts.get("ticks", int(opts.get("count", max(3, int(round(dur / 0.065))))))))
        base_vol = float(opts.get("volume", 0.56))
        files = events_spec.get("tick", {}).get("files", ["sfx/scrubber_tick.wav"])
        step = dur / max(1, ticks - 1) if ticks > 1 else 0.0
        for i in range(ticks):
            t_i = max(0.0, base_t + i * step)
            accent = 1.06 if (i == 0 or i == ticks - 1) else 0.92
            out.append(_apply_scene_tags({
                "file": files[i % len(files)],
                "time": round(t_i, 3),
                "volume": round(min(0.95, base_vol * accent), 2),
            }, "tick", opts, scene_profile))
        return out

    spec = events_spec.get(kind_norm)
    if spec is None:
        raw_file = kind if kind.endswith(".wav") else f"sfx/{kind_norm}.wav"
        vol = float(opts.get("volume", 0.72))
        entry = {"file": raw_file, "time": round(max(0.0, base_t), 3), "volume": round(vol, 2)}
        if explicit_pan is not None:
            entry["pan"] = explicit_pan
        out.append(_apply_scene_tags(entry, kind_norm, opts, scene_profile))
        return out

    files = spec.get("files", ["sfx/ui_tap.wav"])
    if "variant" in opts:
        variant_idx = int(opts["variant"]) % len(files)
    elif rr_counts is not None:
        variant_idx = rr_counts.get(kind_norm, 0) % len(files)
        rr_counts[kind_norm] = variant_idx + 1
    else:
        variant_idx = 0
    preroll = float(opts.get("preroll", spec.get("preroll_sec", 0.0)))
    vol = float(opts.get("volume", spec.get("default_volume", 0.72)))
    entry = {
        "file": files[variant_idx],
        "time": round(max(0.0, base_t - preroll), 3),
        "volume": round(min(0.95, max(0.15, vol)), 2),
    }
    if explicit_pan is not None:
        entry["pan"] = explicit_pan
    out.append(_apply_scene_tags(entry, kind_norm, opts, scene_profile))
    return out


def _dedupe_and_sort(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(cues, key=lambda c: (float(c["time"]), str(c["file"])))
    cleaned: list[dict[str, Any]] = []
    for cue in ordered:
        if cleaned:
            prev = cleaned[-1]
            if prev["file"] == cue["file"] and abs(float(cue["time"]) - float(prev["time"])) < 0.022:
                prev["volume"] = round(max(float(prev["volume"]), float(cue["volume"])), 2)
                continue
        cleaned.append(cue)
    return cleaned


def extract_scene_cues(
    scene_path: str | os.PathLike[str],
    scene_offset: float = 0.0,
    scene_duration: float | None = None,
    *,
    scene_match: bool = True,
    catalog_path: str | os.PathLike[str] | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """Parse `@cue` directives & scene visual material/mood from HTML (or infer spring cues)."""
    p = Path(scene_path)
    if not p.is_file():
        raise FileNotFoundError(f"Scene file not found: {p}")

    html_text = p.read_text(encoding="utf-8")
    dur = _infer_scene_duration(html_text, scene_duration)
    catalog = load_catalog(catalog_path)
    events_spec = catalog.get("events", {})
    scene_profile = analyze_scene_audio_profile(html_text) if scene_match else None

    # Strip quoted JS string literals so displayed code snippets (e.g. "// @cue ...") never trigger phantom audio cues.
    scan_text = STRING_LITERAL_RE.sub('""', html_text)
    directives = CUE_DIRECTIVE_RE.findall(scan_text)
    raw_cues: list[dict[str, Any]] = []
    rr_counts: dict[str, int] = {}

    if directives:
        for raw_t, raw_kind, raw_tail in directives:
            local_t = float(raw_t)
            opts = _parse_kv_options(raw_tail)
            raw_cues.extend(_expand_event(local_t, raw_kind, opts, scene_offset, events_spec, rr_counts=rr_counts, scene_profile=scene_profile))
    else:
        raw_cues.extend(_expand_event(0.02, "transition", {"volume": 0.76}, scene_offset, events_spec, rr_counts=rr_counts, scene_profile=scene_profile))
        delays = sorted({float(d) for d in SPRING_DELAY_RE.findall(html_text) if 0.05 <= float(d) <= dur})
        for idx, d_sec in enumerate(delays):
            kind = "swish" if idx % 2 == 0 else "latch"
            raw_cues.extend(_expand_event(d_sec, kind, {"volume": 0.70}, scene_offset, events_spec, rr_counts=rr_counts, scene_profile=scene_profile))
            if idx % 2 == 0:
                raw_cues.extend(_expand_event(d_sec + 0.14, "tap", {"volume": 0.66}, scene_offset, events_spec, rr_counts=rr_counts, scene_profile=scene_profile))

    return _dedupe_and_sort(raw_cues), dur


def generate_project_cues(
    input_path: str | os.PathLike[str],
    out_path: str | os.PathLike[str] | None = None,
    copy_local_sfx: bool = False,
    *,
    scene_match: bool = True,
    sfx_source_dir: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """Generate micro-timed, scene-matched cues for a `kinearc.project.json` or `.html` scene."""
    abs_in = Path(os.path.abspath(os.fspath(input_path)))
    if not abs_in.is_file():
        raise FileNotFoundError(f"Input project or scene not found: {abs_in}")

    sfx_root = Path(os.path.abspath(os.fspath(sfx_source_dir))) if sfx_source_dir else (REPO_ROOT / "assets" / "sfx")
    cat_override = (sfx_root / "catalog.json") if (sfx_root / "catalog.json").is_file() else None

    all_cues: list[dict[str, Any]] = []
    if abs_in.suffix.lower() in {".html", ".htm"}:
        cues, _ = extract_scene_cues(abs_in, scene_offset=0.0, scene_match=scene_match, catalog_path=cat_override)
        all_cues.extend(cues)
    elif abs_in.suffix.lower() == ".json":
        data = json.loads(abs_in.read_text(encoding="utf-8"))
        raw_scenes = data.get("scenes", [])
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ValueError(f"Project manifest 'scenes' must be a non-empty list: {abs_in}")
        offset = 0.0
        for item in raw_scenes:
            if isinstance(item, str):
                s_rel = item
                s_dur = None
            elif isinstance(item, dict):
                s_rel = item.get("path") or item.get("file") or item.get("src") or item.get("html")
                if not isinstance(s_rel, str) or not s_rel.strip():
                    raise ValueError(f"Scene entry missing 'path'/'file'/'src'/'html': {item!r}")
                s_dur = item.get("duration") if item.get("duration") is not None else item.get("total")
            else:
                raise ValueError(f"Invalid scene entry: {item!r}")
            s_path = Path(s_rel) if os.path.isabs(str(s_rel)) else (abs_in.parent / str(s_rel))
            scene_cues, resolved_dur = extract_scene_cues(
                s_path.resolve(),
                scene_offset=offset,
                scene_duration=float(s_dur) if s_dur is not None else None,
                scene_match=scene_match,
                catalog_path=cat_override,
            )
            all_cues.extend(scene_cues)
            offset += resolved_dur
    else:
        raise ValueError(f"Unsupported input extension {abs_in.suffix!r}")

    final_cues = _dedupe_and_sort(all_cues)

    if out_path is not None:
        dest = Path(os.path.abspath(os.fspath(out_path)))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(final_cues, indent=2) + "\n", encoding="utf-8")

        if copy_local_sfx:
            local_sfx_dir = dest.parent / "sfx"
            local_sfx_dir.mkdir(parents=True, exist_ok=True)
            copied: set[str] = set()
            for cue in final_cues:
                rel = cue["file"]
                if rel in copied:
                    continue
                src_wav = sfx_root / Path(rel).name if sfx_source_dir else (REPO_ROOT / "assets" / rel)
                if not src_wav.is_file():
                    src_wav = REPO_ROOT / "assets" / rel
                if src_wav.is_file():
                    shutil.copy2(src_wav, local_sfx_dir / src_wav.name)
                    copied.add(rel)

    return final_cues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="auto_cue.py",
        description="Auto-generate scene-matched tactile SFX cues.json from kinearc scenes or project manifests.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", help="Path to kinearc.project.json manifest")
    group.add_argument("--scene", help="Path to standalone .html scene")
    parser.add_argument("--out", required=True, help="Output cues.json path")
    parser.add_argument("--copy-local-sfx", action="store_true", help="Copy referenced WAV files into <out_dir>/sfx/")
    parser.add_argument("--sfx-dir", default=None, help="Optional custom sfx/ directory (e.g. from extract-audio)")
    parser.add_argument("--no-scene-match", action="store_true", help="Disable per-scene material/temperature acoustic matching")
    args = parser.parse_args(argv)
    target_input = args.project if args.project else args.scene
    cues = generate_project_cues(
        target_input,
        out_path=args.out,
        copy_local_sfx=args.copy_local_sfx,
        scene_match=not args.no_scene_match,
        sfx_source_dir=args.sfx_dir,
    )
    print(f"[autocue] Generated {len(cues)} tactile SFX cues -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
