import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "extract_full_motion.py"


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


def test_detects_hard_cut_and_writes_scene_cuts_json(tmp_path: Path) -> None:
    video_path = tmp_path / "hard_cut.mp4"
    out_dir = tmp_path / "out"

    blue_bgr = (255, 0, 0)
    orange_bgr = (0, 140, 255)
    frames = [_solid_frame(640, 360, blue_bgr) for _ in range(6)] + [
        _solid_frame(640, 360, orange_bgr) for _ in range(6)
    ]
    _write_mp4(video_path, frames, fps=30.0)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(video_path), "--out_dir", str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"

    scene_cuts_path = out_dir / "scene_cuts.json"
    assert scene_cuts_path.is_file()
    scene_cuts = json.loads(scene_cuts_path.read_text(encoding="utf-8"))
    assert scene_cuts["total_frames"] == 12
    assert scene_cuts["fps"] == pytest.approx(30.0, rel=1e-2)
    assert scene_cuts["cut_threshold"] == pytest.approx(18.0)

    cuts = scene_cuts["cuts"]
    assert len(cuts) == 1
    cut = cuts[0]
    assert cut["cut_index"] == 0
    assert cut["before_frame"] == 5
    assert cut["after_frame"] == 6
    assert cut["delta_mae"] >= 18.0
    assert (out_dir / cut["pair_image"]).is_file()

    metadata_path = out_dir / "metadata.json"
    assert metadata_path.is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["total_frames"] == 12
    assert metadata["source_loop_mae"] > 20.0


def test_static_clip_produces_empty_cuts_and_low_loop_mae(tmp_path: Path) -> None:
    video_path = tmp_path / "static.mp4"
    out_dir = tmp_path / "out"

    solid = _solid_frame(640, 360, (40, 180, 90))
    _write_mp4(video_path, [solid for _ in range(8)], fps=30.0)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(video_path), "--out_dir", str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"

    scene_cuts = json.loads((out_dir / "scene_cuts.json").read_text(encoding="utf-8"))
    assert scene_cuts["cuts"] == []

    metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["source_loop_mae"] < 0.5


def test_short_clip_under_two_frames_raises_cleanly(tmp_path: Path) -> None:
    single_frame_video = tmp_path / "one_frame.mp4"
    _write_mp4(single_frame_video, [_solid_frame(640, 360, (128, 128, 128))], fps=30.0)

    proc_short = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(single_frame_video),
            "--out_dir",
            str(tmp_path / "out_short"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_short.returncode != 0
    combined_short = (proc_short.stdout + proc_short.stderr).lower()
    assert "indexerror" not in combined_short
    assert "2 frames" in combined_short or "at least 2" in combined_short

    missing_video = tmp_path / "does_not_exist.mp4"
    proc_missing = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(missing_video),
            "--out_dir",
            str(tmp_path / "out_missing"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_missing.returncode != 0
    combined_missing = (proc_missing.stdout + proc_missing.stderr).lower()
    assert "indexerror" not in combined_missing
    assert "could not open" in combined_missing or "unreadable" in combined_missing


def test_compute_loop_seam_mae_and_analyze_cuts_unit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import extract_full_motion as efm

    f0 = _solid_frame(32, 32, (10, 20, 30))
    f1 = _solid_frame(32, 32, (20, 30, 40))

    with pytest.raises(ValueError, match="At least 2 frames"):
        efm.compute_loop_seam_mae([])
    with pytest.raises(ValueError, match="At least 2 frames"):
        efm.compute_loop_seam_mae([f0])

    assert efm.compute_loop_seam_mae([f0, f0]) == 0.0
    assert efm.compute_loop_seam_mae([f0, f1]) == 10.0

    # Verify min_spacing suppresses adjacent cut spikes within 3 frames of prior cut.
    frames = [f0] * 10
    diffs = [0.0, 2.0, 25.0, 30.0, 28.0, 20.0, 1.0, 19.0, 1.0, 1.0]
    cuts = efm.analyze_cuts(frames, diffs, fps=30.0, out_dir=str(tmp_path), threshold=18.0, min_spacing=3)
    assert [c["after_frame"] for c in cuts] == [2, 5]
    assert [c["before_frame"] for c in cuts] == [1, 4]
    assert cuts[0]["timestamp_sec"] == round(2 / 30.0, 4)
    assert (tmp_path / cuts[0]["pair_image"]).is_file()
    assert (tmp_path / cuts[1]["pair_image"]).is_file()


def test_default_out_dir_and_cut_threshold_cli(tmp_path: Path) -> None:
    video_path = tmp_path / "cut_threshold.mp4"
    frames = [_solid_frame(640, 360, (255, 0, 0)) for _ in range(4)] + [
        _solid_frame(640, 360, (0, 140, 255)) for _ in range(4)
    ]
    _write_mp4(video_path, frames, fps=30.0)

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(video_path), "--cut-threshold", "200.0"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"

    default_out = tmp_path / ".kinearc_analysis"
    assert (default_out / "metadata.json").is_file()
    scene_cuts = json.loads((default_out / "scene_cuts.json").read_text(encoding="utf-8"))
    assert scene_cuts["cut_threshold"] == pytest.approx(200.0)
    assert scene_cuts["cuts"] == []


def test_rerun_with_higher_threshold_clears_stale_cut_images(tmp_path: Path) -> None:
    video_path = tmp_path / "two_cuts.mp4"
    out_dir = tmp_path / "out_rerun"

    dark = _solid_frame(640, 360, (10, 10, 10))
    mid = _solid_frame(640, 360, (90, 90, 90))
    bright = _solid_frame(640, 360, (245, 245, 245))
    frames = [dark for _ in range(4)] + [mid for _ in range(4)] + [bright for _ in range(4)]
    _write_mp4(video_path, frames, fps=30.0)

    proc_low = subprocess.run(
        [sys.executable, "-B", str(SCRIPT_PATH), str(video_path), "--out_dir", str(out_dir), "--cut-threshold", "18.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_low.returncode == 0, f"stderr:\n{proc_low.stderr}\nstdout:\n{proc_low.stdout}"

    cuts_low = json.loads((out_dir / "scene_cuts.json").read_text(encoding="utf-8"))["cuts"]
    assert len(cuts_low) == 2
    assert sorted(p.name for p in (out_dir / "cuts").glob("cut_*.png")) == ["cut_0000.png", "cut_0001.png"]

    # Re-run into the same directory with an intermediate threshold (only 1 cut remains).
    proc_mid = subprocess.run(
        [sys.executable, "-B", str(SCRIPT_PATH), str(video_path), "--out_dir", str(out_dir), "--cut-threshold", "110.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_mid.returncode == 0, f"stderr:\n{proc_mid.stderr}\nstdout:\n{proc_mid.stdout}"

    cuts_mid = json.loads((out_dir / "scene_cuts.json").read_text(encoding="utf-8"))["cuts"]
    assert len(cuts_mid) == 1
    assert sorted(p.name for p in (out_dir / "cuts").glob("cut_*.png")) == ["cut_0000.png"]

    # Re-run into the same directory with an even higher threshold (0 cuts remain).
    proc_high = subprocess.run(
        [sys.executable, "-B", str(SCRIPT_PATH), str(video_path), "--out_dir", str(out_dir), "--cut-threshold", "240.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_high.returncode == 0, f"stderr:\n{proc_high.stderr}\nstdout:\n{proc_high.stdout}"

    cuts_high = json.loads((out_dir / "scene_cuts.json").read_text(encoding="utf-8"))["cuts"]
    assert cuts_high == []
    assert list((out_dir / "cuts").glob("cut_*.png")) == []


def test_nonfinite_or_nonpositive_fps_falls_back_to_30(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import extract_full_motion as efm

    sample_frames = [_solid_frame(64, 36, (20, 40, 60)), _solid_frame(64, 36, (20, 40, 60))]

    for bad_fps in (float("nan"), float("inf"), 0.0, -24.0):
        class _FakeCap:
            def __init__(self, _path: str) -> None:
                self._idx = 0

            def isOpened(self) -> bool:
                return True

            def get(self, prop_id: int) -> float:
                if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
                    return 64.0
                if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
                    return 36.0
                if prop_id == cv2.CAP_PROP_FPS:
                    return bad_fps
                return 0.0

            def read(self):
                if self._idx < len(sample_frames):
                    frame = sample_frames[self._idx]
                    self._idx += 1
                    return True, frame
                return False, None

            def release(self) -> None:
                pass

        out_dir = tmp_path / f"out_{repr(bad_fps).replace('-', 'neg')}"
        monkeypatch.setattr(efm.cv2, "VideoCapture", _FakeCap)
        efm.main([str(tmp_path / "dummy.mp4"), "--out_dir", str(out_dir)])
        meta = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
        assert meta["fps"] == 30.0
        assert meta["duration_sec"] == round(2 / 30.0, 4)

