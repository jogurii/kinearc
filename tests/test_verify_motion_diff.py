import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_motion_diff.py"


def _write_mp4(path: Path, frames_bgr: list[np.ndarray], fps: float = 30.0) -> None:
    height, width = frames_bgr[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    assert writer.isOpened(), f"Failed to open VideoWriter for {path}"
    try:
        for frame in frames_bgr:
            writer.write(frame)
    finally:
        writer.release()


def _solid_frame(width: int, height: int, bgr: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = bgr
    return frame


def test_worst_frames_sorted_by_mae_descending(tmp_path: Path) -> None:
    orig_path = tmp_path / "orig.mp4"
    clone_path = tmp_path / "clone.mp4"
    out_dir = tmp_path / "out"

    base_bgr = (30, 30, 30)
    orig_frames = [_solid_frame(320, 180, base_bgr) for _ in range(30)]
    clone_frames = [_solid_frame(320, 180, base_bgr) for _ in range(30)]

    # Mild rectangle difference at frame 5
    cv2.rectangle(clone_frames[5], (40, 40), (120, 100), (110, 110, 110), -1)
    # Massive full-frame color corruption at frame 20
    clone_frames[20] = _solid_frame(320, 180, (255, 255, 255))

    _write_mp4(orig_path, orig_frames, fps=30.0)
    _write_mp4(clone_path, clone_frames, fps=30.0)

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(orig_path),
            str(clone_path),
            "--out_dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"

    report_path = out_dir / "verification_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    worst = report["worst_frames"]
    assert 1 <= len(worst) <= 5
    assert worst[0]["frame"] == 20
    assert worst[0]["rank"] == 1
    assert "timestamp_sec" in worst[0]
    assert worst[0]["timestamp_sec"] == pytest.approx(round(20 / 30.0, 3))
    assert all("rank" in item and "timestamp_sec" in item and "mae" in item for item in worst)
    assert [item["rank"] for item in worst] == list(range(1, len(worst) + 1))

    maes = [item["mae"] for item in worst]
    assert all(a >= b for a, b in zip(maes, maes[1:]))
    assert any(item["frame"] == 5 for item in worst)


def test_check_loop_flags_broken_seam_on_cross_fps(tmp_path: Path) -> None:
    orig_path = tmp_path / "orig_30fps.mp4"
    clone_path = tmp_path / "clone_60fps.mp4"
    out_dir = tmp_path / "out_loop"

    orig_frames = [_solid_frame(320, 180, (128, 128, 128)) for _ in range(15)]
    clone_frames = [_solid_frame(320, 180, (128, 128, 128)) for _ in range(30)]
    clone_frames[0] = _solid_frame(320, 180, (255, 255, 255))
    clone_frames[-1] = _solid_frame(320, 180, (0, 0, 0))

    _write_mp4(orig_path, orig_frames, fps=30.0)
    _write_mp4(clone_path, clone_frames, fps=60.0)

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(orig_path),
            str(clone_path),
            "--out_dir",
            str(out_dir),
            "--check-loop",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
    assert "indexerror" not in (proc.stdout + proc.stderr).lower()

    report = json.loads((out_dir / "verification_report.json").read_text(encoding="utf-8"))
    assert "clone_loop_mae" in report
    assert report["clone_loop_mae"] > 100.0
    assert report["loop_warnings_count"] == 1
    assert len(report["loop_warnings"]) == 1
    assert report["loop_warnings"][0]["type"] == "BROKEN_LOOP_SEAM"
    assert report["loop_warnings"][0]["clone_loop_mae"] == report["clone_loop_mae"]


def test_accepts_legacy_motion_analysis_out_dir(tmp_path: Path) -> None:
    orig_path = tmp_path / "orig.mp4"
    clone_path = tmp_path / "clone.mp4"
    legacy_out_dir = tmp_path / ".motion_analysis"

    frames = [_solid_frame(160, 120, (50, 100, 150)) for _ in range(6)]
    _write_mp4(orig_path, frames, fps=30.0)
    _write_mp4(clone_path, frames, fps=30.0)

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(orig_path),
            str(clone_path),
            "--out_dir",
            str(legacy_out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
    assert (legacy_out_dir / "verification_report.json").is_file()


def test_short_clip_under_two_frames_raises_cleanly(tmp_path: Path) -> None:
    one_frame = tmp_path / "one_frame.mp4"
    four_frames = tmp_path / "four_frames.mp4"
    _write_mp4(one_frame, [_solid_frame(160, 120, (90, 90, 90))], fps=30.0)
    _write_mp4(four_frames, [_solid_frame(160, 120, (90, 90, 90)) for _ in range(4)], fps=30.0)

    proc_short_orig = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(one_frame),
            str(four_frames),
            "--out_dir",
            str(tmp_path / "out_short_orig"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_short_orig.returncode != 0
    combined_orig = (proc_short_orig.stdout + proc_short_orig.stderr).lower()
    assert "indexerror" not in combined_orig
    assert "2 frames" in combined_orig or "at least 2" in combined_orig

    proc_short_clone = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(four_frames),
            str(one_frame),
            "--out_dir",
            str(tmp_path / "out_short_clone"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_short_clone.returncode != 0
    combined_clone = (proc_short_clone.stdout + proc_short_clone.stderr).lower()
    assert "indexerror" not in combined_clone
    assert "2 frames" in combined_clone or "at least 2" in combined_clone


def test_rank_worst_frames_and_compute_clone_loop_mae_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import verify_motion_diff as vmd

    maes = [1.0, 2.0, 15.0, 40.0, 38.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 25.0]
    ranked = vmd.rank_worst_frames(maes, fps_o=30.0, max_items=5, min_spacing=8)
    assert [item["frame"] for item in ranked] == [3, 11]
    assert [item["rank"] for item in ranked] == [1, 2]
    assert ranked[0]["timestamp_sec"] == round(3 / 30.0, 3)
    assert ranked[1]["timestamp_sec"] == round(11 / 30.0, 3)
    assert ranked[0]["mae"] >= ranked[1]["mae"]

    f0 = _solid_frame(32, 32, (10, 20, 30))
    f1 = _solid_frame(32, 32, (20, 30, 40))
    with pytest.raises(ValueError, match="At least 2 frames"):
        vmd.compute_clone_loop_mae([])
    with pytest.raises(ValueError, match="At least 2 frames"):
        vmd.compute_clone_loop_mae([f0])
    assert vmd.compute_clone_loop_mae([f0, f0]) == 0.0
    assert vmd.compute_clone_loop_mae([f0, f1]) == 10.0


def test_default_out_dir_is_kinearc_analysis_and_clean_loop(tmp_path: Path) -> None:
    orig_path = tmp_path / "orig.mp4"
    clone_path = tmp_path / "clone.mp4"
    frames = [_solid_frame(160, 120, (70, 140, 210)) for _ in range(6)]
    _write_mp4(orig_path, frames, fps=30.0)
    _write_mp4(clone_path, frames, fps=30.0)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(orig_path), str(clone_path), "--check-loop"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"

    default_out = tmp_path / ".kinearc_analysis"
    assert (default_out / "verification_report.json").is_file()
    report = json.loads((default_out / "verification_report.json").read_text(encoding="utf-8"))
    assert report["clone_loop_mae"] <= 6.0
    assert report["loop_warnings"] == []
    assert report["loop_warnings_count"] == 0
