#!/usr/bin/env python3
"""
kinearc_cli.py — Unified CLI Wrapper, Manifest Validator & Environment Doctor for kinearc.

Provides:
  - `validate_manifest`: Pre-render validation & even-dimension scaling for `kinearc.project.json` or `.html` scenes.
  - `find_browser_executable`: Cross-platform Chrome / Edge / Chromium binary discovery.
  - `run_doctor`: Environment probe for Python (cv2/numpy), FFmpeg/FFprobe, Node.js 24+, Browser, and `engine/render.mjs`.
  - Subcommands: `doctor`, `render`, `stills`, plus direct passthrough to `extract`, `track`, `measure`, `verify`, `ui`, `audio`.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import math
import ntpath
import os
import platform as py_platform
import posixpath
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
ENGINE_RENDER = os.path.join(REPO_ROOT, "engine", "render.mjs")
MIN_NODE_MAJOR = 24

PASSTHROUGH_SCRIPTS: dict[str, tuple[str, str, str]] = {
    "extract": ("extract_full_motion.py", "extract_full_motion", "Extract full-FPS frames, trails, and scene cuts"),
    "track": ("track_objects.py", "track_objects", "Track optical flow, rotation, plateaus, and particles"),
    "measure": ("measure_shapes_colors.py", "measure_shapes_colors", "Measure geometry, card bop scale, and HEX colors"),
    "verify": ("verify_motion_diff.py", "verify_motion_diff", "Verify motion MAE/PSNR, jitter, blur, and loop seam"),
    "ui": ("kinearc_ui.py", "kinearc_ui", "Launch the interactive dual-mode kinearc workbench UI"),
    "audio": ("audio_mix.py", "audio_mix", "Auto-ducking audio mixer & silence pause cutter"),
}


def _require_finite_number(val: Any, name: str, *, allow_zero: bool = False) -> float:
    """Validate that a value is a non-boolean finite number (> 0 or >= 0)."""
    if isinstance(val, bool):
        raise ValueError(f"{name} must be a number, got bool {val!r}")
    try:
        num = float(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number, got {val!r}") from exc
    if not math.isfinite(num):
        raise ValueError(f"{name} must be finite, got {val!r}")
    if allow_zero:
        if num < 0:
            raise ValueError(f"{name} must be >= 0, got {val!r}")
    elif num <= 0:
        raise ValueError(f"{name} must be > 0, got {val!r}")
    return num


def even_dimension(val: float | int) -> int:
    """Round a positive finite dimension and clamp down to an even integer >= 2."""
    num = _require_finite_number(val, "dimension", allow_zero=False)
    return max(2, (int(round(num)) // 2) * 2)


def _resolve_existing_file(raw_path: Any, base_dir: str, label: str) -> str:
    """Resolve a path relative to base_dir and verify that it exists as a regular file."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"{label} path must be a non-empty string, got {raw_path!r}")
    abs_path = os.path.abspath(raw_path) if os.path.isabs(raw_path) else os.path.abspath(os.path.join(base_dir, raw_path))
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"{label} file not found: {abs_path}")
    return abs_path


def _parse_scene_entry(item: Any, project_dir: str) -> dict[str, Any]:
    """Parse and validate a single scene string or object from kinearc.project.json."""
    if isinstance(item, str):
        abs_scene = _resolve_existing_file(item, project_dir, "Scene")
        return {"path": abs_scene, "duration": None}

    if isinstance(item, dict):
        raw_scene = item.get("path") or item.get("file") or item.get("src") or item.get("html")
        if raw_scene is None or (isinstance(raw_scene, str) and not raw_scene.strip()):
            raise ValueError(f"Scene entry missing 'path'/'file'/'src'/'html': {item!r}")
        abs_scene = _resolve_existing_file(raw_scene, project_dir, "Scene")
        raw_dur = item.get("duration") if item.get("duration") is not None else item.get("total")
        dur_val = _require_finite_number(raw_dur, "scene duration", allow_zero=False) if raw_dur is not None else None
        return {"path": abs_scene, "duration": dur_val}

    raise ValueError(f"Scene entry must be a path string or object, got {type(item).__name__}")


def _parse_optional_track(audio_cfg: dict[str, Any], keys: tuple[str, str], project_dir: str, label: str) -> str | None:
    """Resolve an optional audio file path from preferred/alias keys, verifying existence."""
    raw_val = None
    for k in keys:
        if k in audio_cfg and audio_cfg[k] is not None:
            candidate = audio_cfg[k]
            if not isinstance(candidate, str):
                raise ValueError(f"Audio '{keys[0]}' must be a path string or null, got {candidate!r}")
            if not candidate.strip():
                continue
            raw_val = candidate
            break
    if raw_val is None:
        return None
    return _resolve_existing_file(raw_val, project_dir, label)


def _parse_audio_config(raw_audio: Any, project_dir: str) -> dict[str, Any] | None:
    """Normalize optional `audio` manifest block using audio_mix.py defaults."""
    if raw_audio is None:
        return None
    if not isinstance(raw_audio, dict):
        raise ValueError(f"Project manifest 'audio' must be an object or null, got {type(raw_audio).__name__}")
    if not raw_audio:
        return None

    voice_path = _parse_optional_track(raw_audio, ("voice", "voice_path"), project_dir, "Audio voice")
    bgm_path = _parse_optional_track(raw_audio, ("bgm", "bgm_path"), project_dir, "Audio bgm")
    sfx_path = _parse_optional_track(raw_audio, ("sfx", "sfx_path"), project_dir, "Audio sfx")

    raw_keep = raw_audio.get("keep_video_audio", False)
    if raw_keep is None:
        raw_keep = False
    if not isinstance(raw_keep, bool):
        raise ValueError(f"Audio 'keep_video_audio' must be a boolean, got {raw_keep!r}")

    if voice_path is None and bgm_path is None and sfx_path is None and not raw_keep:
        return None

    voice_vol = _require_finite_number(raw_audio.get("voice_vol", 1.0) if raw_audio.get("voice_vol") is not None else 1.0, "voice_vol", allow_zero=True)
    bgm_vol = _require_finite_number(raw_audio.get("bgm_vol", 0.35) if raw_audio.get("bgm_vol") is not None else 0.35, "bgm_vol", allow_zero=True)
    video_vol = _require_finite_number(raw_audio.get("video_vol", 1.0) if raw_audio.get("video_vol") is not None else 1.0, "video_vol", allow_zero=True)
    fade_out = _require_finite_number(raw_audio.get("fade_out", 1.5) if raw_audio.get("fade_out") is not None else 1.5, "fade_out", allow_zero=True)

    return {
        "voice": voice_path,
        "bgm": bgm_path,
        "sfx": sfx_path,
        "voice_vol": voice_vol,
        "bgm_vol": bgm_vol,
        "video_vol": video_vol,
        "fade_out": fade_out,
        "keep_video_audio": raw_keep,
    }


def validate_manifest(
    input_path: str | os.PathLike[str],
    scale: float = 1.0,
    fps_override: float | None = None,
) -> dict[str, Any]:
    """Validate a `kinearc.project.json` manifest or `.html` scene and return normalized dimensions/paths."""
    scale_val = _require_finite_number(scale, "scale", allow_zero=False)
    fps_ovr = _require_finite_number(fps_override, "fps", allow_zero=False) if fps_override is not None else None

    try:
        input_path = os.fspath(input_path)
    except TypeError:
        pass
    if not isinstance(input_path, str) or not input_path.strip() or not os.path.isfile(input_path):
        raise FileNotFoundError(f"Manifest or scene file not found: {input_path}")

    abs_p = os.path.abspath(input_path)
    project_dir = os.path.dirname(abs_p)
    ext = os.path.splitext(abs_p)[1].lower()

    if ext in {".html", ".htm"}:
        fps = fps_ovr if fps_ovr is not None else 60.0
        return {
            "kind": "scene",
            "project_dir": project_dir,
            "manifest_path": abs_p,
            "fps": fps,
            "base_width": 1920,
            "base_height": 1080,
            "width": even_dimension(1920 * scale_val),
            "height": even_dimension(1080 * scale_val),
            "scale": scale_val,
            "scenes": [{"path": abs_p, "duration": None}],
            "audio": None,
        }

    if ext != ".json":
        raise ValueError(f"Unsupported input file extension {ext!r} (expected .json or .html/.htm): {abs_p}")

    with open(abs_p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Project manifest must be a JSON object: {abs_p}")

    raw_fps = data.get("fps") if data.get("fps") is not None else 60.0
    fps = fps_ovr if fps_ovr is not None else _require_finite_number(raw_fps, "fps", allow_zero=False)

    raw_w = data.get("width") if data.get("width") is not None else 1920
    raw_h = data.get("height") if data.get("height") is not None else 1080
    w_num = _require_finite_number(raw_w, "width", allow_zero=False)
    h_num = _require_finite_number(raw_h, "height", allow_zero=False)
    base_width = int(round(w_num))
    base_height = int(round(h_num))
    if base_width <= 0 or base_height <= 0:
        raise ValueError(f"Project width and height must be positive integers, got {raw_w!r}x{raw_h!r}")

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or len(raw_scenes) == 0:
        raise ValueError("Project manifest 'scenes' must be a non-empty list.")
    scenes = [_parse_scene_entry(item, project_dir) for item in raw_scenes]

    audio_norm = _parse_audio_config(data.get("audio"), project_dir)

    return {
        "kind": "project",
        "project_dir": project_dir,
        "manifest_path": abs_p,
        "fps": fps,
        "base_width": base_width,
        "base_height": base_height,
        "width": even_dimension(base_width * scale_val),
        "height": even_dimension(base_height * scale_val),
        "scale": scale_val,
        "scenes": scenes,
        "audio": audio_norm,
    }


def find_browser_executable(
    env: Mapping[str, str] | None = None,
    path_exists: Callable[[str], bool] = os.path.isfile,
    which: Callable[[str], str | None] = shutil.which,
    platform: str | None = None,
) -> str | None:
    """Locate Chrome, Edge, or Chromium executable across CHROME_PATH and standard OS paths."""
    active_env = os.environ if env is None else env
    plat = sys.platform if platform is None else platform

    chrome_env = (active_env.get("CHROME_PATH") or "").strip()
    if chrome_env:
        return chrome_env if path_exists(chrome_env) else None

    candidates: list[str] = []
    which_names: list[str] = []

    if plat.startswith("win"):
        pf = active_env.get("PROGRAMFILES") or active_env.get("ProgramFiles") or r"C:\Program Files"
        pfx86 = active_env.get("PROGRAMFILES(X86)") or active_env.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
        local_app = active_env.get("LOCALAPPDATA") or ""
        roots = [r for r in (pf, pfx86, local_app) if r]
        for root in roots:
            candidates.append(ntpath.join(root, "Google", "Chrome", "Application", "chrome.exe"))
        for root in roots:
            candidates.append(ntpath.join(root, "Microsoft", "Edge", "Application", "msedge.exe"))
        which_names = ["chrome", "google-chrome", "msedge", "chromium"]
    elif plat == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        home = (active_env.get("HOME") or "").strip()
        if home:
            candidates.extend(
                [
                    posixpath.join(home, "Applications", "Google Chrome.app", "Contents", "MacOS", "Google Chrome"),
                    posixpath.join(home, "Applications", "Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge"),
                    posixpath.join(home, "Applications", "Chromium.app", "Contents", "MacOS", "Chromium"),
                ]
            )
        which_names = ["google-chrome", "chromium", "microsoft-edge"]
    else:
        which_names = [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "microsoft-edge",
            "microsoft-edge-stable",
        ]
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/microsoft-edge",
            "/snap/bin/chromium",
        ]

    if plat.startswith("linux"):
        for name in which_names:
            found = which(name)
            if found:
                return found

    for path in candidates:
        if path_exists(path):
            return path

    if not plat.startswith("linux"):
        for name in which_names:
            found = which(name)
            if found:
                return found

    return None


def _probe_node(which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    """Probe Node.js binary and parse major version (>= MIN_NODE_MAJOR required)."""
    node_path = which("node")
    node_version: str | None = None
    node_major: int | None = None
    if node_path:
        try:
            proc = subprocess.run(
                [node_path, "-v"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                raw_ver = proc.stdout.strip()
                m = re.match(r"^v?(\d+)(?:\.\d+\.\d+)?", raw_ver)
                if m:
                    node_version = raw_ver
                    node_major = int(m.group(1))
        except (OSError, subprocess.SubprocessError):
            pass

    return {
        "path": node_path,
        "version": node_version,
        "major": node_major,
        "min_major": MIN_NODE_MAJOR,
        "ok": bool(node_path and node_major is not None and node_major >= MIN_NODE_MAJOR),
    }


def run_doctor() -> dict[str, Any]:
    """Probe Python CV deps, FFmpeg/FFprobe, Node.js 24+, Browser, and engine/render.mjs."""
    cv2_ver: str | None = None
    numpy_ver: str | None = None
    try:
        import cv2  # type: ignore[import-not-found]

        cv2_ver = getattr(cv2, "__version__", "unknown")
    except Exception:
        cv2_ver = None
    try:
        import numpy  # type: ignore[import-not-found]

        numpy_ver = getattr(numpy, "__version__", "unknown")
    except Exception:
        numpy_ver = None

    py_info = {
        "version": py_platform.python_version(),
        "executable": sys.executable,
        "cv2": cv2_ver,
        "numpy": numpy_ver,
        "ok": bool(cv2_ver and numpy_ver),
    }

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    ffmpeg_info = {"path": ffmpeg_path, "ok": bool(ffmpeg_path)}
    ffprobe_info = {"path": ffprobe_path, "ok": bool(ffprobe_path)}

    node_info = _probe_node()
    browser_path = find_browser_executable()
    browser_info = {"path": browser_path, "ok": bool(browser_path)}

    engine_ready = bool(os.path.isfile(ENGINE_RENDER))
    all_ok = bool(
        py_info["ok"]
        and ffmpeg_info["ok"]
        and ffprobe_info["ok"]
        and node_info["ok"]
        and browser_info["ok"]
        and engine_ready
    )

    return {
        "python": py_info,
        "ffmpeg": ffmpeg_info,
        "ffprobe": ffprobe_info,
        "node": node_info,
        "browser": browser_info,
        "engine_ready": engine_ready,
        "ok": all_ok,
    }


def _require_engine_and_node() -> str:
    """Verify engine/render.mjs and Node.js executable exist before spawning Node."""
    if not os.path.isfile(ENGINE_RENDER):
        raise FileNotFoundError(
            f"kinearc native render engine not found: {ENGINE_RENDER} (expected engine/render.mjs)."
        )
    node_path = shutil.which("node")
    if not node_path:
        raise FileNotFoundError("Node.js executable ('node') not found on PATH.")
    return node_path


def _engine_env() -> dict[str, str]:
    """Build subprocess environment with CHROME_PATH populated when discoverable."""
    env = os.environ.copy()
    if not (env.get("CHROME_PATH") or "").strip():
        browser = find_browser_executable(env=env)
        if browser:
            env["CHROME_PATH"] = browser
    return env


def _ensure_utf8_stream(stream: Any) -> None:
    """Reconfigure a text stream to UTF-8 with replacement error handling when supported."""
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _write_stdout_utf8(line: str) -> None:
    """Write a line to stdout safely without raising UnicodeEncodeError on non-UTF-8 pipes."""
    try:
        sys.stdout.write(line)
    except UnicodeEncodeError:
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None:
            buf.write(line.encode("utf-8", errors="replace"))
            buf.flush()
            return
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(line.encode(enc, errors="replace").decode(enc, errors="replace"))
    sys.stdout.flush()


def _run_streaming_node(cmd: list[str], env: dict[str, str], *, stream_stdout: bool) -> int:
    """Execute a Node engine command, forwarding stdout line-by-line when requested."""
    if not stream_stdout:
        proc = subprocess.run(cmd, env=env, check=False)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)
        return 0

    _ensure_utf8_stream(sys.stdout)
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    waited_rc: int | None = None
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                _write_stdout_utf8(line)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        raise
    finally:
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass
        try:
            waited_rc = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            waited_rc = proc.wait()

    rc = proc.returncode if getattr(proc, "returncode", None) is not None else waited_rc
    return 1 if rc is None else rc


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run environment diagnostics and print JSON or human-readable summary."""
    report = run_doctor()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        py = report["python"]
        node = report["node"]
        print(f"kinearc Environment Doctor (ok={report['ok']})")
        print(f"  Python : {py['version']} (cv2={py['cv2']}, numpy={py['numpy']}) -> {'OK' if py['ok'] else 'MISSING'}")
        print(f"  FFmpeg : {report['ffmpeg']['path'] or 'not found'} -> {'OK' if report['ffmpeg']['ok'] else 'MISSING'}")
        print(f"  FFprobe: {report['ffprobe']['path'] or 'not found'} -> {'OK' if report['ffprobe']['ok'] else 'MISSING'}")
        print(f"  Node.js: {node['version'] or 'not found'} (min v{node['min_major']}) -> {'OK' if node['ok'] else 'MISSING/OLD'}")
        print(f"  Browser: {report['browser']['path'] or 'not found'} -> {'OK' if report['browser']['ok'] else 'MISSING'}")
        print(f"  Engine : {ENGINE_RENDER} -> {'READY' if report['engine_ready'] else 'NOT BUILT'}")
    if args.strict and not report["ok"]:
        return 1
    return 0


def cmd_stills(args: argparse.Namespace) -> int:
    """Validate scene/scale/times and invoke `node engine/render.mjs stills`."""
    abs_scene = _resolve_existing_file(args.scene, os.getcwd(), "Scene")
    scale_val = _require_finite_number(args.scale, "scale", allow_zero=False)
    raw_times = [t.strip() for t in str(args.times).split(",") if t.strip()]
    if not raw_times:
        raise ValueError("--times must provide at least one timestamp in seconds (e.g. '0,1.5,3.0').")
    for tok in raw_times:
        _require_finite_number(tok, "timestamp", allow_zero=True)

    node_path = _require_engine_and_node()
    cmd = [
        node_path,
        ENGINE_RENDER,
        "stills",
        "--scene",
        abs_scene,
        "--out_dir",
        os.path.abspath(args.out_dir),
        "--times",
        ",".join(raw_times),
        "--scale",
        str(scale_val),
    ]
    return _run_streaming_node(cmd, _engine_env(), stream_stdout=False)


def cmd_render(args: argparse.Namespace) -> int:
    """Validate manifest/assets first, verify engine/render.mjs, then invoke `node engine/render.mjs render`."""
    manifest = validate_manifest(args.project, scale=args.scale, fps_override=args.fps)
    if isinstance(args.crf, bool) or args.crf < 0 or args.crf > 51:
        raise ValueError(f"crf must be an integer in [0, 51], got {args.crf!r}")

    node_path = _require_engine_and_node()
    cmd = [
        node_path,
        ENGINE_RENDER,
        "render",
        "--project",
        manifest["manifest_path"],
        "--out",
        os.path.abspath(args.out),
        "--scale",
        str(manifest["scale"]),
        "--fps",
        str(manifest["fps"]),
        "--crf",
        str(args.crf),
    ]
    if args.json_progress:
        cmd.append("--json-progress")
    return _run_streaming_node(cmd, _engine_env(), stream_stdout=bool(args.json_progress))


def _delegate_to_module(subcommand: str, rest_args: list[str]) -> int:
    """Import and invoke a toolkit script's `main()` with remaining CLI arguments."""
    filename, module_name, _ = PASSTHROUGH_SCRIPTS[subcommand]
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    mod = importlib.import_module(module_name)
    main_fn = getattr(mod, "main")
    sig = inspect.signature(main_fn)
    positional_params = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
    ]
    if positional_params:
        result = main_fn(rest_args)
    else:
        script_path = os.path.join(SCRIPTS_DIR, filename)
        old_argv = sys.argv
        sys.argv = [script_path, *rest_args]
        try:
            result = main_fn()
        finally:
            sys.argv = old_argv
    return int(result) if isinstance(result, int) and not isinstance(result, bool) else 0


def build_parser() -> argparse.ArgumentParser:
    """Create the unified kinearc CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="kinearc_cli.py",
        description="Unified kinearc CLI for environment checks, native HTML/Canvas rendering, CV capture, audio mixing, and workbench UI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="Check Python CV libs, FFmpeg/FFprobe, Node.js 24+, Browser, and engine readiness.")
    p_doc.add_argument("--json", action="store_true", help="Output machine-readable JSON diagnostics")
    p_doc.add_argument("--strict", action="store_true", help="Exit with code 1 if any core dependency is missing")
    p_doc.set_defaults(func=cmd_doctor)

    p_ren = sub.add_parser("render", help="Validate project/scene manifest and render MP4 via engine/render.mjs.")
    p_ren.add_argument("--project", required=True, help="Path to kinearc.project.json or standalone .html scene")
    p_ren.add_argument("--out", required=True, help="Output MP4 file path")
    p_ren.add_argument("--scale", type=float, default=1.0, help="Resolution scale factor (e.g. 2 for 4K)")
    p_ren.add_argument("--fps", type=float, default=None, help="Override FPS (defaults to manifest FPS or 60)")
    p_ren.add_argument("--crf", type=int, default=16, help="H.264 CRF quality (default: 16)")
    p_ren.add_argument("--json-progress", action="store_true", help="Stream newline-delimited JSON progress events")
    p_ren.set_defaults(func=cmd_render)

    p_stills = sub.add_parser("stills", help="Capture deterministic still PNGs at specified timestamps via engine/render.mjs.")
    p_stills.add_argument("--scene", required=True, help="Path to standalone deterministic .html scene")
    p_stills.add_argument("--out_dir", default=".kinearc_analysis/stills", help="Directory to save still PNGs")
    p_stills.add_argument("--times", required=True, help="Comma-separated timestamps in seconds (e.g. 0,1.25,2.5)")
    p_stills.add_argument("--scale", type=float, default=1.0, help="Resolution scale factor (default: 1)")
    p_stills.set_defaults(func=cmd_stills)

    for cmd_name, (_, _, help_text) in PASSTHROUGH_SCRIPTS.items():
        p_pass = sub.add_parser(cmd_name, add_help=False, help=help_text)
        p_pass.add_argument("rest", nargs=argparse.REMAINDER)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint supporting `doctor`, `render`, `stills`, and toolkit passthrough subcommands."""
    _ensure_utf8_stream(sys.stderr)
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if argv_list and argv_list[0] in PASSTHROUGH_SCRIPTS:
        return _delegate_to_module(argv_list[0], argv_list[1:])

    parser = build_parser()
    args = parser.parse_args(argv_list)
    return int(args.func(args))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"[kinearc] Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode or 1)
