#!/usr/bin/env python3
"""
verify_motion_diff.py — Time-Synchronized 30/60/120-FPS Pixel MAE, Optical-Flow, Jitter & Motion-Blur Auditor
Part of the kinearc skill toolkit.

Supports:
- 30 FPS vs 30 FPS
- 60 FPS vs 60 FPS
- Cross-FPS Verification (e.g. 30 FPS Original vs 60 FPS Upscaled Clone via timestamp alignment!)

Usage:
    python scripts/verify_motion_diff.py <original.mp4> <reconstructed.mp4> [--out_dir .kinearc_analysis] [--check-loop]
"""

import argparse
import json
import math
import os
import cv2
import numpy as np


def edge_sharpness(gray_roi: np.ndarray) -> float:
    """Compute mean Sobel gradient magnitude for a grayscale region of interest."""
    if gray_roi.size == 0:
        return 0.0
    gx = cv2.Sobel(gray_roi, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_roi, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(np.hypot(gx, gy)))


def rank_worst_frames(
    frame_maes: list[float],
    fps_o: float,
    max_items: int = 5,
    min_spacing: int = 8,
) -> list[dict]:
    """Select up to max_items spaced peak-MAE frames and sort them by MAE descending."""
    if fps_o <= 0:
        raise ValueError(f"fps_o must be positive (got {fps_o})")
    if not frame_maes or max_items <= 0:
        return []

    ranked_indices = sorted(
        range(len(frame_maes)),
        key=lambda idx: (-float(frame_maes[idx]), idx),
    )

    selected: list[int] = []
    for f_idx in ranked_indices:
        if all(abs(f_idx - w_idx) >= min_spacing for w_idx in selected):
            selected.append(f_idx)
        if len(selected) >= max_items:
            break

    return [
        {
            "rank": rank,
            "frame": f_idx,
            "timestamp_sec": round(f_idx / float(fps_o), 3),
            "mae": round(float(frame_maes[f_idx]), 2),
        }
        for rank, f_idx in enumerate(selected, start=1)
    ]


def compute_clone_loop_mae(clone_raw: list[np.ndarray]) -> float:
    """Compute rounded mean absolute pixel error between first and last clone frames."""
    if len(clone_raw) < 2:
        raise ValueError(f"At least 2 frames are required to compute clone loop MAE (got {len(clone_raw)})")
    diff = np.abs(clone_raw[0].astype(np.float32) - clone_raw[-1].astype(np.float32))
    return round(float(np.mean(diff)), 3)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="kinearc Time-Synced Verify pixel MAE, optical flow direction, jitter/drift, and directional motion blur."
    )
    parser.add_argument("original", help="Path to reference video")
    parser.add_argument("clone", help="Path to reconstructed video")
    parser.add_argument("--out_dir", default=".kinearc_analysis", help="Output directory for audit report & images")
    parser.add_argument(
        "--check-loop",
        action="store_true",
        help="Evaluate first-vs-last frame loop seam MAE on the clone video",
    )
    args = parser.parse_args(argv)

    cap_o = cv2.VideoCapture(args.original)
    cap_c = cv2.VideoCapture(args.clone)
    if not cap_o.isOpened() or not cap_c.isOpened():
        cap_o.release()
        cap_c.release()
        raise RuntimeError("Could not open original or clone video.")

    w = int(cap_c.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap_c.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if w <= 0 or h <= 0:
        cap_o.release()
        cap_c.release()
        raise RuntimeError(f"Could not read valid clone dimensions ({w}x{h}).")

    fps_o_raw = float(cap_o.get(cv2.CAP_PROP_FPS) or 0.0)
    fps_c_raw = float(cap_c.get(cv2.CAP_PROP_FPS) or 0.0)
    fps_o = fps_o_raw if fps_o_raw > 0 else 30.0
    fps_c = fps_c_raw if fps_c_raw > 0 else 30.0

    orig_raw: list[np.ndarray] = []
    while True:
        ro, fo = cap_o.read()
        if not ro:
            break
        orig_raw.append(cv2.resize(fo, (w, h), interpolation=cv2.INTER_AREA))

    clone_raw: list[np.ndarray] = []
    while True:
        rc, fc = cap_c.read()
        if not rc:
            break
        clone_raw.append(fc)

    cap_o.release()
    cap_c.release()

    if len(orig_raw) < 2:
        raise ValueError(f"Original video must contain at least 2 frames (got {len(orig_raw)}).")
    if len(clone_raw) < 2:
        raise ValueError(f"Clone video must contain at least 2 frames (got {len(clone_raw)}).")

    # Align on original frame timestamps so 30fps->60fps upscaled renders are audited at identical timestamps!
    n_eval = len(orig_raw)
    orig_frames: list[np.ndarray] = []
    clone_frames: list[np.ndarray] = []
    for o_idx in range(n_eval):
        t_sec = o_idx / fps_o
        c_idx = int(round(t_sec * fps_c))
        if c_idx >= len(clone_raw):
            break
        orig_frames.append(orig_raw[o_idx])
        clone_frames.append(clone_raw[c_idx])

    n_frames = len(orig_frames)
    if n_frames < 2:
        raise ValueError(f"Aligned evaluation requires at least 2 frames (got {n_frames}).")

    os.makedirs(args.out_dir, exist_ok=True)

    frame_maes: list[float] = []
    frame_psnrs: list[float] = []
    motion_warnings: list[dict] = []
    jitter_drift_warnings: list[dict] = []
    blur_warnings: list[dict] = []

    prev_go = None
    prev_gc = None

    for idx in range(n_frames):
        fo = orig_frames[idx]
        fc = clone_frames[idx]
        diff = np.abs(fo.astype(np.float32) - fc.astype(np.float32))
        mae = float(np.mean(diff))
        psnr = float(cv2.PSNR(fo, fc))
        if not math.isfinite(psnr):
            psnr = 100.0
        frame_maes.append(mae)
        frame_psnrs.append(psnr)

        go = cv2.cvtColor(fo, cv2.COLOR_BGR2GRAY)
        gc = cv2.cvtColor(fc, cv2.COLOR_BGR2GRAY)

        if prev_go is not None and prev_gc is not None:
            do = cv2.absdiff(go, prev_go)
            dc = cv2.absdiff(gc, prev_gc)
            active_o = do > 16
            active_c = dc > 16

            if np.sum(active_o) < 40 and np.sum(active_c) > 150:
                ys, xs = np.where(active_c)
                jitter_drift_warnings.append({
                    "frame": idx,
                    "type": "UNWANTED_JITTER_OR_HOLD_DRIFT",
                    "bbox": [int(np.min(xs)), int(np.min(ys)), int(np.max(xs)), int(np.max(ys))],
                    "note": "Clone is moving/jittering during a stationary hold frame in Original!",
                })

            if np.sum(active_o) > 100:
                flow_o = cv2.calcOpticalFlowFarneback(prev_go, go, None, 0.5, 2, 15, 2, 5, 1.1, 0)
                flow_c = cv2.calcOpticalFlowFarneback(prev_gc, gc, None, 0.5, 2, 15, 2, 5, 1.1, 0)

                vx_o = float(np.median(flow_o[:, :, 0][active_o]))
                vy_o = float(np.median(flow_o[:, :, 1][active_o]))
                vx_c = float(np.median(flow_c[:, :, 0][active_o]))
                vy_c = float(np.median(flow_c[:, :, 1][active_o]))

                mag_o = math.hypot(vx_o, vy_o)
                mag_c = math.hypot(vx_c, vy_c)

                ys, xs = np.where(active_o)
                bbox = [int(np.min(xs)), int(np.min(ys)), int(np.max(xs)), int(np.max(ys))]

                if mag_o > 0.8:
                    if mag_c < 0.15:
                        motion_warnings.append({
                            "frame": idx,
                            "type": "MISSING_MOTION",
                            "bbox": bbox,
                            "orig_vector": [round(vx_o, 2), round(vy_o, 2)],
                            "clone_vector": [round(vx_c, 2), round(vy_c, 2)],
                        })
                    else:
                        cos_sim = (vx_o * vx_c + vy_o * vy_c) / (mag_o * mag_c + 1e-6)
                        if cos_sim < 0.35:
                            motion_warnings.append({
                                "frame": idx,
                                "type": "WRONG_DIRECTION",
                                "cosine_similarity": round(cos_sim, 2),
                                "bbox": bbox,
                                "orig_vector": [round(vx_o, 2), round(vy_o, 2)],
                                "clone_vector": [round(vx_c, 2), round(vy_c, 2)],
                            })

                if mag_o > 3.0:
                    x0, y0, x1, y1 = bbox
                    sharp_o = edge_sharpness(go[y0:y1, x0:x1])
                    sharp_c = edge_sharpness(gc[y0:y1, x0:x1])
                    if sharp_c > sharp_o * 1.38 and sharp_o > 1.0:
                        blur_warnings.append({
                            "frame": idx,
                            "type": "MISSING_DIRECTIONAL_MOTION_BLUR",
                            "bbox": bbox,
                            "orig_velocity": [round(vx_o, 2), round(vy_o, 2)],
                            "orig_sharpness": round(sharp_o, 2),
                            "clone_sharpness": round(sharp_c, 2),
                            "note": "Clone is overly sharp during fast motion; increase directional motion blur (blurX/blurY).",
                        })

        prev_go = go
        prev_gc = gc

    worst_frames = rank_worst_frames(frame_maes, fps_o)

    tw = 220
    th = max(32, int(round(h * (tw / w))))
    panels = []
    for item in worst_frames:
        f_idx = item["frame"]
        fo = cv2.resize(orig_frames[f_idx], (tw, th))
        fc = cv2.resize(clone_frames[f_idx], (tw, th))
        err = np.mean(np.abs(fo.astype(np.float32) - fc.astype(np.float32)), axis=2)
        heat = cv2.applyColorMap(np.clip(err * 3.0, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)

        cv2.putText(
            fo,
            f"#{item['rank']} ORIG f{f_idx}",
            (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 200, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            fc,
            f"#{item['rank']} f{f_idx} ({item['timestamp_sec']}s, MAE {item['mae']:.1f})",
            (6, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.37,
            (255, 160, 40),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            heat,
            "DIFF HEATMAP",
            (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        panels.append(np.hstack([fo, fc, heat]))

    if panels:
        audit_sheet = np.vstack(panels)
        sheet_path = os.path.join(args.out_dir, "motion_audit_sheet.png")
        cv2.imwrite(sheet_path, audit_sheet)

    summary: dict = {
        "original_fps": fps_o,
        "clone_fps": fps_c,
        "frames_evaluated": n_frames,
        "overall_mae": round(float(np.mean(frame_maes)), 2),
        "overall_psnr_db": round(float(np.mean(frame_psnrs)), 2),
        "max_mae": round(float(np.max(frame_maes)), 2),
        "max_mae_frame": int(np.argmax(frame_maes)),
        "worst_frames": worst_frames,
        "motion_warnings_count": len(motion_warnings),
        "jitter_or_drift_warnings_count": len(jitter_drift_warnings),
        "missing_motion_blur_warnings_count": len(blur_warnings),
        "motion_warnings": motion_warnings[:15],
        "jitter_or_drift_warnings": jitter_drift_warnings[:15],
        "missing_motion_blur_warnings": blur_warnings[:15],
    }

    if args.check_loop:
        clone_loop_mae = compute_clone_loop_mae(clone_raw)
        loop_warnings = []
        if clone_loop_mae > 6.0:
            loop_warnings.append({
                "type": "BROKEN_LOOP_SEAM",
                "clone_loop_mae": clone_loop_mae,
                "note": "Clone first and last frames differ significantly; loop seam may jump visibly.",
            })
        summary["clone_loop_mae"] = clone_loop_mae
        summary["loop_warnings_count"] = len(loop_warnings)
        summary["loop_warnings"] = loop_warnings

    report_path = os.path.join(args.out_dir, "verification_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(
        f"[kinearc verify_motion_diff] Orig FPS={fps_o:.1f} | Clone FPS={fps_c:.1f} "
        f"| Overall MAE: {summary['overall_mae']:.2f} | PSNR: {summary['overall_psnr_db']:.2f} dB"
    )
    print(f"[kinearc verify_motion_diff] Worst frames: {summary['worst_frames']}")
    print(
        f"[kinearc verify_motion_diff] Warnings -> Motion: {len(motion_warnings)} "
        f"| Jitter/Drift: {len(jitter_drift_warnings)} | Missing Blur: {len(blur_warnings)}"
    )
    if args.check_loop:
        print(
            f"[kinearc verify_motion_diff] Clone loop MAE: {summary['clone_loop_mae']:.3f} "
            f"| Loop warnings: {summary['loop_warnings_count']}"
        )


if __name__ == "__main__":
    main()
