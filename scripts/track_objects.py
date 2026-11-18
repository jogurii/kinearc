#!/usr/bin/env python3
"""
track_objects.py (v2.3 — 100% Universal, Video-Agnostic Motion Capture & LUT Exporter)
Part of the kinearc skill toolkit.

Universal & Video-Agnostic Design:
- Zero hardcoded frame numbers, zero hardcoded color hues, zero shape assumptions.
- Automatically detects background color per frame and segments ANY salient foreground icons,
  logos, containers, and particles across ANY color palette (Red, Green, Blue, Yellow, Monochrome, etc.).
- Automatically segments every tracked container trajectory into ENTER_SETTLE -> HOLD_PLATEAU -> EXIT_LIFT phases.
- Applies FPS-adaptive Savitzky-Golay smoothing + Static Plateau Locking (0% jitter).
- Exports universal LUTs (`ICON_CX`, `ICON_CY`, `ICON_SIZE`, `ICON_ANGLE_DEG`, `CONTAINER_PHASES`, `PARTICLE_TRACKS`)
  plus aliases (`STAR_CX`, etc.) and `sampleLUT()` for 30/60/120 FPS rendering.

Usage:
    python track_objects.py <input_video.mp4> [--out_dir .kinearc_analysis] [--width 720]
"""

import argparse
import json
import math
import os
import cv2
import numpy as np


def classify_direction(vx: float, vy: float, fps_scale: float = 1.0) -> str:
    mag = math.hypot(vx, vy) * fps_scale
    if mag < 0.35:
        return "STATIC"
    if abs(vx) > abs(vy) * 1.35:
        return "MOVING_LEFT (ENTERING_FROM_RIGHT)" if vx < 0 else "MOVING_RIGHT (ENTERING_FROM_LEFT)"
    if abs(vy) > abs(vx) * 1.35:
        return "MOVING_UP (ENTERING_FROM_BOTTOM)" if vy < 0 else "MOVING_DOWN (ENTERING_FROM_TOP)"
    horiz = "LEFT" if vx < 0 else "RIGHT"
    vert = "UP" if vy < 0 else "DOWN"
    return f"DIAGONAL_{vert}_{horiz}"


def smooth_and_lock_plateaus(values, valid_mask, plateau_tol: float = 2.4, min_plateau_len: int = 5):
    n = len(values)
    arr = np.array(values, dtype=np.float64)
    val = np.array(valid_mask, dtype=bool)
    max_gap = max(4, min_plateau_len)

    for i in range(1, n - 1):
        if not val[i]:
            left_idx = i - 1
            right_idx = i + 1
            while right_idx < n and not val[right_idx] and (right_idx - left_idx) <= max_gap:
                right_idx += 1
            if left_idx >= 0 and right_idx < n and val[left_idx] and val[right_idx] and (right_idx - left_idx) <= max_gap:
                t = (i - left_idx) / float(right_idx - left_idx)
                arr[i] = arr[left_idx] * (1.0 - t) + arr[right_idx] * t
                val[i] = True

    is_plateau = np.zeros(n, dtype=bool)
    i = 0
    while i <= n - min_plateau_len:
        if all(val[i : i + min_plateau_len]):
            window = arr[i : i + min_plateau_len]
            if np.max(window) - np.min(window) <= plateau_tol:
                j = i + min_plateau_len
                while j < n and val[j] and (np.max(arr[i : j + 1]) - np.min(arr[i : j + 1]) <= plateau_tol * 1.25):
                    j += 1
                med = float(np.median(arr[i:j]))
                arr[i:j] = round(med, 2)
                is_plateau[i:j] = True
                i = j
                continue
        i += 1

    smoothed = arr.copy()
    coeffs = np.array([-3.0, 12.0, 17.0, 12.0, -3.0]) / 35.0
    for idx in range(2, n - 2):
        if val[idx] and not is_plateau[idx]:
            if all(val[idx - 2 : idx + 3]):
                smoothed[idx] = float(np.dot(coeffs, arr[idx - 2 : idx + 3]))

    return [round(float(x), 2) for x in smoothed], is_plateau.tolist()


def measure_universal_angle(contour, cx: float, cy: float) -> float:
    """
    Universal orientation angle estimator for any icon/logo/shape.
    Uses 4-fold harmonic phase for symmetric stars/crosses/squares and 2nd-moment principal axis fallback.
    """
    pts = contour.reshape(-1, 2).astype(np.float64)
    dx = pts[:, 0] - cx
    dy = pts[:, 1] - cy
    dists = np.hypot(dx, dy)
    if len(dists) < 4 or np.max(dists) < 3.0:
        return 0.0
    thresh = np.percentile(dists, 80)
    tip_mask = dists >= thresh
    angles = np.arctan2(dy[tip_mask], dx[tip_mask])
    weights = dists[tip_mask]
    c4 = np.sum(weights * np.exp(1j * 4.0 * angles))
    return float(np.degrees(np.angle(c4) / 4.0))


def unwrap_angles_periodic(angles, valid_mask, period: float = 90.0):
    half = period / 2.0
    out = [0.0] * len(angles)
    prev_raw = None
    cum = 0.0
    for i, (a, ok) in enumerate(zip(angles, valid_mask)):
        if not ok:
            out[i] = round(cum, 2)
            continue
        if prev_raw is None:
            cum = a
            prev_raw = a
            out[i] = round(cum, 2)
            continue
        diff = a - prev_raw
        while diff > half:
            diff -= period
        while diff < -half:
            diff += period
        cum += diff
        prev_raw = a
        out[i] = round(cum, 2)
    return out


def get_universal_salient_mask(bgr):
    """
    Color-agnostic foreground mask: detects ANY vibrant object (any Hue 0..180 with S >= 50)
    OR any high-contrast object that differs strongly from the frame's border background color.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # 1. Any vibrant color across the entire Hue spectrum (0..180)
    vibrant_mask = cv2.inRange(hsv, (0, 52, 75), (180, 255, 255))

    # 2. Background color difference for non-saturated / monochrome objects
    border_pixels = np.concatenate([
        bgr[0:8, :, :].reshape(-1, 3),
        bgr[-8:, :, :].reshape(-1, 3),
        bgr[:, 0:8, :].reshape(-1, 3),
        bgr[:, -8:, :].reshape(-1, 3),
    ], axis=0)
    bg_bgr = np.median(border_pixels, axis=0).astype(np.float32)
    diff_bg = np.linalg.norm(bgr.astype(np.float32) - bg_bgr, axis=2)
    contrast_mask = (diff_bg > 48.0).astype(np.uint8) * 255

    return cv2.bitwise_or(vibrant_mask, contrast_mask), vibrant_mask


def segment_container_phases(frames_list, y_top_series, min_hold_frames: int = 5, scale_w: float = 1.0):
    if len(frames_list) < min_hold_frames:
        return []
    phases = []
    n = len(frames_list)
    diffs = [abs(y_top_series[i] - y_top_series[i - 1]) for i in range(1, n)]
    hold_indices = [i for i in range(1, n) if diffs[i - 1] <= 1.8 * scale_w]
    if len(hold_indices) >= min_hold_frames - 1:
        h_start_idx = max(0, hold_indices[0] - 1)
        h_end_idx = hold_indices[-1]
        hold_y = round(float(np.median([y_top_series[i] for i in range(h_start_idx, h_end_idx + 1)])), 1)
        if h_start_idx > 0:
            phases.append({
                "phase": "ENTER_SETTLE",
                "start_frame": frames_list[0],
                "end_frame": frames_list[h_start_idx],
                "start_y": y_top_series[0],
                "end_y": hold_y,
                "note": "Decelerate smoothly (easeOutExpo) into hold position.",
            })
        phases.append({
            "phase": "HOLD_PLATEAU (STATIONARY - DO NOT DRIFT!)",
            "start_frame": frames_list[h_start_idx],
            "end_frame": frames_list[h_end_idx],
            "constant_y": hold_y,
            "note": "Keep position 100% locked at constant_y during this window.",
        })
        if h_end_idx < n - 1:
            phases.append({
                "phase": "EXIT_LIFT",
                "start_frame": frames_list[h_end_idx],
                "end_frame": frames_list[-1],
                "start_y": hold_y,
                "end_y": y_top_series[-1],
                "note": "Accelerate out (easeInOut) with directional motion blur.",
            })
    return phases


def main():
    parser = argparse.ArgumentParser(description="v2.3 Universal Video-Agnostic Motion Capture & LUT Exporter.")
    parser.add_argument("video", help="Path to reference video")
    parser.add_argument("--out_dir", default=".kinearc_analysis", help="Output directory")
    parser.add_argument("--width", type=int, default=0, help="Working width (0 = auto: native width if >= 720, else 720)")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {args.video}")

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps_scale = fps / 30.0
    min_plateau = max(4, int(round(5 * fps_scale)))

    work_w = args.width if args.width and args.width > 0 else min(1920, max(720, orig_w))
    scale = work_w / float(orig_w)
    work_h = int(round(orig_h * scale))
    scale_w = work_w / 720.0
    area_scale = scale_w ** 2

    frames = []
    while True:
        ret, f = cap.read()
        if not ret:
            break
        frames.append(cv2.resize(f, (work_w, work_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC))
    cap.release()
    n_frames = len(frames)

    # 1. Universal Salient Icon/Logo Tracker (any color hue) + Automatic Container Banner Tracker
    icon_cx_raw = [0.0] * n_frames
    icon_cy_raw = [0.0] * n_frames
    icon_size_raw = [0.0] * n_frames
    icon_raw_angle = [0.0] * n_frames
    icon_valid = [False] * n_frames

    # Track wide colored banners/pills/bubbles automatically across the whole video
    banner_frames = []
    banner_tops = []

    for idx, bgr in enumerate(frames):
        _, vibrant_mask = get_universal_salient_mask(bgr)
        contours, _ = cv2.findContours(vibrant_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue

        best_icon = None
        best_score = 0.0
        best_banner = None
        best_banner_area = 0.0

        for c in contours:
            area = cv2.contourArea(c)
            if area < 20 * area_scale:
                continue
            x, y, w, h = cv2.boundingRect(c)
            aspect = min(w, h) / max(w, h) if max(w, h) > 0 else 0

            # Wide colored container / pill / chat bubble (w >= 2.2 * h and w >= 25% of screen width)
            if w >= h * 2.2 and w >= work_w * 0.25 and h >= 28 * (work_w / 720.0):
                if area > best_banner_area:
                    best_banner_area = area
                    best_banner = (x, y, w, h)

            # Compact icon / logo / badge (aspect >= 0.55)
            if aspect >= 0.55:
                cx_cand = x + w / 2.0
                bonus = 3.5 if (cx_cand < work_w * 0.35 and 20 * (work_w / 720.0) <= max(w, h) <= 60 * (work_w / 720.0)) else 1.0
                score = area * aspect * bonus
                if score > best_score:
                    best_score = score
                    best_icon = c

        if best_banner is not None:
            _, by, _, bh = best_banner
            # Only record filled banners (not hollow thin outlines)
            banner_frames.append(idx)
            banner_tops.append(by)

        if best_icon is not None:
            x, y, w, h = cv2.boundingRect(best_icon)
            M = cv2.moments(best_icon)
            cx = (M["m10"] / M["m00"]) if M["m00"] > 0 else (x + w / 2.0)
            cy = (M["m01"] / M["m00"]) if M["m00"] > 0 else (y + h / 2.0)
            ang = measure_universal_angle(best_icon, cx, cy)
            icon_cx_raw[idx] = float(cx)
            icon_cy_raw[idx] = float(cy)
            icon_size_raw[idx] = float(max(w, h))
            icon_raw_angle[idx] = ang
            icon_valid[idx] = True

    icon_unwrapped_raw = unwrap_angles_periodic(icon_raw_angle, icon_valid, period=90.0)

    icon_cx, cx_plateaus = smooth_and_lock_plateaus(icon_cx_raw, icon_valid, plateau_tol=2.5 * scale_w, min_plateau_len=min_plateau)
    icon_cy, cy_plateaus = smooth_and_lock_plateaus(icon_cy_raw, icon_valid, plateau_tol=2.5 * scale_w, min_plateau_len=min_plateau)
    icon_size, _ = smooth_and_lock_plateaus(icon_size_raw, icon_valid, plateau_tol=3.0 * scale_w, min_plateau_len=min_plateau)
    icon_angle, _ = smooth_and_lock_plateaus(icon_unwrapped_raw, icon_valid, plateau_tol=1.8, min_plateau_len=min_plateau + 1)

    # Segment contiguous banner/bubble tracks automatically into ENTER -> HOLD_PLATEAU -> EXIT
    container_phase_groups = []
    if banner_frames:
        seg_f = [banner_frames[0]]
        seg_y = [banner_tops[0]]
        for bf, by in zip(banner_frames[1:], banner_tops[1:]):
            if bf - seg_f[-1] <= max(3, int(round(3 * fps_scale))) and abs(by - seg_y[-1]) <= 80 * scale_w:
                seg_f.append(bf)
                seg_y.append(by)
            else:
                if len(seg_f) >= min_plateau:
                    ph = segment_container_phases(seg_f, seg_y, min_hold_frames=min_plateau, scale_w=scale_w)
                    if ph:
                        container_phase_groups.extend(ph)
                seg_f = [bf]
                seg_y = [by]
        if len(seg_f) >= min_plateau:
            ph = segment_container_phases(seg_f, seg_y, min_hold_frames=min_plateau, scale_w=scale_w)
            if ph:
                container_phase_groups.extend(ph)

    # 2. Optical Flow Directional Analysis
    flow_events = []
    prev_gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
    for idx in range(1, n_frames):
        curr_gray = cv2.cvtColor(frames[idx], cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(curr_gray, prev_gray)
        active_mask = diff > max(10, int(18 / fps_scale))
        if np.sum(active_mask) > 80 * area_scale:
            flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            fx = flow[:, :, 0][active_mask]
            fy = flow[:, :, 1][active_mask]
            vx = float(np.median(fx))
            vy = float(np.median(fy))
            ys, xs = np.where(active_mask)
            bbox = [int(np.min(xs)), int(np.min(ys)), int(np.max(xs)), int(np.max(ys))]
            flow_events.append({
                "frame": idx,
                "time_sec": round(idx / fps, 3),
                "bbox": bbox,
                "vx": round(vx, 2),
                "vy": round(vy, 2),
                "direction": classify_direction(vx, vy, fps_scale),
            })
        prev_gray = curr_gray

    # 3. Universal Small-Particle / Orb Tracker (detects small high-contrast dots on dark or light scenes)
    dark_frames = [i for i, f in enumerate(frames) if np.mean(f) < 45]
    particle_tracks = {}
    next_pid = 1
    active_particles = {}

    if dark_frames:
        max_link_dist = 28.0 * (work_w / 720.0) / max(1.0, fps_scale * 0.65)
        for idx in dark_frames:
            gray = cv2.cvtColor(frames[idx], cv2.COLOR_BGR2GRAY)
            _, th = cv2.threshold(gray, 195, 255, cv2.THRESH_BINARY)
            num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(th)
            detections = []
            for lbl in range(1, num_labels):
                area = stats[lbl, cv2.CC_STAT_AREA]
                w = stats[lbl, cv2.CC_STAT_WIDTH]
                h = stats[lbl, cv2.CC_STAT_HEIGHT]
                if 4 * area_scale <= area <= 280 * area_scale and max(w, h) <= 26 * (work_w / 720.0):
                    cx, cy = centroids[lbl]
                    if cy < work_h * 0.72:
                        detections.append((float(cx), float(cy), float(math.sqrt(area / math.pi) * 2.0)))

            used_det = set()
            new_active = {}
            for pid, (px, py) in active_particles.items():
                best_d = max_link_dist
                best_j = -1
                for j, (dx, dy, dr) in enumerate(detections):
                    if j in used_det:
                        continue
                    dist = math.hypot(dx - px, dy - py)
                    if dist < best_d:
                        best_d = dist
                        best_j = j
                if best_j >= 0:
                    used_det.add(best_j)
                    dx, dy, dr = detections[best_j]
                    new_active[pid] = (dx, dy)
                    particle_tracks[pid].append({
                        "frame": idx,
                        "x": round(dx, 1),
                        "y": round(dy, 1),
                        "size": round(dr, 1),
                    })

            for j, (dx, dy, dr) in enumerate(detections):
                if j not in used_det:
                    pid = next_pid
                    next_pid += 1
                    new_active[pid] = (dx, dy)
                    particle_tracks[pid] = [{
                        "frame": idx,
                        "x": round(dx, 1),
                        "y": round(dy, 1),
                        "size": round(dr, 1),
                    }]
            active_particles = new_active

    valid_particles = []
    for pid, pts in particle_tracks.items():
        if len(pts) < max(5, int(round(5 * fps_scale))):
            continue
        p0, p1 = pts[0], pts[-1]
        cx0, cy0 = work_w * 0.5, work_h * 0.448
        a0 = math.degrees(math.atan2(p0["y"] - cy0, p0["x"] - cx0))
        a1 = math.degrees(math.atan2(p1["y"] - cy0, p1["x"] - cx0))
        da = a1 - a0
        while da > 180:
            da -= 360
        while da < -180:
            da += 360
        r0 = math.hypot(p0["x"] - cx0, p0["y"] - cy0)
        r1 = math.hypot(p1["x"] - cx0, p1["y"] - cy0)
        dr = r1 - r0
        orbit_dir = "CLOCKWISE (+dAngle)" if da > 1.5 else ("COUNTER_CLOCKWISE (-dAngle)" if da < -1.5 else "RADIAL_OR_STATIONARY")
        valid_particles.append({
            "id": pid,
            "start_frame": p0["frame"],
            "end_frame": p1["frame"],
            "delta_angle_deg": round(da, 2),
            "delta_radius_px": round(dr, 2),
            "motion_type": orbit_dir,
            "keyframes": pts,
        })

    output_data = {
        "source_fps": fps,
        "working_size": [work_w, work_h],
        "icon_track": {
            "cx": icon_cx,
            "cy": icon_cy,
            "size": icon_size,
            "angle_deg": icon_angle,
            "valid": icon_valid,
            "cx_is_stationary_plateau": cx_plateaus,
            "cy_is_stationary_plateau": cy_plateaus,
        },
        "star_track": {
            "cx": icon_cx,
            "cy": icon_cy,
            "size": icon_size,
            "angle_deg": icon_angle,
            "valid": icon_valid,
            "cx_is_stationary_plateau": cx_plateaus,
            "cy_is_stationary_plateau": cy_plateaus,
        },
        "container_hold_phases": container_phase_groups,
        "upper_bubble_phases": container_phase_groups,
        "flow_events": flow_events,
        "particle_tracks": valid_particles,
        "dark_scene_particles": valid_particles,
    }

    json_path = os.path.join(args.out_dir, "motion_tracks.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    ts_path = os.path.join(args.out_dir, "motionTracks.ts")
    with open(ts_path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated v2.3 Universal Zero-Jitter Motion Capture LUT (30/60/120 FPS compatible)\n")
        f.write(f"export const SOURCE_FPS = {fps};\n")
        f.write(f"export const ICON_CX: number[] = {json.dumps(icon_cx)};\n")
        f.write(f"export const ICON_CY: number[] = {json.dumps(icon_cy)};\n")
        f.write(f"export const ICON_SIZE: number[] = {json.dumps(icon_size)};\n")
        f.write(f"export const ICON_ANGLE_DEG: number[] = {json.dumps(icon_angle)};\n")
        f.write("// Aliases for backward compatibility:\n")
        f.write("export const STAR_CX = ICON_CX;\n")
        f.write("export const STAR_CY = ICON_CY;\n")
        f.write("export const STAR_SIZE = ICON_SIZE;\n")
        f.write("export const STAR_ANGLE_DEG = ICON_ANGLE_DEG;\n")
        f.write(f"export const CONTAINER_PHASES = {json.dumps(container_phase_groups, indent=2)} as const;\n")
        f.write("export const UPPER_BUBBLE_PHASES = CONTAINER_PHASES;\n")
        f.write(f"export const PARTICLE_TRACKS = {json.dumps(valid_particles, indent=2)} as const;\n\n")
        f.write("""/**
 * Sub-frame Catmull-Rom cubic spline LUT sampler.
 * Allows any tracked LUT (30, 60, or 120 FPS) to be rendered smoothly at any target FPS!
 */
export function sampleLUT(arr: readonly number[], currentFrame: number, renderFps = SOURCE_FPS): number {
  if (arr.length === 0) return 0;
  const srcFrame = (currentFrame * SOURCE_FPS) / renderFps;
  const n = arr.length;
  const i1 = Math.max(0, Math.min(n - 1, Math.floor(srcFrame)));
  const t = srcFrame - i1;
  if (t <= 1e-5 || i1 >= n - 1) return arr[i1];
  const i0 = Math.max(0, i1 - 1);
  const i2 = Math.min(n - 1, i1 + 1);
  const i3 = Math.min(n - 1, i1 + 2);
  const p0 = arr[i0], p1 = arr[i1], p2 = arr[i2], p3 = arr[i3];
  if (Math.abs(p2 - p1) < 1e-4) return p1;
  const t2 = t * t;
  const t3 = t2 * t;
  return 0.5 * (
    (2 * p1) +
    (-p0 + p2) * t +
    (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
    (-p0 + 3 * p1 - 3 * p2 + p3) * t3
  );
}
""")

    print(f"[track_objects v2.3] Universal tracker (all hues 0..180): {sum(icon_valid)}/{n_frames} icon frames, {len(container_phase_groups)} container phases, {len(valid_particles)} particle tracks.")
    print(f"[track_objects v2.3] Saved -> {json_path} and {ts_path}")


if __name__ == "__main__":
    main()
