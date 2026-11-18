#!/usr/bin/env python3
"""
measure_shapes_colors.py (v2.3 — Universal Video-Agnostic Geometry, Card Bop-Scale & Radial Ring Profiler)
Part of the kinearc skill toolkit.

Universal & Video-Agnostic Design:
- Detects UI cards, buttons, and active selection borders across ALL color hues (0..180) and luminance contrasts.
- Automatically compares sibling cards/tiles to compute the exact selection 'bop' scale ratio (e.g. 1.074x).
- Radially profiles any circular/ring element across 8 angles (0..315 deg) for inner/outer radius, stroke width, and hex stops.

Usage:
    python measure_shapes_colors.py <input_video.mp4> <frame1> [frame2 ...] [--width 720] [--out_dir .kinearc_analysis]
"""

import argparse
import json
import math
import os
import cv2
import numpy as np


def bgr_to_hex(bgr) -> str:
    b, g, r = int(round(bgr[0])), int(round(bgr[1])), int(round(bgr[2]))
    return f"#{r:02x}{g:02x}{b:02x}"


def profile_ring_or_circle(img, cx: int, cy: int, max_r: int = 260):
    h, w, _ = img.shape
    angles_deg = [0, 45, 90, 135, 180, 225, 270, 315]
    radial_luma = np.zeros(max_r, dtype=np.float64)
    radial_sat = np.zeros(max_r, dtype=np.float64)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    for r in range(max_r):
        lumas = []
        sats = []
        for a in angles_deg:
            rad = math.radians(a)
            px = int(round(cx + math.cos(rad) * r))
            py = int(round(cy + math.sin(rad) * r))
            if 0 <= px < w and 0 <= py < h:
                b, g, red = img[py, px]
                lumas.append(0.299 * red + 0.587 * g + 0.114 * b)
                sats.append(float(hsv[py, px, 1]))
        radial_luma[r] = np.mean(lumas) if lumas else 0
        radial_sat[r] = np.mean(sats) if sats else 0

    score = radial_luma + radial_sat * 0.6
    min_r = max(20, int(round(30 * (w / 720.0))))
    if max_r <= min_r + 5:
        return None
    peak_r = int(min_r + np.argmax(score[min_r:]))
    peak_val = score[peak_r]
    base_val = float(np.min(score[:peak_r]))
    if peak_val - base_val < 25:
        return None

    half_thresh = base_val + (peak_val - base_val) * 0.5
    r_in = peak_r
    while r_in > 10 and score[r_in] > half_thresh:
        r_in -= 1
    r_out = peak_r
    while r_out < max_r - 1 and score[r_out] > half_thresh:
        r_out += 1

    ring_stops = {}
    for a in angles_deg:
        rad = math.radians(a)
        px = int(round(cx + math.cos(rad) * peak_r))
        py = int(round(cy + math.sin(rad) * peak_r))
        if 0 <= px < w and 0 <= py < h:
            ring_stops[f"{a}deg"] = bgr_to_hex(img[py, px])

    return {
        "center": [cx, cy],
        "peak_radius": peak_r,
        "inner_radius": r_in,
        "outer_radius": r_out,
        "outer_diameter": r_out * 2,
        "stroke_width": r_out - r_in,
        "center_fill_hex": bgr_to_hex(img[cy, cx]),
        "inner_disc_mid_hex": bgr_to_hex(img[cy, min(w - 1, cx + r_in // 2)]),
        "ring_gradient_stops": ring_stops,
    }


def detect_cards_and_bop(img):
    """
    Universal card & active-selection bop detector:
    Works across any card border color (any Hue 0..180 with S >= 45) and any resolution.
    """
    h, w, _ = img.shape
    scale_f = w / 720.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    white_mask = (gray >= 248) & (hsv[:, :, 1] <= 14)
    num_lbl, _, stats, _ = cv2.connectedComponentsWithStats(white_mask.astype(np.uint8))

    cards = []
    for i in range(1, num_lbl):
        cw = int(stats[i, cv2.CC_STAT_WIDTH])
        ch = int(stats[i, cv2.CC_STAT_HEIGHT])
        cx = int(stats[i, cv2.CC_STAT_LEFT])
        cy = int(stats[i, cv2.CC_STAT_TOP])
        area = int(stats[i, cv2.CC_STAT_AREA])
        if cw >= int(160 * scale_f) and ch >= int(55 * scale_f) and area >= int(9000 * scale_f * scale_f):
            pad = max(4, int(round(6 * scale_f)))
            x0, y0 = max(0, cx - pad), max(0, cy - pad)
            x1, y1 = min(w, cx + cw + pad), min(h, cy + ch + pad)
            roi_hsv = hsv[y0:y1, x0:x1]
            # Universal hue range (0..180) for any colored highlight border
            border_sat = cv2.inRange(roi_hsv, (0, 48, 100), (180, 255, 255))
            bys, bxs = np.where(border_sat > 0)
            has_active_border = len(bxs) > int(140 * scale_f)
            outer_w = int(np.max(bxs) - np.min(bxs)) if has_active_border else cw
            outer_h = int(np.max(bys) - np.min(bys)) if has_active_border else ch
            cards.append({
                "bbox": [cx, cy, cw, ch],
                "outer_size": [outer_w, outer_h],
                "is_active_highlighted": bool(has_active_border),
            })

    bop_summary = None
    idle_cards = [c for c in cards if not c["is_active_highlighted"] and abs(c["bbox"][2] - c["bbox"][3]) <= int(20 * scale_f)]
    active_cards = [c for c in cards if c["is_active_highlighted"] and abs(c["outer_size"][0] - c["outer_size"][1]) <= int(25 * scale_f)]
    if idle_cards and active_cards:
        idle_w = float(np.median([c["bbox"][2] for c in idle_cards]))
        act_w = float(np.max([c["outer_size"][0] for c in active_cards]))
        if idle_w > 0 and act_w > idle_w:
            bop_summary = {
                "idle_card_width": round(idle_w, 1),
                "active_card_outer_width": round(act_w, 1),
                "bop_scale_ratio": round(act_w / idle_w, 4),
                "note": f"Active card pops/scales to {act_w/idle_w:.3f}x ({((act_w/idle_w)-1)*100:.1f}% larger than idle card)!",
            }

    return cards, bop_summary


def analyze_frame(img, frame_idx: int):
    h, w, _ = img.shape
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    is_dark = float(np.mean(gray)) < 60.0

    grid_colors = {}
    for gy, y_frac in [("top", 0.12), ("mid", 0.50), ("bot", 0.88)]:
        for gx, x_frac in [("left", 0.12), ("center", 0.50), ("right", 0.88)]:
            px, py = int(w * x_frac), int(h * y_frac)
            grid_colors[f"{gy}_{gx}"] = bgr_to_hex(img[py, px])

    if is_dark:
        mask = (gray > 140).astype(np.uint8)
    else:
        mask = (gray < 115).astype(np.uint8)

    rows = np.where(mask.sum(axis=1) > 3)[0]
    bands = []
    if len(rows) > 0:
        start = int(rows[0])
        prev = int(rows[0])
        for r in rows[1:]:
            r = int(r)
            if r - prev > max(4, int(round(6 * (w / 720.0)))):
                bands.append((start, prev))
                start = r
            prev = r
        bands.append((start, prev))

    measured_bands = []
    for y1, y2 in bands:
        cols = np.where(mask[y1 : y2 + 1].sum(axis=0) > 0)[0]
        if len(cols) == 0:
            continue
        x1, x2 = int(cols[0]), int(cols[-1])
        sub_mask = mask[y1 : y2 + 1, x1 : x2 + 1] > 0
        sub_img = img[y1 : y2 + 1, x1 : x2 + 1]
        median_bgr = np.median(sub_img[sub_mask], axis=0) if np.any(sub_mask) else [0, 0, 0]
        measured_bands.append({
            "y_range": [y1, y2],
            "height": y2 - y1,
            "x_range": [x1, x2],
            "width": x2 - x1,
            "center": [round((x1 + x2) / 2.0, 1), round((y1 + y2) / 2.0, 1)],
            "ink_hex": bgr_to_hex(median_bgr),
        })

    cards, bop_summary = ([], None) if is_dark else detect_cards_and_bop(img)

    ring_info = None
    if is_dark:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        sat_mask = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 75)
        ys, xs = np.where(sat_mask)
        if len(xs) > 50:
            rcx, rcy = int(round(np.mean(xs))), int(round(np.mean(ys)))
            ring_info = profile_ring_or_circle(img, rcx, rcy, max_r=int(260 * (w / 720.0)))

    return {
        "frame": frame_idx,
        "mode": "DARK" if is_dark else "LIGHT",
        "grid_colors": grid_colors,
        "content_bands": measured_bands,
        "cards": cards,
        "card_bop_summary": bop_summary,
        "ring_profile": ring_info,
    }


def main():
    parser = argparse.ArgumentParser(description="v2.3 Universal geometry, card bop scale ratios, circles, and HEX colors.")
    parser.add_argument("video", help="Path to reference video")
    parser.add_argument("frames", nargs="+", type=int, help="Frame indices to inspect")
    parser.add_argument("--width", type=int, default=0, help="Working width (0 = auto: native width if >= 720, else 720)")
    parser.add_argument("--out_dir", default=".kinearc_analysis", help="Output analysis directory (used when --out is omitted)")
    parser.add_argument("--out", default=None, help="Output JSON report path (default: <out_dir>/geometry_report.json)")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {args.video}")

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    work_w = args.width if args.width and args.width > 0 else min(1920, max(720, orig_w))
    scale = work_w / float(orig_w)
    work_h = int(round(orig_h * scale))

    reports = []
    for f_idx in args.frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        resized = cv2.resize(frame, (work_w, work_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        rep = analyze_frame(resized, f_idx)
        reports.append(rep)
        print(f"=== Frame {f_idx} ({rep['mode']}) ===")
        for b in rep["content_bands"]:
            print(f"  Band y={b['y_range'][0]}..{b['y_range'][1]} (h={b['height']}px) x={b['x_range'][0]}..{b['x_range'][1]} (w={b['width']}px, cx={b['center'][0]}) color={b['ink_hex']}")
        if rep["card_bop_summary"]:
            bs = rep["card_bop_summary"]
            print(f"  [CARD BOP DETECTED] {bs['note']}")
        if rep["ring_profile"]:
            rp = rep["ring_profile"]
            print(f"  Ring center={rp['center']} inner_r={rp['inner_radius']}px outer_r={rp['outer_radius']}px (diameter={rp['outer_diameter']}px, stroke={rp['stroke_width']}px)")

    cap.release()
    out_path = args.out if args.out else os.path.join(args.out_dir, "geometry_report.json")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2)
    print(f"[kinearc measure_shapes_colors v2.3] Saved full report -> {out_path}")


if __name__ == "__main__":
    main()
