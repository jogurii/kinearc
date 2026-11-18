#!/usr/bin/env python3
"""
extract_full_motion.py (v2.2) — Full-FPS Frame Extractor, Hard-Cut Detector & FPS-Adaptive RGB Motion-Trail Generator
Part of the kinearc skill toolkit.

Supports 30 FPS, 60 FPS, and 120 FPS reference videos automatically.

Usage:
    python scripts/extract_full_motion.py <input_video> [--out_dir .kinearc_analysis] [--width 0] [--cut-threshold 18.0]
"""

import argparse
import json
import math
import os
import cv2
import numpy as np


def compute_loop_seam_mae(frames: list[np.ndarray]) -> float:
    """Compute rounded mean absolute pixel difference between first and last frames."""
    if len(frames) < 2:
        raise ValueError(f"At least 2 frames are required to compute loop seam MAE (got {len(frames)})")
    mae = float(np.mean(np.abs(frames[0].astype(np.float32) - frames[-1].astype(np.float32))))
    return round(mae, 3)


def _render_cut_pair(
    before_frame: np.ndarray,
    after_frame: np.ndarray,
    before_idx: int,
    after_idx: int,
) -> np.ndarray:
    """Render a labeled side-by-side comparison image for a detected hard cut."""
    h, w = before_frame.shape[:2]
    panel_w = 320
    panel_h = max(32, int(round(h * (panel_w / float(w)))))
    divider_w = 4

    def _prepare_panel(frame: np.ndarray, label: str, color: tuple[int, int, int]) -> np.ndarray:
        panel = cv2.resize(frame, (panel_w, panel_h))
        cv2.rectangle(panel, (0, 0), (panel_w, 24), (0, 0, 0), -1)
        cv2.putText(panel, label, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        return panel

    left = _prepare_panel(before_frame, f"BEFORE f{before_idx}", (0, 255, 255))
    right = _prepare_panel(after_frame, f"AFTER f{after_idx}", (255, 255, 255))
    divider = np.full((panel_h, divider_w, 3), 40, dtype=np.uint8)
    return np.hstack([left, divider, right])


def analyze_cuts(
    frames: list[np.ndarray],
    frame_diffs: list[float],
    fps: float,
    out_dir: str,
    threshold: float = 18.0,
    min_spacing: int = 3,
) -> list[dict]:
    """Detect hard cuts from inter-frame diffs and write side-by-side comparison PNGs."""
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"fps must be positive (got {fps})")

    cuts_dir = os.path.join(out_dir, "cuts")
    os.makedirs(cuts_dir, exist_ok=True)
    for stale_name in os.listdir(cuts_dir):
        if stale_name.startswith("cut_") and stale_name.endswith(".png"):
            stale_path = os.path.join(cuts_dir, stale_name)
            if os.path.isfile(stale_path):
                os.remove(stale_path)

    cuts: list[dict] = []
    last_cut_frame: int | None = None
    limit = min(len(frames), len(frame_diffs))

    for i in range(1, limit):
        diff = float(frame_diffs[i])
        if diff < threshold:
            continue
        if last_cut_frame is not None and (i - last_cut_frame) < min_spacing:
            continue

        cut_index = len(cuts)
        rel_pair_path = f"cuts/cut_{cut_index:04d}.png"
        pair_img = _render_cut_pair(frames[i - 1], frames[i], i - 1, i)
        cv2.imwrite(os.path.join(out_dir, rel_pair_path), pair_img)

        cuts.append(
            {
                "cut_index": cut_index,
                "before_frame": i - 1,
                "after_frame": i,
                "timestamp_sec": round(i / fps, 4),
                "delta_mae": round(diff, 3),
                "pair_image": rel_pair_path,
            }
        )
        last_cut_frame = i

    return cuts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extract 100% of video frames, detect hard cuts, and build FPS-adaptive RGB motion-trail contact sheets."
    )
    parser.add_argument("video", help="Path to reference video file")
    parser.add_argument("--out_dir", default=".kinearc_analysis", help="Output analysis directory")
    parser.add_argument("--width", type=int, default=0, help="Working width in pixels (0 = auto: native width if >= 720, else 720)")
    parser.add_argument("--cut-threshold", type=float, default=18.0, help="Mean grayscale frame delta threshold for hard-cut detection")
    args = parser.parse_args(argv)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {args.video}")

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    raw_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    fps = raw_fps if math.isfinite(raw_fps) and raw_fps > 0 else 30.0
    if orig_w <= 0 or orig_h <= 0:
        cap.release()
        raise RuntimeError(f"Could not read valid dimensions ({orig_w}x{orig_h}) from video: {args.video}")

    fps_scale = fps / 30.0
    work_w = args.width if args.width and args.width > 0 else min(1920, max(720, orig_w))
    scale = work_w / float(orig_w)
    work_h = max(1, int(round(orig_h * scale)))

    frames: list[np.ndarray] = []
    frame_diffs: list[float] = [0.0]
    prev_gray = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        resized = cv2.resize(frame, (work_w, work_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        frames.append(resized)

        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None:
            diff = float(np.mean(cv2.absdiff(gray, prev_gray)))
            frame_diffs.append(diff)
        prev_gray = gray

    cap.release()
    total_frames = len(frames)
    if total_frames < 2:
        raise ValueError(f"Video must contain at least 2 frames (got {total_frames}): {args.video}")

    frames_dir = os.path.join(args.out_dir, "frames_all")
    sheets_dir = os.path.join(args.out_dir, "contact_sheets")
    trails_dir = os.path.join(args.out_dir, "motion_trails")
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(sheets_dir, exist_ok=True)
    os.makedirs(trails_dir, exist_ok=True)

    for idx, resized in enumerate(frames):
        cv2.imwrite(os.path.join(frames_dir, f"f_{idx:04d}.png"), resized)

    print(
        f"[kinearc extract_full_motion] Extracted {total_frames} frames "
        f"({work_w}x{work_h} @ {fps:.2f} fps, original {orig_w}x{orig_h}) -> {frames_dir}"
    )

    diffs_np = np.array(frame_diffs)
    threshold = max(2.5 / fps_scale, float(np.mean(diffs_np) + 1.2 * np.std(diffs_np)))
    active_frames = np.where(diffs_np > threshold)[0].tolist()

    thumb_w = 180
    thumb_h = int(round(work_h * (thumb_w / work_w)))
    chunk_size = 30
    cols = 6
    rows = 5

    for start_f in range(0, total_frames, chunk_size):
        end_f = min(total_frames, start_f + chunk_size)
        canvas = np.zeros((rows * thumb_h, cols * thumb_w, 3), dtype=np.uint8)
        for i, f_idx in enumerate(range(start_f, end_f)):
            r = i // cols
            c = i % cols
            thumb = cv2.resize(frames[f_idx], (thumb_w, thumb_h))
            label = f"f{f_idx} ({f_idx/fps:.2f}s)"
            cv2.rectangle(thumb, (0, 0), (thumb_w, 22), (0, 0, 0), -1)
            cv2.putText(thumb, label, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)
            canvas[r * thumb_h : (r + 1) * thumb_h, c * thumb_w : (c + 1) * thumb_w] = thumb

        sheet_path = os.path.join(sheets_dir, f"sheet_{start_f:04d}_{end_f-1:04d}.png")
        cv2.imwrite(sheet_path, canvas)

    # FPS-adaptive RGB Chrono-Motion Trail (spans ~133ms regardless of 30fps or 60fps)
    half_span = max(2, int(round(2 * fps_scale)))
    full_span = half_span * 2
    trail_thumbs = []
    for f_idx in range(full_span, total_frames, full_span):
        g0 = cv2.cvtColor(frames[f_idx - full_span], cv2.COLOR_BGR2GRAY)
        g1 = cv2.cvtColor(frames[f_idx - half_span], cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(frames[f_idx], cv2.COLOR_BGR2GRAY)

        d01 = cv2.absdiff(g0, g1)
        d12 = cv2.absdiff(g1, g2)
        motion_energy = float(np.mean(d01) + np.mean(d12))
        if motion_energy < 0.6:
            continue

        base_dim = (frames[f_idx].astype(np.float32) * 0.35).astype(np.uint8)
        trail = base_dim.copy()
        trail[:, :, 2] = np.clip(trail[:, :, 2].astype(np.int32) + d01.astype(np.int32) * 3, 0, 255).astype(np.uint8)
        trail[:, :, 1] = np.clip(trail[:, :, 1].astype(np.int32) + ((d01.astype(np.int32) + d12.astype(np.int32)) // 2) * 2, 0, 255).astype(np.uint8)
        trail[:, :, 0] = np.clip(trail[:, :, 0].astype(np.int32) + d12.astype(np.int32) * 3, 0, 255).astype(np.uint8)

        t_thumb = cv2.resize(trail, (thumb_w, thumb_h))
        cv2.rectangle(t_thumb, (0, 0), (thumb_w, 22), (0, 0, 0), -1)
        cv2.putText(t_thumb, f"f{f_idx-full_span}->f{f_idx} (R->B)", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
        trail_thumbs.append((f_idx, t_thumb))

    for chunk_i in range(0, len(trail_thumbs), chunk_size):
        sub = trail_thumbs[chunk_i : chunk_i + chunk_size]
        canvas = np.zeros((rows * thumb_h, cols * thumb_w, 3), dtype=np.uint8)
        for i, (_, t_img) in enumerate(sub):
            r = i // cols
            c = i % cols
            canvas[r * thumb_h : (r + 1) * thumb_h, c * thumb_w : (c + 1) * thumb_w] = t_img
        cv2.imwrite(os.path.join(trails_dir, f"trails_{chunk_i:03d}.png"), canvas)

    source_loop_mae = compute_loop_seam_mae(frames)
    cuts = analyze_cuts(frames, frame_diffs, fps, args.out_dir, threshold=args.cut_threshold)

    scene_cuts_payload = {
        "fps": fps,
        "total_frames": total_frames,
        "cut_threshold": args.cut_threshold,
        "cuts": cuts,
    }
    scene_cuts_path = os.path.join(args.out_dir, "scene_cuts.json")
    with open(scene_cuts_path, "w", encoding="utf-8") as f:
        json.dump(scene_cuts_payload, f, indent=2)

    meta = {
        "video": args.video,
        "original_size": [orig_w, orig_h],
        "working_size": [work_w, work_h],
        "fps": fps,
        "total_frames": total_frames,
        "duration_sec": round(total_frames / fps, 4),
        "high_motion_frames": active_frames,
        "source_loop_mae": source_loop_mae,
    }
    meta_path = os.path.join(args.out_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"[kinearc extract_full_motion] Saved contact sheets -> {sheets_dir}")
    print(f"[kinearc extract_full_motion] Saved RGB motion trails -> {trails_dir}")
    print(
        f"[kinearc extract_full_motion] Detected {len(cuts)} hard cut(s) "
        f"(threshold={args.cut_threshold}, loop_seam_mae={source_loop_mae}) -> {scene_cuts_path}"
    )


if __name__ == "__main__":
    main()
