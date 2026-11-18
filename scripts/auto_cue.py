#!/usr/bin/env python3
"""
auto_cue.py — Automated Tactile Foley Cue Generator for kinearc.

Scans a `kinearc.project.json` manifest or standalone `.html` scene for semantic `@cue`
directives (or falls back to detecting `springProgress` / transition keyframes in code),
applies psychoacoustic pre-rolls (-30ms on whooshes/swishes), expands composite bursts
(`typing`, `scrub`, `transition`), offsets timestamps across multi-scene timelines, and
writes a sorted `cues.json` ready for `scripts/audio_mix.py` and `scripts/kinearc_ui.py`.
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
KV_TOKEN_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^\s*]+)")
TOTAL_DURATION_RE = re.compile(
    r"(?:totalDuration|(?:window\.)?TOTAL|(?:const|let|var)\s+TOTAL)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)"
)
SPRING_DELAY_RE = re.compile(r"springProgress\s*\([^,]+,\s*\{[^}]*?\bdelay\s*:\s*([0-9]+(?:\.[0-9]+)?)")


def load_catalog() -> dict[str, Any]:
    if CATALOG_PATH.is_file():
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
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


def _infer_scene_duration(html_text: str, explicit_duration: float | None) -> float:
    if explicit_duration is not None and explicit_duration > 0:
        return float(explicit_duration)
    m = TOTAL_DURATION_RE.search(html_text)
    if m:
        return float(m.group(1))
    return 3.0


def _expand_event(
    local_t: float,
    kind: str,
    opts: dict[str, Any],
    scene_offset: float,
    events_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    base_t = scene_offset + max(0.0, float(local_t))
    kind_norm = kind.lower().strip()
    out: list[dict[str, Any]] = []

    if kind_norm == "transition":
        vol = float(opts.get("volume", 0.80))
        out.append({"file": "sfx/air_swish_fast.wav", "time": round(max(0.0, base_t - 0.035), 3), "volume": round(min(0.95, vol * 0.88), 2)})
        out.append({"file": "sfx/sub_impact.wav", "time": round(max(0.0, base_t), 3), "volume": round(min(0.95, vol), 2)})
        out.append({"file": "sfx/switch_latch.wav", "time": round(max(0.0, base_t + 0.016), 3), "volume": round(min(0.95, vol * 0.84), 2)})
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
        # Deterministic human-like rhythm offsets
        jitter_cycle = (0.0, -0.006, 0.008, -0.004, 0.005, -0.007)
        vol_cycle = (1.0, 0.91, 1.04, 0.94, 0.98, 0.89)
        step = dur / max(1, count - 1) if count > 1 else 0.0
        for i in range(count):
            jit = jitter_cycle[i % len(jitter_cycle)] if i > 0 else 0.0
            t_i = max(0.0, base_t + i * step + jit)
            v_i = min(0.95, max(0.25, base_vol * vol_cycle[i % len(vol_cycle)]))
            f_i = files[i % len(files)]
            out.append({"file": f_i, "time": round(t_i, 3), "volume": round(v_i, 2)})
        return out

    if kind_norm == "scrub":
        dur = max(0.06, float(opts.get("duration", 0.45)))
        ticks = max(1, int(opts.get("ticks", int(opts.get("count", max(3, int(round(dur / 0.065))))))))
        base_vol = float(opts.get("volume", 0.56))
        step = dur / max(1, ticks - 1) if ticks > 1 else 0.0
        for i in range(ticks):
            t_i = max(0.0, base_t + i * step)
            accent = 1.06 if (i == 0 or i == ticks - 1) else 0.92
            out.append({
                "file": "sfx/scrubber_tick.wav",
                "time": round(t_i, 3),
                "volume": round(min(0.95, base_vol * accent), 2),
            })
        return out

    spec = events_spec.get(kind_norm)
    if spec is None:
        # Direct filename fallback if user passed e.g. sfx/ui_tap.wav
        raw_file = kind if kind.endswith(".wav") else f"sfx/{kind_norm}.wav"
        vol = float(opts.get("volume", 0.72))
        out.append({"file": raw_file, "time": round(max(0.0, base_t), 3), "volume": round(vol, 2)})
        return out

    files = spec.get("files", ["sfx/ui_tap.wav"])
    variant_idx = int(opts.get("variant", 0)) % len(files)
    preroll = float(opts.get("preroll", spec.get("preroll_sec", 0.0)))
    vol = float(opts.get("volume", spec.get("default_volume", 0.72)))
    out.append({
        "file": files[variant_idx],
        "time": round(max(0.0, base_t - preroll), 3),
        "volume": round(min(0.95, max(0.15, vol)), 2),
    })
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
) -> tuple[list[dict[str, Any]], float]:
    """Parse `@cue` directives from a scene HTML file (or infer spring/transition cues)."""
    p = Path(scene_path)
    if not p.is_file():
        raise FileNotFoundError(f"Scene file not found: {p}")

    html_text = p.read_text(encoding="utf-8")
    dur = _infer_scene_duration(html_text, scene_duration)
    catalog = load_catalog()
    events_spec = catalog.get("events", {})

    # Strip quoted JS string literals so displayed code snippets (e.g. "// @cue ...") never trigger phantom audio cues.
    scan_text = STRING_LITERAL_RE.sub('""', html_text)
    directives = CUE_DIRECTIVE_RE.findall(scan_text)
    raw_cues: list[dict[str, Any]] = []

    if directives:
        for raw_t, raw_kind, raw_tail in directives:
            local_t = float(raw_t)
            opts = _parse_kv_options(raw_tail)
            raw_cues.extend(_expand_event(local_t, raw_kind, opts, scene_offset, events_spec))
    else:
        # Automatic heuristic fallback when a scene has no explicit @cue comments
        raw_cues.extend(_expand_event(0.02, "transition", {"volume": 0.76}, scene_offset, events_spec))
        delays = sorted({float(d) for d in SPRING_DELAY_RE.findall(html_text) if 0.05 <= float(d) <= dur})
        for idx, d_sec in enumerate(delays):
            kind = "swish" if idx % 2 == 0 else "latch"
            raw_cues.extend(_expand_event(d_sec, kind, {"volume": 0.70}, scene_offset, events_spec))
            if idx % 2 == 0:
                raw_cues.extend(_expand_event(d_sec + 0.14, "tap", {"volume": 0.66}, scene_offset, events_spec))

    return _dedupe_and_sort(raw_cues), dur


def generate_project_cues(
    input_path: str | os.PathLike[str],
    out_path: str | os.PathLike[str] | None = None,
    copy_local_sfx: bool = False,
) -> list[dict[str, Any]]:
    """Generate micro-timed cues for a `kinearc.project.json` or standalone `.html` scene."""
    abs_in = Path(os.path.abspath(os.fspath(input_path)))
    if not abs_in.is_file():
        raise FileNotFoundError(f"Input project or scene not found: {abs_in}")

    all_cues: list[dict[str, Any]] = []
    if abs_in.suffix.lower() in {".html", ".htm"}:
        cues, _ = extract_scene_cues(abs_in, scene_offset=0.0)
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
                src_wav = REPO_ROOT / "assets" / rel
                if src_wav.is_file():
                    shutil.copy2(src_wav, local_sfx_dir / src_wav.name)
                    copied.add(rel)

    return final_cues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="auto_cue.py",
        description="Auto-generate micro-timed tactile SFX cues.json from kinearc scenes or project manifests.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", help="Path to kinearc.project.json manifest")
    group.add_argument("--scene", help="Path to standalone .html scene")
    parser.add_argument("--out", required=True, help="Output cues.json path")
    parser.add_argument(
        "--copy-local-sfx",
        action="store_true",
        help="Copy referenced WAV files into <out_dir>/sfx/ alongside cues.json",
    )
    args = parser.parse_args(argv)
    target_input = args.project if args.project else args.scene
    cues = generate_project_cues(target_input, out_path=args.out, copy_local_sfx=args.copy_local_sfx)
    print(f"[autocue] Generated {len(cues)} tactile SFX cues -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
