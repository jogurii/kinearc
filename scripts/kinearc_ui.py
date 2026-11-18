#!/usr/bin/env python3
"""
kinearc_ui.py — Local Zero-Build Backend & Media Server for kinearc UI
Part of the kinearc skill toolkit.

Zero external web dependencies (uses Python stdlib http.server + OpenCV + NumPy + FFmpeg/FFprobe).
Supports:
- Video-only (`clone.mp4`) and side-by-side reference comparison (`--ref orig.mp4`).
- Live interactive HTML scenes (`--scene path/to/scene.html`) with or without MP4 renders.
- Multi-scene project manifests (`--project kinearc.project.json`).
- Audio waveform peak extraction, pause cutting (`audio_mix.cmd_cut_pauses`),
  and automated BGM auto-ducking / SFX mixing (`audio_mix.cmd_mix`).
- Thread-safe `.kinearc_analysis/selection.json` notes and cropped annotation snapshots.
"""

import argparse
from collections import OrderedDict
import http.server
import json
import math
import mimetypes
import os
import re
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import uuid
import webbrowser

import cv2
import numpy as np

try:
    import audio_mix
except ImportError:
    from . import audio_mix


PLACEHOLDER_HTML = (
    "<!doctype html><html><head><title>kinearc</title></head>"
    "<body>kinearc UI backend ready</body></html>"
)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
CLI_SCRIPT = os.path.join(SCRIPTS_DIR, "kinearc_cli.py")
ENGINE_RENDER = os.path.join(REPO_ROOT, "engine", "render.mjs")
UI_DIR = os.path.realpath(os.path.join(SCRIPTS_DIR, "ui"))

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def _guess_mime(file_path: str, fallback: str = "application/octet-stream") -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in MIME_TYPES:
        return MIME_TYPES[ext]
    guessed, _ = mimetypes.guess_type(file_path)
    return guessed or fallback


def _read_optional_json(path: str):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _valid_fps(raw_fps, fallback: float = 30.0) -> float:
    """Return raw_fps as float if finite and > 0, otherwise fallback."""
    if isinstance(raw_fps, bool):
        return fallback
    try:
        val = float(raw_fps)
    except (TypeError, ValueError):
        return fallback
    return val if math.isfinite(val) and val > 0 else fallback


def _is_finite_number(val) -> bool:
    """Return True if val is an int/float (excluding bool) and finite."""
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)


def _is_under_root(root_real: str, target_real: str) -> bool:
    """Return True when target_real is under root_real (safe across Windows drive letters)."""
    try:
        return os.path.commonpath([root_real, target_real]) == root_real
    except ValueError:
        return False


def _safe_resolve_under(root_dir: str, raw_relpath: str, single_level: bool = False) -> tuple[str | None, str | None]:
    """Resolve a URL relative path inside root_dir; returns (abs_path, err_status_msg)."""
    if not root_dir:
        return None, "missing"
    rel = urllib.parse.unquote(raw_relpath or "")
    if "\x00" in rel:
        return None, "forbidden"
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel:
        return None, "missing"
    if ":" in rel.split("/")[0]:
        return None, "forbidden"
    parts = [p for p in rel.split("/") if p != ""]
    if any(p == ".." for p in parts):
        return None, "forbidden"
    if single_level and len(parts) != 1:
        return None, "forbidden"

    root_real = os.path.realpath(root_dir)
    candidate = os.path.realpath(os.path.join(root_real, *parts))
    if not _is_under_root(root_real, candidate):
        return None, "forbidden"
    if candidate == root_real:
        return None, "missing"
    return candidate, None


def _unique_output_path(directory: str, stem: str, ext: str, avoid_path: str | None = None) -> str:
    candidate = os.path.join(directory, f"{stem}{ext}")
    avoid_abs = os.path.abspath(avoid_path) if avoid_path else None
    if avoid_abs is None or os.path.abspath(candidate) != avoid_abs:
        return candidate
    idx = 2
    while True:
        alt = os.path.join(directory, f"{stem}_{idx}{ext}")
        if os.path.abspath(alt) != avoid_abs:
            return alt
        idx += 1


def _parse_positive_number(raw_val, label: str) -> float:
    """Validate and return a finite number > 0 (rejects bool, NaN, Inf, <= 0)."""
    if isinstance(raw_val, bool):
        raise ValueError(f"{label} must be a positive number, got bool")
    try:
        val = float(raw_val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive number, got {raw_val!r}") from exc
    if not math.isfinite(val) or val <= 0:
        raise ValueError(f"{label} must be finite and > 0, got {raw_val!r}")
    return val


def _parse_non_negative_number(raw_val, label: str) -> float:
    """Validate and return a finite number >= 0 (rejects bool, NaN, Inf, < 0)."""
    if isinstance(raw_val, bool):
        raise ValueError(f"{label} must be a non-negative number, got bool")
    try:
        val = float(raw_val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative number, got {raw_val!r}") from exc
    if not math.isfinite(val) or val < 0:
        raise ValueError(f"{label} must be finite and >= 0, got {raw_val!r}")
    return val


def _parse_render_times(payload: dict) -> str:
    """Parse 'times' (list or CSV) or 'time_sec' into a normalized CSV string."""
    if "times" in payload and payload["times"] is not None:
        raw_times = payload["times"]
        if isinstance(raw_times, list):
            tokens = raw_times
        elif isinstance(raw_times, str):
            tokens = [tok.strip() for tok in raw_times.split(",") if tok.strip()]
        else:
            raise ValueError("'times' must be a list or comma-separated string of timestamps")
        if not tokens:
            raise ValueError("'times' must include at least one timestamp >= 0")
        parsed = [_parse_non_negative_number(tok, "timestamp") for tok in tokens]
        return ",".join(str(int(v)) if v.is_integer() else str(v) for v in parsed)

    if "time_sec" in payload and payload["time_sec"] is not None:
        t_val = _parse_non_negative_number(payload["time_sec"], "time_sec")
        return str(int(t_val)) if t_val.is_integer() else str(t_val)

    return "0"


def _resolve_render_mp4_output(renders_dir: str, req_out, job_id: str) -> tuple[str, str]:
    """Validate optional MP4 output filename and confine it inside renders_dir."""
    if req_out is None or (isinstance(req_out, str) and not req_out.strip()):
        out_name = f"render_{job_id}.mp4"
    else:
        if not isinstance(req_out, str):
            raise ValueError("Output filename 'out' must be a string")
        raw = req_out.strip()
        if "\x00" in raw or "/" in raw or "\\" in raw or ".." in raw or ":" in raw:
            raise ValueError(f"Invalid output filename: {req_out}")
        stem, ext = os.path.splitext(raw)
        if not stem or stem in {".", ".."}:
            raise ValueError(f"Invalid output filename: {req_out}")
        if not ext:
            out_name = f"{raw}.mp4"
        elif ext.lower() == ".mp4":
            out_name = raw
        else:
            raise ValueError(f"Output filename must end with .mp4 (got {req_out!r})")

    target, err = _safe_resolve_under(renders_dir, out_name, single_level=True)
    if err or not target:
        raise ValueError(f"Invalid output filename: {req_out}")
    return target, out_name


def extract_waveform_peaks(audio_path: str, bins: int = 800) -> dict:
    """Decode audio to 8kHz mono f32le PCM via FFmpeg and compute normalized peak bins."""
    if not audio_path or not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    if not isinstance(bins, int) or isinstance(bins, bool) or bins <= 0:
        raise ValueError(f"bins must be a positive integer (got {bins!r})")

    try:
        duration_sec = audio_mix.get_duration(audio_path)
    except (ValueError, subprocess.CalledProcessError):
        duration_sec = 0.0

    cmd = [
        "ffmpeg", "-v", "error",
        "-i", audio_path,
        "-ac", "1",
        "-ar", "8000",
        "-f", "f32le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg waveform extraction failed: {err_msg or f'exit {proc.returncode}'}")

    raw_bytes = proc.stdout
    usable = len(raw_bytes) - (len(raw_bytes) % 4)
    if usable <= 0:
        return {"bins": [0.0] * bins, "duration_sec": round(float(duration_sec), 4), "max_peak": 0.0}

    samples = np.frombuffer(raw_bytes[:usable], dtype="<f4")
    abs_samples = np.nan_to_num(np.abs(samples), nan=0.0, posinf=0.0, neginf=0.0)
    n = int(abs_samples.size)
    if n == 0:
        return {"bins": [0.0] * bins, "duration_sec": round(float(duration_sec), 4), "max_peak": 0.0}

    if duration_sec <= 0.0:
        duration_sec = n / 8000.0

    raw_peaks = np.zeros(bins, dtype=np.float32)
    for b in range(bins):
        i0 = min(n - 1, int(b * n / bins))
        i1 = max(i0 + 1, min(n, int((b + 1) * n / bins)))
        raw_peaks[b] = float(np.max(abs_samples[i0:i1]))

    max_peak = float(np.max(raw_peaks))
    if max_peak > 0.0:
        norm_bins = [min(1.0, max(0.0, round(float(v / max_peak), 6))) for v in raw_peaks]
    else:
        norm_bins = [0.0] * bins

    return {
        "bins": norm_bins,
        "duration_sec": round(float(duration_sec), 4),
        "max_peak": round(max_peak, 6),
    }


class UiState:
    """Shared server state for video/scene inspection, audio processing, and selection notes."""

    def __init__(
        self,
        clone_path: str | None = None,
        ref_path: str | None = None,
        scene_path: str | None = None,
        project_path: str | None = None,
        out_dir: str = ".kinearc_analysis",
        voice_path: str | None = None,
        bgm_path: str | None = None,
        sfx_path: str | None = None,
    ):
        if not clone_path and not scene_path and not project_path:
            raise ValueError("At least one source (clone_path, scene_path, or project_path) must be provided.")

        self.out_dir = os.path.abspath(out_dir)
        self.sel_dir = os.path.join(self.out_dir, "selection")
        self.sel_json = os.path.join(self.out_dir, "selection.json")
        self.renders_dir = os.path.join(self.out_dir, "renders")
        self.cuts_dir = os.path.join(self.out_dir, "cuts")
        os.makedirs(self.sel_dir, exist_ok=True)
        self.lock = threading.Lock()
        self.render_jobs: dict[str, dict] = {}
        self.render_jobs_lock = threading.Lock()
        self._cap_cache: dict[str, dict] = {}
        self._bgr_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._encoded_cache: OrderedDict[tuple, tuple[bytes, str]] = OrderedDict()

        self.project_path = os.path.abspath(project_path) if project_path else None
        project_data = self._load_project_manifest(self.project_path) if self.project_path else {}
        proj_dir = os.path.dirname(self.project_path) if self.project_path else None

        def _resolve(p: str | None, base_dir: str | None = None) -> str | None:
            if not p:
                return None
            if os.path.isabs(p) or not base_dir:
                return os.path.abspath(p)
            return os.path.abspath(os.path.join(base_dir, p))

        raw_clone = clone_path or project_data.get("clone") or project_data.get("video") or project_data.get("clone_path")
        raw_ref = ref_path or project_data.get("ref") or project_data.get("ref_path")
        self.clone_path = _resolve(raw_clone, proj_dir if not clone_path else None)
        self.ref_path = _resolve(raw_ref, proj_dir if not ref_path else None)

        audio_cfg = project_data.get("audio") if isinstance(project_data.get("audio"), dict) else {}
        raw_voice = voice_path or audio_cfg.get("voice") or audio_cfg.get("voice_path")
        raw_bgm = bgm_path or audio_cfg.get("bgm") or audio_cfg.get("bgm_path")
        raw_sfx = sfx_path or audio_cfg.get("sfx") or audio_cfg.get("sfx_path")
        self.voice_path = _resolve(raw_voice, proj_dir if not voice_path else None)
        self.bgm_path = _resolve(raw_bgm, proj_dir if not bgm_path else None)
        self.sfx_path = _resolve(raw_sfx, proj_dir if not sfx_path else None)

        self.scene_path = os.path.abspath(scene_path) if scene_path else None
        if self.scene_path and not os.path.isfile(self.scene_path):
            raise FileNotFoundError(f"Scene file not found: {self.scene_path}")

        self.scene_root: str | None = None
        self.scenes: list[dict] = []
        self.live_scene_url: str | None = None
        self._video_has_audio_path: str | None = None
        self._video_has_audio: bool = False
        self._init_scenes(project_data, proj_dir)

        self._load_sidecars()
        self._init_media_geometry(project_data)
        self.has_video_audio()

    def _load_project_manifest(self, path: str) -> dict:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Project manifest not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Project manifest must be a JSON object: {path}")
        return data

    def _init_scenes(self, project_data: dict, proj_dir: str | None) -> None:
        raw_scenes = project_data.get("scenes") if isinstance(project_data.get("scenes"), list) else []
        resolved_scenes: list[tuple[dict, str]] = []
        for item in raw_scenes:
            if isinstance(item, str):
                abs_p = item if os.path.isabs(item) or not proj_dir else os.path.abspath(os.path.join(proj_dir, item))
                entry = {"name": os.path.splitext(os.path.basename(abs_p))[0]}
                resolved_scenes.append((entry, abs_p))
            elif isinstance(item, dict):
                raw_p = item.get("path") or item.get("file") or item.get("src") or item.get("html")
                if not raw_p:
                    continue
                abs_p = raw_p if os.path.isabs(raw_p) or not proj_dir else os.path.abspath(os.path.join(proj_dir, raw_p))
                entry = {k: v for k, v in item.items() if k not in {"path", "file", "src", "html"}}
                entry.setdefault("name", item.get("title") or os.path.splitext(os.path.basename(abs_p))[0])
                resolved_scenes.append((entry, abs_p))

        if self.scene_path is None and resolved_scenes:
            self.scene_path = resolved_scenes[0][1]

        if proj_dir and (resolved_scenes or self.scene_path):
            proj_real = os.path.realpath(proj_dir)
            if self.scene_path and _is_under_root(proj_real, os.path.realpath(self.scene_path)):
                self.scene_root = proj_real
            elif resolved_scenes:
                self.scene_root = proj_real
            elif self.scene_path:
                self.scene_root = os.path.realpath(os.path.dirname(self.scene_path))
        elif self.scene_path:
            self.scene_root = os.path.realpath(os.path.dirname(self.scene_path))

        if self.scene_root:
            for entry, abs_p in resolved_scenes:
                abs_real = os.path.realpath(abs_p)
                if _is_under_root(self.scene_root, abs_real):
                    rel = os.path.relpath(abs_real, self.scene_root).replace("\\", "/")
                    entry["path"] = rel
                    entry["url"] = f"/api/scene/{rel}"
                    self.scenes.append(entry)

            if self.scene_path:
                scene_real = os.path.realpath(self.scene_path)
                if _is_under_root(self.scene_root, scene_real):
                    rel = os.path.relpath(scene_real, self.scene_root).replace("\\", "/")
                    self.live_scene_url = f"/api/scene/{rel}"
                    if not self.scenes:
                        self.scenes.append({
                            "name": os.path.splitext(os.path.basename(rel))[0],
                            "path": rel,
                            "url": self.live_scene_url,
                        })

    def _load_sidecars(self) -> None:
        cuts_raw = _read_optional_json(os.path.join(self.out_dir, "scene_cuts.json"))
        if isinstance(cuts_raw, dict):
            self.scene_cuts = list(cuts_raw.get("cuts") or [])
        elif isinstance(cuts_raw, list):
            self.scene_cuts = cuts_raw
        else:
            self.scene_cuts = []

        vrep = _read_optional_json(os.path.join(self.out_dir, "verification_report.json"))
        if isinstance(vrep, dict):
            self.worst_frames = list(vrep.get("worst_frames") or [])
            self.clone_loop_mae = vrep.get("clone_loop_mae")
            self.overall_mae = vrep.get("overall_mae")
            self.overall_psnr_db = vrep.get("overall_psnr_db")
        else:
            self.worst_frames = []
            self.clone_loop_mae = None
            self.overall_mae = None
            self.overall_psnr_db = None

        meta = _read_optional_json(os.path.join(self.out_dir, "metadata.json"))
        if isinstance(meta, dict):
            self.source_loop_mae = meta.get("source_loop_mae")
            self.metadata_fps = meta.get("fps")
            self.working_size = meta.get("working_size")
        else:
            self.source_loop_mae = None
            self.metadata_fps = None
            self.working_size = None

        sfx_raw = _read_optional_json(self.sfx_path) if self.sfx_path else None
        if isinstance(sfx_raw, list):
            self.sfx_cues = sfx_raw
        elif isinstance(sfx_raw, dict):
            self.sfx_cues = list(sfx_raw.get("cues") or [])
        else:
            self.sfx_cues = []

    def _init_media_geometry(self, project_data: dict) -> None:
        self.ref_fps = 30.0
        if self.clone_path:
            cap = cv2.VideoCapture(self.clone_path)
            if not cap.isOpened():
                raise RuntimeError(f"Could not open video: {self.clone_path}")
            try:
                raw_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                raw_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                raw_fps = cap.get(cv2.CAP_PROP_FPS)
                raw_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            finally:
                cap.release()
            self.width = int(raw_w) if math.isfinite(raw_w) else 0
            self.height = int(raw_h) if math.isfinite(raw_h) else 0
            if self.width <= 0 or self.height <= 0:
                raise ValueError(f"Invalid video dimensions ({self.width}x{self.height}) for: {self.clone_path}")
            self.fps = _valid_fps(raw_fps, 30.0)
            self.total_frames = max(0, int(raw_frames)) if math.isfinite(raw_frames) else 0
            self.duration_sec = (self.total_frames / self.fps) if self.fps > 0 else 0.0
            self.ref_fps = self.fps
        else:
            ws = self.working_size if isinstance(self.working_size, list) and len(self.working_size) == 2 else None
            raw_w = project_data["width"] if project_data.get("width") is not None else (ws[0] if ws else 1920)
            raw_h = project_data["height"] if project_data.get("height") is not None else (ws[1] if ws else 1080)
            if isinstance(raw_w, bool) or isinstance(raw_h, bool):
                raise ValueError(f"Invalid project dimensions: {raw_w!r}x{raw_h!r}")
            try:
                self.width = int(raw_w)
                self.height = int(raw_h)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid project dimensions: {raw_w!r}x{raw_h!r}") from exc
            if self.width <= 0 or self.height <= 0:
                raise ValueError(f"Project dimensions must be positive (got {self.width}x{self.height})")
            raw_fps = project_data.get("fps") if project_data.get("fps") is not None else self.metadata_fps
            self.fps = _valid_fps(raw_fps, 30.0)
            dur = project_data.get("duration_sec") if project_data.get("duration_sec") is not None else project_data.get("duration")
            if dur is not None:
                if isinstance(dur, bool):
                    raise ValueError(f"Invalid duration_sec: {dur!r}")
                dur_val = float(dur)
                if not math.isfinite(dur_val) or dur_val < 0:
                    raise ValueError(f"Invalid duration_sec: {dur!r}")
                self.duration_sec = dur_val
                self.total_frames = max(0, int(round(self.duration_sec * self.fps)))
            elif project_data.get("total_frames") is not None:
                if isinstance(project_data["total_frames"], bool):
                    raise ValueError("Invalid total_frames")
                self.total_frames = max(0, int(project_data["total_frames"]))
                self.duration_sec = (self.total_frames / self.fps) if self.fps > 0 else 0.0
            else:
                self.total_frames = 0
                self.duration_sec = 0.0
            self.ref_fps = self.fps

        if self.ref_path:
            rcap = cv2.VideoCapture(self.ref_path)
            if rcap.isOpened():
                try:
                    raw_ref_fps = rcap.get(cv2.CAP_PROP_FPS)
                finally:
                    rcap.release()
                self.ref_fps = _valid_fps(raw_ref_fps, 30.0)
            else:
                self.ref_path = None

    def read_notes(self) -> list[dict]:
        if not os.path.exists(self.sel_json):
            return []
        with open(self.sel_json, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_notes(self, notes: list[dict]) -> None:
        with open(self.sel_json, "w", encoding="utf-8") as f:
            json.dump(notes, f, indent=2)

    def _file_sig(self, path: str | None) -> tuple[str, int, int] | None:
        if not path:
            return None
        try:
            st = os.stat(path)
            return (path, int(st.st_mtime_ns), int(st.st_size))
        except OSError:
            return None

    def clear_frame_caches(self) -> None:
        for entry in self._cap_cache.values():
            cap = entry.get("cap")
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
        self._cap_cache.clear()
        self._bgr_cache.clear()
        self._encoded_cache.clear()

    def get_frame_bgr(self, src: str, frame_idx: int) -> np.ndarray | None:
        if frame_idx < 0 or (self.total_frames > 0 and frame_idx >= self.total_frames):
            return None
        if src == "diff":
            return self.get_diff_frame_bgr(frame_idx)
        if src == "clone":
            path = self.clone_path
            target_idx = frame_idx
        elif src == "ref":
            path = self.ref_path
            t_sec = frame_idx / (self.fps if self.fps > 0 else 30.0)
            target_idx = max(0, int(round(t_sec * self.ref_fps)))
        else:
            return None

        if not path:
            return None

        sig = self._file_sig(path)
        bgr_key = (src, target_idx, sig, self.width, self.height) if sig is not None else None
        if bgr_key is not None and bgr_key in self._bgr_cache:
            self._bgr_cache.move_to_end(bgr_key)
            return self._bgr_cache[bgr_key]

        entry = self._cap_cache.get(src)
        cap = None
        if (
            entry is not None
            and sig is not None
            and entry.get("sig") == sig
            and entry.get("cap_cls") is cv2.VideoCapture
            and entry.get("cap") is not None
            and entry["cap"].isOpened()
        ):
            cap = entry["cap"]
        else:
            if entry is not None and entry.get("cap") is not None:
                try:
                    entry["cap"].release()
                except Exception:
                    pass
                self._cap_cache.pop(src, None)
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return None
            entry = {
                "sig": sig,
                "cap": cap,
                "next_idx": 0,
                "cap_cls": cv2.VideoCapture,
            }
            if sig is not None:
                self._cap_cache[src] = entry

        if entry["next_idx"] != target_idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
        ok, img = cap.read()
        if not ok or img is None:
            try:
                cap.release()
            except Exception:
                pass
            self._cap_cache.pop(src, None)
            return None

        entry["next_idx"] = target_idx + 1
        if sig is None:
            try:
                cap.release()
            except Exception:
                pass

        if img.shape[1] != self.width or img.shape[0] != self.height:
            img = cv2.resize(img, (self.width, self.height), interpolation=cv2.INTER_AREA)

        if bgr_key is not None:
            self._bgr_cache[bgr_key] = img
            while len(self._bgr_cache) > 96:
                self._bgr_cache.popitem(last=False)
        return img

    def get_encoded_frame(self, kind: str, f_idx: int, fmt_l: str) -> tuple[bytes, str] | None:
        clone_sig = self._file_sig(self.clone_path)
        ref_sig = self._file_sig(self.ref_path) if kind in {"ref", "diff"} else None
        enc_key = (kind, f_idx, fmt_l, clone_sig, ref_sig, self.width, self.height)
        if clone_sig is not None and enc_key in self._encoded_cache:
            self._encoded_cache.move_to_end(enc_key)
            return self._encoded_cache[enc_key]

        img = self.get_frame_bgr(kind, f_idx)
        if img is None:
            return None

        if fmt_l == "png":
            ok, buf = cv2.imencode(".png", img)
            ctype = "image/png"
        else:
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            ctype = "image/jpeg"
        if not ok:
            return None

        result = (buf.tobytes(), ctype)
        if clone_sig is not None:
            self._encoded_cache[enc_key] = result
            while len(self._encoded_cache) > 360:
                self._encoded_cache.popitem(last=False)
        return result

    def get_diff_frame_bgr(self, frame_idx: int) -> np.ndarray | None:
        """Compute 4x amplified absolute pixel error heatmap (COLORMAP_JET) between ref and clone."""
        if not self.clone_path or not self.ref_path:
            return None
        clone_img = self.get_frame_bgr("clone", frame_idx)
        ref_img = self.get_frame_bgr("ref", frame_idx)
        if clone_img is None or ref_img is None:
            return None
        err = np.mean(np.abs(ref_img.astype(np.float32) - clone_img.astype(np.float32)), axis=2)
        amp = np.clip(err * 4.0, 0, 255).astype(np.uint8)
        return cv2.applyColorMap(amp, cv2.COLORMAP_JET)

    def save_note_snapshot(self, note_id: int, frame_idx: int, bbox, point) -> str:
        clone_img = self.get_frame_bgr("clone", frame_idx)
        if clone_img is None:
            return ""
        annotated = clone_img.copy()
        color = (122, 93, 255)
        if bbox:
            x0, y0, x1, y1 = [int(round(v)) for v in bbox]
            cv2.rectangle(annotated, (x0, y0), (x1, y1), color, max(3, self.width // 240))
            cv2.putText(annotated, f"#{note_id}", (x0 + 6, max(28, y0 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        elif point:
            px, py = [int(round(v)) for v in point]
            cv2.circle(annotated, (px, py), max(12, self.width // 60), color, max(3, self.width // 240))
            cv2.putText(annotated, f"#{note_id}", (px + 14, py + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        if self.ref_path:
            ref_img = self.get_frame_bgr("ref", frame_idx)
            if ref_img is not None:
                cv2.putText(ref_img, f"ORIG f{frame_idx}", (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 220, 100), 2)
                cv2.putText(annotated, f"CLONE #{note_id}", (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
                annotated = np.hstack([ref_img, annotated])

        rel_path = f"selection/note_{note_id}.png"
        abs_path = os.path.join(self.sel_dir, f"note_{note_id}.png")
        cv2.imwrite(abs_path, annotated)
        return rel_path

    def has_video_audio(self) -> bool:
        """Return cached whether clone_path has an audio stream, updating when clone_path changes."""
        with self.lock:
            clone_p = self.clone_path
            cached_p = self._video_has_audio_path
            cached_val = self._video_has_audio
        if not clone_p or not os.path.isfile(clone_p):
            with self.lock:
                self._video_has_audio_path = clone_p
                self._video_has_audio = False
            return False
        if cached_p != clone_p:
            try:
                detected = bool(audio_mix.has_audio_stream(clone_p))
            except (OSError, subprocess.SubprocessError):
                detected = False
            with self.lock:
                if self.clone_path == clone_p:
                    self._video_has_audio_path = clone_p
                    self._video_has_audio = detected
            return detected
        return cached_val

    def load_rendered_video(self, video_path: str) -> dict:
        """Load or hot-swap clone_path to a rendered MP4 and return refreshed info payload."""
        if not video_path or not isinstance(video_path, str):
            raise ValueError("video_path must be a non-empty string")
        abs_video = os.path.abspath(video_path)
        with self.lock:
            if not os.path.isfile(abs_video):
                raise FileNotFoundError(f"Rendered video not found: {abs_video}")
            snapshot = {
                "clone_path": self.clone_path,
                "ref_path": self.ref_path,
                "ref_fps": self.ref_fps,
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "total_frames": self.total_frames,
                "duration_sec": self.duration_sec,
                "_video_has_audio_path": self._video_has_audio_path,
                "_video_has_audio": self._video_has_audio,
            }
            self.clone_path = abs_video
            self._video_has_audio_path = None
            self._video_has_audio = False
            try:
                self._init_media_geometry({})
                self.clear_frame_caches()
            except Exception:
                for attr, val in snapshot.items():
                    setattr(self, attr, val)
                raise
        return self.build_info_payload()

    def build_info_payload(self) -> dict:
        video_audio = self.has_video_audio()
        with self.lock:
            has_video = bool(self.clone_path)
            has_ref = bool(self.ref_path)
            has_live = bool(self.live_scene_url)
            width = self.width
            height = self.height
            fps = self.fps
            total_frames = self.total_frames
            duration_sec = round(self.duration_sec, 4)
            live_scene_url = self.live_scene_url
            scenes = self.scenes
            voice_p = self.voice_path
            bgm_p = self.bgm_path
            sfx_p = self.sfx_path
        has_render_engine = os.path.isfile(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine", "render.mjs")
        )
        return {
            "has_video": has_video,
            "has_ref": has_ref,
            "hasRef": has_ref,
            "has_live_scene": has_live,
            "has_render_engine": has_render_engine,
            "mode_default": "live" if (has_live and not has_video) else "clone",
            "width": width,
            "height": height,
            "fps": fps,
            "totalFrames": total_frames,
            "total_frames": total_frames,
            "duration_sec": duration_sec,
            "live_scene_url": live_scene_url,
            "scenes": scenes,
            "scene_cuts": self.scene_cuts,
            "worst_frames": self.worst_frames,
            "source_loop_mae": self.source_loop_mae,
            "clone_loop_mae": self.clone_loop_mae,
            "overall_mae": self.overall_mae,
            "overall_psnr_db": self.overall_psnr_db,
            "sfx_cues": self.sfx_cues,
            "audio": {
                "voice": bool(voice_p and os.path.isfile(voice_p)),
                "bgm": bool(bgm_p and os.path.isfile(bgm_p)),
                "sfx": bool(sfx_p and os.path.isfile(sfx_p)),
                "video": video_audio,
                "voice_path": voice_p,
                "bgm_path": bgm_p,
                "sfx_path": sfx_p,
            },
            "out_dir": self.out_dir,
        }


def _execute_render_job(
    state: UiState,
    job_id: str,
    mode: str,
    cmd: list[str],
    out_abs: str | None = None,
    out_name: str | None = None,
    stills_dir: str | None = None,
    stills_subdir: str | None = None,
) -> None:
    """Run kinearc_cli render/stills in a background thread and update UiState.render_jobs."""
    log_tail: list[str] = []
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
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
        rc = None
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                parsed = None
                if line.startswith("{"):
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        parsed = None
                if isinstance(parsed, dict) and parsed.get("type") == "progress":
                    with state.render_jobs_lock:
                        job = state.render_jobs.get(job_id)
                        if job is not None:
                            if _is_finite_number(parsed.get("frame")):
                                job["frame"] = max(0, int(parsed["frame"]))
                            if _is_finite_number(parsed.get("total")):
                                job["total"] = max(0, int(parsed["total"]))
                            if _is_finite_number(parsed.get("progress")):
                                job["progress"] = min(100.0, max(0.0, float(parsed["progress"])))
                elif isinstance(parsed, dict) and parsed.get("type") == "done":
                    with state.render_jobs_lock:
                        job = state.render_jobs.get(job_id)
                        if job is not None and _is_finite_number(parsed.get("frames")):
                            frames_cnt = max(0, int(parsed["frames"]))
                            job["frame"] = max(job["frame"], frames_cnt)
                            job["total"] = max(job["total"], frames_cnt)
                else:
                    log_tail.append(line)
                    if len(log_tail) > 20:
                        log_tail.pop(0)
        except Exception:
            if proc.poll() is None:
                proc.kill()
            raise
        finally:
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except OSError:
                    pass
            if proc.poll() is None:
                try:
                    rc = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    rc = proc.wait()
            else:
                rc = proc.wait()

        if rc != 0:
            err_msg = "\n".join(log_tail[-5:]) or f"Render process exited with code {rc}"
            with state.render_jobs_lock:
                job = state.render_jobs.get(job_id)
                if job is not None:
                    job["status"] = "error"
                    job["error"] = err_msg
            return

        if mode == "mp4":
            if not out_abs or not os.path.isfile(out_abs) or os.path.getsize(out_abs) <= 0:
                with state.render_jobs_lock:
                    job = state.render_jobs.get(job_id)
                    if job is not None:
                        job["status"] = "error"
                        job["error"] = "Render completed but output MP4 is missing or empty"
                return
            with state.render_jobs_lock:
                job = state.render_jobs.get(job_id)
                if job is not None:
                    job["status"] = "done"
                    job["progress"] = 100.0
                    if job["total"] > 0 and job["frame"] < job["total"]:
                        job["frame"] = job["total"]
                    job["out"] = f"renders/{out_name}"
                    job["url"] = f"/renders/{out_name}"
                    job["error"] = None
            return

        pngs = sorted(
            f for f in os.listdir(stills_dir or "")
            if f.lower().endswith(".png") and os.path.isfile(os.path.join(stills_dir or "", f))
        )
        if not pngs:
            with state.render_jobs_lock:
                job = state.render_jobs.get(job_id)
                if job is not None:
                    job["status"] = "error"
                    job["error"] = "Still capture completed but no PNG files were generated"
            return

        still_items = [
            {"out": f"renders/{stills_subdir}/{fn}", "url": f"/renders/{stills_subdir}/{fn}"}
            for fn in pngs
        ]
        with state.render_jobs_lock:
            job = state.render_jobs.get(job_id)
            if job is not None:
                job["status"] = "done"
                job["progress"] = 100.0
                job["frame"] = len(still_items)
                job["total"] = len(still_items)
                job["out"] = still_items[0]["out"]
                job["url"] = still_items[0]["url"]
                job["stills"] = still_items
                job["error"] = None
    except Exception as exc:
        with state.render_jobs_lock:
            job = state.render_jobs.get(job_id)
            if job is not None:
                job["status"] = "error"
                job["error"] = str(exc)


def make_handler(state: UiState):
    """Build HTTP request handler class bound to a UiState instance."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send_json(self, code: int, obj) -> None:
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._safe_write(data)

        def send_bytes(self, code: int, data: bytes, content_type: str, cache_control: str = "no-store") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if cache_control:
                self.send_header("Cache-Control", cache_control)
            self.end_headers()
            self._safe_write(data)

        def _safe_write(self, data: bytes) -> bool:
            try:
                self.wfile.write(data)
                return True
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return False

        def _read_json_body(self) -> tuple[dict | None, str | None]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None, "Invalid Content-Length header"
            raw = self.rfile.read(max(0, length))
            if not raw:
                return {}, None
            try:
                obj = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return None, f"Invalid JSON payload: {exc}"
            if not isinstance(obj, dict):
                return None, "Request JSON body must be an object"
            return obj, None

        def stream_file_range(self, file_path: str, content_type: str, cache_control: str | None = None) -> None:
            size = os.path.getsize(file_path)
            range_hdr = self.headers.get("Range")
            if range_hdr:
                m = re.match(r"bytes=(\d+)-(\d*)", range_hdr)
                if m:
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                    end = min(end, size - 1)
                    if size == 0 or start >= size or start > end:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    length = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", str(length))
                    if cache_control:
                        self.send_header("Cache-Control", cache_control)
                    self.end_headers()
                    with open(file_path, "rb") as f:
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk = f.read(min(65536, remaining))
                            if not chunk:
                                break
                            if not self._safe_write(chunk):
                                break
                            remaining -= len(chunk)
                    return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            if cache_control:
                self.send_header("Cache-Control", cache_control)
            self.end_headers()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    if not self._safe_write(chunk):
                        break

        def _serve_confined(self, root_dir: str | None, raw_rel: str, single_level: bool = False, stream: bool = False) -> None:
            target, err = _safe_resolve_under(root_dir or "", raw_rel, single_level=single_level)
            if err == "forbidden":
                self.send_json(403, {"error": "Access denied"})
                return
            if err == "missing" or not target or not os.path.isfile(target):
                self.send_json(404, {"error": "File not found"})
                return
            mime = _guess_mime(target)
            if stream:
                self.stream_file_range(target, mime, cache_control="no-store")
                return
            with open(target, "rb") as f:
                data = f.read()
            self.send_bytes(200, data, mime, cache_control="no-store")

        def _handle_frame_request(self, kind: str, idx_raw: str, fmt: str) -> None:
            if kind not in {"clone", "ref", "diff"}:
                self.send_json(400, {"error": f"Invalid frame kind: {kind}"})
                return
            fmt_l = fmt.lower()
            if fmt_l not in {"jpg", "jpeg", "png"}:
                self.send_json(400, {"error": f"Invalid format: {fmt}"})
                return
            try:
                f_idx = int(idx_raw)
            except (TypeError, ValueError):
                self.send_json(400, {"error": f"Invalid frame index: {idx_raw}"})
                return

            with state.lock:
                encoded = state.get_encoded_frame(kind, f_idx, fmt_l)
            if encoded is None:
                self.send_json(404, {"error": f"Frame {f_idx} ({kind}) not available"})
                return

            raw_bytes, ctype = encoded
            self.send_bytes(200, raw_bytes, ctype, cache_control="no-store")

        def _handle_audio_peaks(self, query: dict[str, list[str]]) -> None:
            track = query.get("track", ["voice"])[0]
            if track not in {"voice", "bgm", "video"}:
                self.send_json(400, {"error": f"Unsupported track: {track}"})
                return
            bins_raw = query.get("bins", ["800"])[0]
            try:
                bins = int(bins_raw)
            except ValueError:
                self.send_json(400, {"error": f"Invalid bins parameter: {bins_raw}"})
                return
            if bins <= 0 or bins > 20000:
                self.send_json(400, {"error": f"bins must be between 1 and 20000 (got {bins})"})
                return

            with state.lock:
                if track == "voice":
                    track_path = state.voice_path
                elif track == "bgm":
                    track_path = state.bgm_path
                else:
                    track_path = state.clone_path

            if not track_path or not os.path.isfile(track_path):
                self.send_json(404, {"error": f"Track '{track}' is not configured"})
                return

            if track == "video":
                try:
                    has_vid_audio = audio_mix.has_audio_stream(track_path)
                except Exception as exc:
                    self.send_json(500, {"error": f"Failed to probe video audio stream: {exc}"})
                    return
                if not has_vid_audio:
                    self.send_json(404, {"error": "Track 'video' has no audio stream"})
                    return

            try:
                result = extract_waveform_peaks(track_path, bins=bins)
            except FileNotFoundError as exc:
                self.send_json(404, {"error": str(exc)})
                return
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            except Exception as exc:
                self.send_json(500, {"error": str(exc)})
                return
            self.send_json(200, result)

        def _handle_cut_pauses(self, payload: dict) -> None:
            track = payload.get("track", "voice")
            explicit_input = payload.get("input")
            with state.lock:
                if track == "voice":
                    src_path = explicit_input or state.voice_path
                elif track == "video":
                    src_path = explicit_input or state.clone_path
                elif track == "path":
                    src_path = explicit_input
                else:
                    self.send_json(400, {"error": f"Unsupported track: {track}"})
                    return

            if not src_path or not isinstance(src_path, str) or not os.path.isfile(src_path):
                self.send_json(400, {"error": f"Input file not found or not configured: {src_path}"})
                return

            try:
                threshold = float(payload.get("threshold", -32.0))
                min_silence = float(payload.get("min_silence", 0.45))
                pad = float(payload.get("pad", 0.08))
            except (TypeError, ValueError):
                self.send_json(400, {"error": "Invalid numeric parameter for cut-pauses"})
                return

            if min_silence <= 0 or pad < 0:
                self.send_json(400, {"error": "min_silence must be > 0 and pad must be >= 0"})
                return

            try:
                if not audio_mix.has_audio_stream(src_path):
                    self.send_json(400, {"error": f"Input has no audio stream: {src_path}"})
                    return
            except Exception as exc:
                self.send_json(500, {"error": f"Failed to probe input audio: {exc}"})
                return

            os.makedirs(state.renders_dir, exist_ok=True)
            stem, ext = os.path.splitext(os.path.basename(src_path))
            if not ext:
                ext = ".wav"
            out_path = _unique_output_path(state.renders_dir, f"{stem}_tight", ext, avoid_path=src_path)
            cuts_json_path = os.path.splitext(out_path)[0] + "_cuts.json"

            cut_args = argparse.Namespace(
                input=src_path,
                out=out_path,
                cuts_json=cuts_json_path,
                threshold=threshold,
                min_silence=min_silence,
                pad=pad,
            )
            try:
                audio_mix.cmd_cut_pauses(cut_args)
            except Exception as exc:
                self.send_json(500, {"error": f"cut-pauses failed: {exc}"})
                return

            cuts_data = _read_optional_json(cuts_json_path) or {}
            out_exists = os.path.isfile(out_path)
            if track == "voice" and out_exists:
                with state.lock:
                    state.voice_path = out_path

            out_fname = os.path.basename(out_path)
            cuts_fname = os.path.basename(cuts_json_path)
            self.send_json(200, {
                "ok": True,
                "out": f"renders/{out_fname}" if out_exists else None,
                "url": f"/renders/{out_fname}" if out_exists else None,
                "cuts_json": f"renders/{cuts_fname}",
                "keep_segments": cuts_data.get("keep_segments", []),
                "original_duration": cuts_data.get("original_duration"),
            })

        def _handle_audio_mix(self, payload: dict) -> None:
            with state.lock:
                video = payload["video"] if "video" in payload else state.clone_path
                if "voice" in payload:
                    voice = payload["voice"]
                elif "voice_path" in payload:
                    voice = payload["voice_path"]
                else:
                    voice = state.voice_path
                if "bgm" in payload:
                    bgm = payload["bgm"]
                elif "bgm_path" in payload:
                    bgm = payload["bgm_path"]
                else:
                    bgm = state.bgm_path
                if "sfx" in payload:
                    sfx = payload["sfx"]
                elif "sfx_path" in payload:
                    sfx = payload["sfx_path"]
                else:
                    sfx = state.sfx_path

            for label, fpath in (("video", video), ("voice", voice), ("bgm", bgm), ("sfx", sfx)):
                if fpath is not None and fpath != "":
                    if not isinstance(fpath, str) or not os.path.isfile(fpath):
                        self.send_json(400, {"error": f"Missing {label} input file: {fpath}"})
                        return

            try:
                voice_vol = float(payload.get("voice_vol", 1.0))
                bgm_vol = float(payload.get("bgm_vol", 0.35))
                video_vol = float(payload.get("video_vol", 1.0))
                fade_out = float(payload.get("fade_out", 1.5))
                keep_video_audio = bool(payload.get("keep_video_audio", False))
            except (TypeError, ValueError):
                self.send_json(400, {"error": "Invalid numeric parameter for audio mix"})
                return

            has_any_audio = bool(voice or bgm or sfx or (keep_video_audio and video))
            if not has_any_audio:
                self.send_json(400, {"error": "No audio sources specified for mix"})
                return

            os.makedirs(state.renders_dir, exist_ok=True)
            default_ext = ".mp4" if video else ".wav"
            req_out = payload.get("out")
            if req_out:
                clean_name = os.path.basename(str(req_out).replace("\\", "/").strip())
                if not clean_name or clean_name in {".", ".."} or ".." in str(req_out):
                    self.send_json(400, {"error": f"Invalid output filename: {req_out}"})
                    return
                if not os.path.splitext(clean_name)[1]:
                    clean_name += default_ext
                out_name = clean_name
            else:
                out_name = f"mixed{default_ext}"

            out_path, err = _safe_resolve_under(state.renders_dir, out_name, single_level=True)
            if err or not out_path:
                self.send_json(400, {"error": "Invalid output filename"})
                return

            mix_args = argparse.Namespace(
                video=video or None,
                voice=voice or None,
                bgm=bgm or None,
                sfx=sfx or None,
                out=out_path,
                voice_vol=voice_vol,
                bgm_vol=bgm_vol,
                video_vol=video_vol,
                fade_out=fade_out,
                keep_video_audio=keep_video_audio,
            )
            try:
                audio_mix.cmd_mix(mix_args)
            except (ValueError, RuntimeError, FileNotFoundError) as exc:
                self.send_json(400, {"error": str(exc)})
                return
            except Exception as exc:
                self.send_json(500, {"error": f"Audio mix failed: {exc}"})
                return

            self.send_json(200, {
                "ok": True,
                "out": f"renders/{out_name}",
                "url": f"/renders/{out_name}",
            })

        def _handle_render_start(self, payload: dict) -> None:
            raw_mode = payload.get("mode", "mp4")
            mode = "mp4" if raw_mode is None else raw_mode
            if not isinstance(mode, str) or mode not in {"mp4", "stills"}:
                self.send_json(400, {"error": f"Invalid mode: {raw_mode!r} (expected 'mp4' or 'stills')"})
                return

            raw_scale = payload.get("scale", 1)
            if raw_scale is None:
                raw_scale = 1
            try:
                scale_val = _parse_positive_number(raw_scale, "scale")
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            scale_norm = int(scale_val) if scale_val.is_integer() else scale_val
            scale_str = str(scale_norm)

            with state.lock:
                source_path = state.project_path or state.scene_path
            if not source_path or not os.path.isfile(source_path):
                self.send_json(400, {"error": "No live HTML scene or project manifest loaded for rendering"})
                return

            if not os.path.isfile(ENGINE_RENDER) or not os.path.isfile(CLI_SCRIPT):
                self.send_json(400, {"error": "kinearc native render engine (engine/render.mjs) is not available"})
                return

            job_id = uuid.uuid4().hex[:10]
            os.makedirs(state.renders_dir, exist_ok=True)

            out_abs = None
            out_name = None
            stills_dir = None
            stills_subdir = None

            if mode == "mp4":
                fps_str = None
                if "fps" in payload and payload["fps"] is not None:
                    try:
                        fps_val = _parse_positive_number(payload["fps"], "fps")
                    except ValueError as exc:
                        self.send_json(400, {"error": str(exc)})
                        return
                    fps_str = str(int(fps_val) if fps_val.is_integer() else fps_val)

                crf_val = None
                if "crf" in payload and payload["crf"] is not None:
                    raw_crf = payload["crf"]
                    if isinstance(raw_crf, bool):
                        self.send_json(400, {"error": "Invalid crf: must be an integer in [0, 51]"})
                        return
                    try:
                        if isinstance(raw_crf, float):
                            if not math.isfinite(raw_crf) or not raw_crf.is_integer():
                                raise ValueError("non-integer float")
                            crf_val = int(raw_crf)
                        elif isinstance(raw_crf, (int, str)):
                            crf_val = int(raw_crf)
                        else:
                            raise ValueError("unsupported type")
                    except ValueError:
                        self.send_json(400, {"error": f"Invalid crf: {raw_crf!r} (expected integer in [0, 51])"})
                        return
                    if crf_val < 0 or crf_val > 51:
                        self.send_json(400, {"error": f"crf must be between 0 and 51 (got {crf_val})"})
                        return

                try:
                    out_abs, out_name = _resolve_render_mp4_output(state.renders_dir, payload.get("out"), job_id)
                except ValueError as exc:
                    self.send_json(400, {"error": str(exc)})
                    return

                cmd = [
                    sys.executable,
                    "-B",
                    CLI_SCRIPT,
                    "render",
                    "--project",
                    source_path,
                    "--out",
                    out_abs,
                    "--scale",
                    scale_str,
                    "--json-progress",
                ]
                if fps_str is not None:
                    cmd.extend(["--fps", fps_str])
                if crf_val is not None:
                    cmd.extend(["--crf", str(crf_val)])
            else:
                try:
                    times_csv = _parse_render_times(payload)
                except ValueError as exc:
                    self.send_json(400, {"error": str(exc)})
                    return
                stills_subdir = f"stills_{job_id}"
                stills_dir, err = _safe_resolve_under(state.renders_dir, stills_subdir, single_level=True)
                if err or not stills_dir:
                    self.send_json(400, {"error": "Invalid stills output directory"})
                    return
                os.makedirs(stills_dir, exist_ok=True)
                cmd = [
                    sys.executable,
                    "-B",
                    CLI_SCRIPT,
                    "stills",
                    "--scene",
                    source_path,
                    "--out_dir",
                    stills_dir,
                    "--times",
                    times_csv,
                    "--scale",
                    scale_str,
                ]

            job_entry = {
                "job_id": job_id,
                "mode": mode,
                "scale": scale_norm,
                "status": "running",
                "progress": 0.0,
                "frame": 0,
                "total": 0,
                "out": None,
                "url": None,
                "error": None,
            }
            if mode == "stills":
                job_entry["stills"] = []

            with state.render_jobs_lock:
                state.render_jobs[job_id] = job_entry

            worker = threading.Thread(
                target=_execute_render_job,
                args=(state, job_id, mode, cmd, out_abs, out_name, stills_dir, stills_subdir),
                daemon=True,
            )
            worker.start()

            self.send_json(202, {
                "ok": True,
                "job_id": job_id,
                "status": "running",
                "mode": mode,
                "scale": scale_norm,
            })

        def _handle_render_load(self, payload: dict) -> None:
            job_id = payload.get("job_id")
            raw_path = payload.get("path")
            rel_path = None

            if job_id is not None:
                if not isinstance(job_id, str) or not job_id.strip():
                    self.send_json(400, {"error": "Invalid job_id"})
                    return
                with state.render_jobs_lock:
                    job = state.render_jobs.get(job_id.strip())
                    job_copy = dict(job) if job is not None else None
                if job_copy is None:
                    self.send_json(404, {"error": "Render job not found"})
                    return
                if job_copy.get("status") != "done" or not job_copy.get("out"):
                    self.send_json(400, {"error": f"Render job '{job_id}' is not completed"})
                    return
                if job_copy.get("mode") != "mp4":
                    self.send_json(400, {"error": f"Render job '{job_id}' is not an MP4 video"})
                    return
                rel_path = str(job_copy["out"])
            elif raw_path is not None:
                if not isinstance(raw_path, str) or not raw_path.strip():
                    self.send_json(400, {"error": "Invalid path"})
                    return
                rel_path = raw_path.strip()
            else:
                self.send_json(400, {"error": "Provide 'job_id' or 'path' to load rendered video"})
                return

            norm_rel = rel_path.replace("\\", "/").lstrip("/")
            if norm_rel.startswith("renders/"):
                norm_rel = norm_rel[len("renders/"):]
            target, err = _safe_resolve_under(state.renders_dir, norm_rel, single_level=False)
            if err == "forbidden":
                self.send_json(400, {"error": "Invalid path: outside renders directory"})
                return
            if err == "missing" or not target or not os.path.isfile(target):
                self.send_json(404, {"error": "Rendered video file not found"})
                return

            try:
                updated_info = state.load_rendered_video(target)
            except FileNotFoundError as exc:
                self.send_json(404, {"error": str(exc)})
                return
            except (ValueError, RuntimeError) as exc:
                self.send_json(400, {"error": str(exc)})
                return

            self.send_json(200, {"ok": True, "info": updated_info})

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path == "/":
                index_file = os.path.join(UI_DIR, "index.html")
                if os.path.isfile(index_file):
                    with open(index_file, "rb") as f:
                        self.send_bytes(200, f.read(), "text/html; charset=utf-8", cache_control="no-store")
                else:
                    self.send_bytes(200, PLACEHOLDER_HTML.encode("utf-8"), "text/html; charset=utf-8", cache_control="no-store")
                return

            if path.startswith("/ui/"):
                self._serve_confined(UI_DIR, path[4:], single_level=False, stream=False)
                return

            if path in {"/api/info", "/api/meta"}:
                self.send_json(200, state.build_info_payload())
                return

            if path == "/api/notes":
                with state.lock:
                    self.send_json(200, state.read_notes())
                return

            if path == "/api/frame":
                if "idx" not in query:
                    self.send_json(400, {"error": "Missing required query parameter 'idx'"})
                    return
                idx_raw = query["idx"][0]
                kind = query.get("kind", ["clone"])[0]
                fmt = query.get("fmt", ["jpg"])[0]
                self._handle_frame_request(kind, idx_raw, fmt)
                return

            if path.startswith("/api/frame/"):
                parts = path.strip("/").split("/")
                if len(parts) == 4:
                    fmt = query.get("fmt", ["jpg"])[0]
                    self._handle_frame_request(parts[2], parts[3], fmt)
                else:
                    self.send_json(404, {"error": "Not found"})
                return

            if path.startswith("/api/scene/"):
                self._serve_confined(state.scene_root, path[len("/api/scene/"):], single_level=False, stream=False)
                return

            if path == "/api/audio-peaks":
                self._handle_audio_peaks(query)
                return

            if path.startswith("/api/render/"):
                job_id = urllib.parse.unquote(path[len("/api/render/"):]).strip("/")
                if not job_id or "/" in job_id:
                    self.send_json(404, {"error": "Render job not found"})
                    return
                with state.render_jobs_lock:
                    job = state.render_jobs.get(job_id)
                    job_copy = dict(job) if job is not None else None
                if job_copy is None:
                    self.send_json(404, {"error": "Render job not found"})
                    return
                self.send_json(200, job_copy)
                return

            if path == "/video/clone":
                with state.lock:
                    clone_path = state.clone_path
                if clone_path and os.path.isfile(clone_path):
                    self.stream_file_range(clone_path, "video/mp4")
                else:
                    self.send_json(404, {"error": "No clone video configured"})
                return

            if path == "/video/ref":
                with state.lock:
                    ref_path = state.ref_path
                if ref_path and os.path.isfile(ref_path):
                    self.stream_file_range(ref_path, "video/mp4")
                else:
                    self.send_json(404, {"error": "No reference video configured"})
                return

            if path.startswith("/selection/"):
                self._serve_confined(state.sel_dir, path[len("/selection/"):], single_level=True, stream=True)
                return

            if path.startswith("/cuts/"):
                self._serve_confined(state.cuts_dir, path[len("/cuts/"):], single_level=True, stream=True)
                return

            if path.startswith("/renders/"):
                self._serve_confined(state.renders_dir, path[len("/renders/"):], single_level=False, stream=True)
                return

            self.send_json(404, {"error": "Not found"})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            payload, err = self._read_json_body()
            if err is not None:
                self.send_json(400, {"error": err})
                return

            if path == "/api/notes":
                raw_frame = payload.get("frame", 0)
                if isinstance(raw_frame, bool):
                    self.send_json(400, {"error": "Invalid frame index"})
                    return
                try:
                    frame_idx = int(raw_frame)
                except (TypeError, ValueError):
                    self.send_json(400, {"error": "Invalid frame index"})
                    return
                if frame_idx < 0:
                    self.send_json(400, {"error": "Frame index must be >= 0"})
                    return

                explicit_time_sec = None
                if "time_sec" in payload and payload["time_sec"] is not None:
                    raw_t = payload["time_sec"]
                    if isinstance(raw_t, bool):
                        self.send_json(400, {"error": "Invalid time_sec"})
                        return
                    try:
                        t_val = float(raw_t)
                    except (TypeError, ValueError):
                        self.send_json(400, {"error": "Invalid time_sec"})
                        return
                    if not math.isfinite(t_val) or t_val < 0:
                        self.send_json(400, {"error": "time_sec must be a finite non-negative number"})
                        return
                    explicit_time_sec = round(t_val, 3)

                bbox = payload.get("bbox")
                if bbox is not None:
                    if not isinstance(bbox, list) or len(bbox) != 4 or not all(_is_finite_number(v) for v in bbox):
                        self.send_json(400, {"error": "Invalid bbox: expected [x0, y0, x1, y1] finite numbers"})
                        return

                point = payload.get("point")
                if point is not None:
                    if not isinstance(point, list) or len(point) != 2 or not all(_is_finite_number(v) for v in point):
                        self.send_json(400, {"error": "Invalid point: expected [x, y] finite numbers"})
                        return

                raw_text = payload.get("text", "")
                if raw_text is None or not isinstance(raw_text, str):
                    self.send_json(400, {"error": "Invalid text: must be a non-null string"})
                    return
                note_text = raw_text.strip()

                end_frame_idx = None
                if "end_frame" in payload and payload["end_frame"] is not None:
                    raw_ef = payload["end_frame"]
                    if isinstance(raw_ef, bool):
                        self.send_json(400, {"error": "Invalid end_frame"})
                        return
                    try:
                        ef_val = int(raw_ef)
                    except (TypeError, ValueError):
                        self.send_json(400, {"error": "Invalid end_frame"})
                        return
                    if ef_val < frame_idx:
                        self.send_json(400, {"error": "end_frame must be >= frame"})
                        return
                    if ef_val > frame_idx:
                        end_frame_idx = ef_val

                explicit_end_time_sec = None
                if "end_time_sec" in payload and payload["end_time_sec"] is not None:
                    raw_et = payload["end_time_sec"]
                    if isinstance(raw_et, bool):
                        self.send_json(400, {"error": "Invalid end_time_sec"})
                        return
                    try:
                        et_val = float(raw_et)
                    except (TypeError, ValueError):
                        self.send_json(400, {"error": "Invalid end_time_sec"})
                        return
                    if not math.isfinite(et_val) or et_val < 0:
                        self.send_json(400, {"error": "end_time_sec must be a finite non-negative number"})
                        return
                    explicit_end_time_sec = round(et_val, 3)

                with state.lock:
                    notes = state.read_notes()
                    next_id = max([n["id"] for n in notes], default=0) + 1
                    rel_img = state.save_note_snapshot(next_id, frame_idx, bbox, point)
                    fps = state.fps if state.fps > 0 else 30.0
                    if explicit_time_sec is not None:
                        time_sec = explicit_time_sec
                    else:
                        time_sec = round(frame_idx / fps, 3)
                    note = {
                        "id": next_id,
                        "status": "open",
                        "frame": frame_idx,
                        "time_sec": time_sec,
                        "bbox": bbox,
                        "point": point,
                        "text": note_text,
                        "image": rel_img,
                    }
                    if end_frame_idx is not None:
                        note["end_frame"] = end_frame_idx
                        note["end_time_sec"] = (
                            explicit_end_time_sec
                            if explicit_end_time_sec is not None
                            else round(end_frame_idx / fps, 3)
                        )
                    notes.append(note)
                    state.write_notes(notes)
                self.send_json(201, note)
                return

            if path == "/api/audio/cut-pauses":
                self._handle_cut_pauses(payload)
                return

            if path == "/api/audio/mix":
                self._handle_audio_mix(payload)
                return

            if path == "/api/render":
                self._handle_render_start(payload)
                return

            if path == "/api/render/load":
                self._handle_render_load(payload)
                return

            self.send_json(404, {"error": "Not found"})

        def do_PATCH(self):
            path = urllib.parse.urlparse(self.path).path
            if not path.startswith("/api/notes/"):
                self.send_json(404, {"error": "Not found"})
                return
            try:
                nid = int(path.split("/")[-1])
            except ValueError:
                self.send_json(400, {"error": "Invalid note ID"})
                return
            payload, err = self._read_json_body()
            if err is not None:
                self.send_json(400, {"error": err})
                return
            if "status" in payload:
                if not isinstance(payload["status"], str) or payload["status"] not in {"open", "done"}:
                    self.send_json(400, {"error": "Invalid status: must be 'open' or 'done'"})
                    return
            if "text" in payload:
                if payload["text"] is None or not isinstance(payload["text"], str):
                    self.send_json(400, {"error": "Invalid text: must be a non-null string"})
                    return
            with state.lock:
                notes = state.read_notes()
                for n in notes:
                    if n["id"] == nid:
                        if "status" in payload:
                            n["status"] = payload["status"]
                        if "text" in payload:
                            n["text"] = payload["text"]
                        state.write_notes(notes)
                        self.send_json(200, n)
                        return
            self.send_json(404, {"error": f"Note {nid} not found"})

        def do_DELETE(self):
            path = urllib.parse.urlparse(self.path).path
            if not path.startswith("/api/notes/"):
                self.send_json(404, {"error": "Not found"})
                return
            try:
                nid = int(path.split("/")[-1])
            except ValueError:
                self.send_json(400, {"error": "Invalid note ID"})
                return
            with state.lock:
                notes = state.read_notes()
                kept = [n for n in notes if n["id"] != nid]
                img_path = os.path.join(state.sel_dir, f"note_{nid}.png")
                if os.path.exists(img_path):
                    os.remove(img_path)
                state.write_notes(kept)
            self.send_json(200, {"deleted": nid})

    return Handler


class ReusableThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    _kinearc_state: UiState | None = None

    def server_close(self) -> None:
        st = getattr(self, "_kinearc_state", None)
        if st is not None:
            with st.lock:
                st.clear_frame_caches()
        super().server_close()


def create_server(state: UiState, port: int = 4175) -> tuple[ReusableThreadingTCPServer, int]:
    """Bind a ReusableThreadingTCPServer on port (0 = ephemeral, >0 = fallback across 15 ports)."""
    handler = make_handler(state)
    if port == 0:
        server = ReusableThreadingTCPServer(("127.0.0.1", 0), handler)
        server._kinearc_state = state
        return server, int(server.server_address[1])

    for candidate in range(port, port + 15):
        try:
            server = ReusableThreadingTCPServer(("127.0.0.1", candidate), handler)
            server._kinearc_state = state
            return server, candidate
        except OSError:
            continue
    raise RuntimeError(f"Could not bind any port in range {port}..{port + 14}")


def build_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser for kinearc_ui."""
    parser = argparse.ArgumentParser(description="Interactive Review & Audio Finishing Web UI Server for kinearc.")
    parser.add_argument("clone", nargs="?", default=None, help="Optional path to rendered/reconstructed MP4 video")
    parser.add_argument("--scene", default=None, help="Optional path to live interactive HTML scene")
    parser.add_argument("--project", default=None, help="Optional path to kinearc.project.json manifest")
    parser.add_argument("--ref", default=None, help="Optional reference video for comparison modes")
    parser.add_argument("--sfx", default=None, help="Optional path to SFX cues JSON")
    parser.add_argument("--voice", default=None, help="Optional path to voiceover audio file")
    parser.add_argument("--bgm", default=None, help="Optional path to background music audio file")
    parser.add_argument("--out_dir", default=".kinearc_analysis", help="Directory where selection.json, selection/, and renders/ are saved")
    parser.add_argument("--port", type=int, default=4175, help="Local HTTP port")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open browser")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.clone and not args.scene and not args.project:
        parser.error("At least one source is required: provide positional clone MP4, --scene, or --project.")

    state = UiState(
        clone_path=args.clone,
        ref_path=args.ref,
        scene_path=args.scene,
        project_path=args.project,
        out_dir=args.out_dir,
        voice_path=args.voice,
        bgm_path=args.bgm,
        sfx_path=args.sfx,
    )
    server, port = create_server(state, port=args.port)
    url = f"http://127.0.0.1:{port}/"

    if state.clone_path:
        print(f"[kinearc_ui] Serving video {state.clone_path} ({state.width}x{state.height} @ {state.fps:.2f} FPS, {state.total_frames} frames)")
    if state.live_scene_url:
        print(f"[kinearc_ui] Serving live scene {state.scene_path} -> {state.live_scene_url}")
    if state.ref_path:
        print(f"[kinearc_ui] Reference comparison enabled: {state.ref_path}")
    print(f"[kinearc_ui] Annotations saved to: {state.sel_json}")
    print(f"[kinearc_ui] Open in browser: {url} (Press Ctrl+C to stop)")

    open_timer = None
    if not args.no_open:
        open_timer = threading.Timer(0.6, lambda: webbrowser.open(url))
        open_timer.daemon = True
        open_timer.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[kinearc_ui] Shutting down.")
        server.shutdown()
    finally:
        if open_timer is not None:
            open_timer.cancel()
        server.server_close()


if __name__ == "__main__":
    main()
