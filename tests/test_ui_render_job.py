import http.client
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _write_mp4(path: Path, frames_bgr: list[np.ndarray], fps: float = 30.0) -> None:
    height, width = frames_bgr[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    assert writer.isOpened(), f"Could not create test video {path}"
    try:
        for frame in frames_bgr:
            writer.write(frame)
    finally:
        writer.release()


@contextmanager
def _running_server(state):
    import kinearc_ui

    server, port = kinearc_ui.create_server(state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _http_request(url: str, method: str = "GET", json_body: dict | None = None):
    headers = {}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()), err.read()


def _raw_get(port: int, raw_path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", raw_path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, dict(resp.getheaders()), body
    finally:
        conn.close()


def _create_canvas_project(base_dir: Path, duration: float = 0.3, width: int = 320, height: int = 180, fps: int = 30):
    scenes_dir = base_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    scene_html = scenes_dir / "01.html"
    scene_html.write_text(
        f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><title>Render Test Scene</title></head>
<body style="margin:0;overflow:hidden;background:#0b0d13;">
<canvas id="c" style="width:100vw;height:100vh;display:block;"></canvas>
<script>
const q = new URLSearchParams(location.search);
const rawS = parseFloat(q.get("scale") || "1");
const S = Number.isFinite(rawS) && rawS > 0 ? rawS : 1;
const W = {width}, H = {height};
const canvas = document.getElementById("c");
canvas.width = Math.round(W * S);
canvas.height = Math.round(H * S);
const ctx = canvas.getContext("2d");

const TOTAL = {duration};
function seek(t) {{
  ctx.setTransform(S, 0, 0, S, 0, 0);
  ctx.fillStyle = "#0b0d13";
  ctx.fillRect(0, 0, W, H);
  const p = Math.min(1, Math.max(0, t / TOTAL));
  ctx.fillStyle = "#6c8cff";
  ctx.fillRect(Math.round(20 + p * (W - 100)), 40, 60, H - 80);
}}
const rawT = parseFloat(q.get("t") || "0");
const initT = Number.isFinite(rawT) && rawT > 0 ? rawT : 0;
const ready = Promise.resolve().then(() => seek(initT));
window.TOTAL = TOTAL;
window.ready = ready;
window.renderAt = seek;
window.kinearc = {{ totalDuration: TOTAL, ready, seek }};
</script>
</body>
</html>
""",
        encoding="utf-8",
    )
    proj_json = base_dir / "kinearc.project.json"
    proj_json.write_text(
        json.dumps({"width": width, "height": height, "fps": fps, "scenes": ["scenes/01.html"]}),
        encoding="utf-8",
    )
    return proj_json, scene_html


def _poll_render_job(base_url: str, job_id: str, timeout_sec: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout_sec
    last_job = None
    while time.monotonic() < deadline:
        st, _, raw = _http_request(f"{base_url}/api/render/{job_id}")
        assert st == 200, f"Unexpected status polling job {job_id}: {st} {raw!r}"
        last_job = json.loads(raw.decode("utf-8"))
        if last_job.get("status") in {"done", "error"}:
            return last_job
        time.sleep(0.2)
    raise AssertionError(f"Render job {job_id} timed out after {timeout_sec}s; last={last_job!r}")


def test_render_mp4_job_progress_and_load_into_stage(tmp_path: Path) -> None:
    import kinearc_ui

    proj_json, _ = _create_canvas_project(tmp_path / "proj_mp4", duration=0.3, width=320, height=180, fps=30)
    out_dir = tmp_path / "proj_mp4" / ".kinearc_analysis"
    state = kinearc_ui.UiState(project_path=str(proj_json), out_dir=str(out_dir))

    with _running_server(state) as (base_url, _port):
        st_info0, _, raw_info0 = _http_request(f"{base_url}/api/info")
        assert st_info0 == 200
        info0 = json.loads(raw_info0.decode("utf-8"))
        assert info0["has_video"] is False
        assert info0["has_live_scene"] is True
        assert info0["has_render_engine"] is True

        st_start, _, raw_start = _http_request(
            f"{base_url}/api/render",
            method="POST",
            json_body={"scale": 1, "mode": "mp4", "fps": 30, "crf": 16},
        )
        assert st_start == 202, raw_start.decode("utf-8", errors="replace")
        start_res = json.loads(raw_start.decode("utf-8"))
        assert start_res["ok"] is True
        assert start_res["status"] == "running"
        assert start_res["mode"] == "mp4"
        assert start_res["scale"] == 1
        job_id = start_res["job_id"]
        assert isinstance(job_id, str) and len(job_id) > 0

        final_job = _poll_render_job(base_url, job_id)
        assert final_job["status"] == "done", f"Render failed: {final_job}"
        assert final_job["progress"] == pytest.approx(100.0)
        assert final_job["frame"] >= 8
        assert final_job["total"] >= 8
        assert final_job["error"] is None
        assert final_job["out"].startswith("renders/")
        assert final_job["url"].startswith("/renders/")

        rendered_mp4 = out_dir / final_job["out"]
        assert rendered_mp4.is_file() and rendered_mp4.stat().st_size > 1024

        cap = cv2.VideoCapture(str(rendered_mp4))
        assert cap.isOpened(), f"cv2 could not open rendered MP4 {rendered_mp4}"
        try:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            cap.release()
        assert (w, h) == (320, 180)
        assert n_frames >= 8

        st_stream, hdr_stream, mp4_bytes = _http_request(f"{base_url}{final_job['url']}")
        assert st_stream == 200
        assert "video/mp4" in hdr_stream.get("Content-Type", "")
        assert len(mp4_bytes) == rendered_mp4.stat().st_size

        st_load, _, raw_load = _http_request(
            f"{base_url}/api/render/load",
            method="POST",
            json_body={"job_id": job_id},
        )
        assert st_load == 200, raw_load.decode("utf-8", errors="replace")
        load_res = json.loads(raw_load.decode("utf-8"))
        assert load_res["ok"] is True
        assert load_res["info"]["has_video"] is True
        assert load_res["info"]["width"] == 320
        assert load_res["info"]["height"] == 180

        st_info1, _, raw_info1 = _http_request(f"{base_url}/api/info")
        assert st_info1 == 200
        info1 = json.loads(raw_info1.decode("utf-8"))
        assert info1["has_video"] is True

        st_frame, hdr_frame, jpg_bytes = _http_request(f"{base_url}/api/frame?idx=0&kind=clone")
        assert st_frame == 200
        assert hdr_frame.get("Content-Type", "").startswith("image/jpeg")
        assert jpg_bytes[:2] == b"\xff\xd8"
        decoded = cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None and decoded.shape == (180, 320, 3)

        # Also verify path-based /api/render/load works for confined renders/ file
        st_load_path, _, raw_load_path = _http_request(
            f"{base_url}/api/render/load",
            method="POST",
            json_body={"path": final_job["out"]},
        )
        assert st_load_path == 200
        assert json.loads(raw_load_path.decode("utf-8"))["info"]["has_video"] is True


def test_render_stills_job_and_nested_renders_serving(tmp_path: Path) -> None:
    import kinearc_ui

    proj_json, _ = _create_canvas_project(tmp_path / "proj_stills", duration=0.4, width=320, height=180, fps=30)
    (tmp_path / "secret.txt").write_text("TOP_SECRET", encoding="utf-8")
    out_dir = tmp_path / "proj_stills" / ".kinearc_analysis"
    state = kinearc_ui.UiState(project_path=str(proj_json), out_dir=str(out_dir))

    with _running_server(state) as (base_url, port):
        st_start, _, raw_start = _http_request(
            f"{base_url}/api/render",
            method="POST",
            json_body={"mode": "stills", "scale": 1, "times": [0.0, 0.25]},
        )
        assert st_start == 202, raw_start.decode("utf-8", errors="replace")
        job_id = json.loads(raw_start.decode("utf-8"))["job_id"]

        final_job = _poll_render_job(base_url, job_id)
        assert final_job["status"] == "done", f"Stills failed: {final_job}"
        assert final_job["progress"] == pytest.approx(100.0)
        assert isinstance(final_job.get("stills"), list) and len(final_job["stills"]) == 2

        decoded_imgs = []
        for item in final_job["stills"]:
            still_url = item["url"] if isinstance(item, dict) else item
            assert still_url.startswith("/renders/")
            st_png, hdr_png, png_bytes = _http_request(f"{base_url}{still_url}")
            assert st_png == 200
            assert "image/png" in hdr_png.get("Content-Type", "")
            assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
            img = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            assert img is not None and img.shape == (180, 320, 3)
            decoded_imgs.append(img)

        diff = float(np.mean(np.abs(decoded_imgs[0].astype(np.float32) - decoded_imgs[1].astype(np.float32))))
        assert diff > 1.0, f"Expected distinct still frames across times, got diff={diff}"

        # Traversal guard on /renders/ MUST still return 403
        st_trav, _, _ = _raw_get(port, "/renders/../../secret.txt")
        assert st_trav == 403

        # /api/render/load on a non-mp4 (stills) job MUST return 400
        st_load_stills, _, raw_load_stills = _http_request(
            f"{base_url}/api/render/load",
            method="POST",
            json_body={"job_id": job_id},
        )
        assert st_load_stills == 400
        assert "error" in json.loads(raw_load_stills.decode("utf-8"))


def test_render_validation_errors_and_mp4_only_rejection(tmp_path: Path) -> None:
    import kinearc_ui

    # 1. MP4-only UiState (no scene/project) -> POST /api/render returns 400
    mp4_only = tmp_path / "plain.mp4"
    _write_mp4(mp4_only, [np.full((120, 160, 3), (30, 60, 90), dtype=np.uint8) for _ in range(4)], fps=30.0)
    state_mp4 = kinearc_ui.UiState(clone_path=str(mp4_only), out_dir=str(tmp_path / ".kinearc_mp4_only"))

    with _running_server(state_mp4) as (base_url, _port):
        st_no_src, _, raw_no_src = _http_request(
            f"{base_url}/api/render",
            method="POST",
            json_body={"scale": 1, "mode": "mp4"},
        )
        assert st_no_src == 400
        assert "error" in json.loads(raw_no_src.decode("utf-8"))

    # 2. Scene-backed UiState parameter validation & missing job 404s
    proj_json, _ = _create_canvas_project(tmp_path / "proj_val")
    state_proj = kinearc_ui.UiState(project_path=str(proj_json), out_dir=str(tmp_path / "proj_val" / ".kinearc_analysis"))

    with _running_server(state_proj) as (base_url, _port):
        bad_payloads = [
            {"scale": 0, "mode": "mp4"},
            {"scale": -1, "mode": "mp4"},
            {"scale": True, "mode": "mp4"},
            {"scale": "nan", "mode": "mp4"},
            {"scale": 1, "mode": "webm"},
            {"scale": 1, "mode": "mp4", "fps": 0},
            {"scale": 1, "mode": "mp4", "crf": 99},
            {"scale": 1, "mode": "mp4", "out": "../escape.mp4"},
            {"scale": 1, "mode": "stills", "times": [-0.5]},
            {"scale": 1, "mode": "stills", "times": ""},
        ]
        for body in bad_payloads:
            st, _, raw = _http_request(f"{base_url}/api/render", method="POST", json_body=body)
            assert st == 400, f"Expected 400 for {body!r}, got {st} ({raw!r})"
            assert "error" in json.loads(raw.decode("utf-8"))

        st_missing_job, _, _ = _http_request(f"{base_url}/api/render/nonexistent_job_id")
        assert st_missing_job == 404

        st_load_missing, _, _ = _http_request(
            f"{base_url}/api/render/load",
            method="POST",
            json_body={"job_id": "nonexistent_job_id"},
        )
        assert st_load_missing == 404

        st_load_trav, _, _ = _http_request(
            f"{base_url}/api/render/load",
            method="POST",
            json_body={"path": "../secret.mp4"},
        )
        assert st_load_trav == 400

        # Invalid/corrupted MP4 inside renders/ returns 400 without clobbering existing info geometry
        renders_dir = Path(state_proj.renders_dir)
        renders_dir.mkdir(parents=True, exist_ok=True)
        corrupt_mp4 = renders_dir / "corrupt.mp4"
        corrupt_mp4.write_bytes(b"NOT_A_VALID_MP4")

        st_before, _, raw_before = _http_request(f"{base_url}/api/info")
        assert st_before == 200
        info_before = json.loads(raw_before.decode("utf-8"))

        st_corrupt, _, raw_corrupt = _http_request(
            f"{base_url}/api/render/load",
            method="POST",
            json_body={"path": "renders/corrupt.mp4"},
        )
        assert st_corrupt == 400
        assert "error" in json.loads(raw_corrupt.decode("utf-8"))

        st_after, _, raw_after = _http_request(f"{base_url}/api/info")
        assert st_after == 200
        info_after = json.loads(raw_after.decode("utf-8"))
        assert info_after["width"] == info_before["width"] == 320
        assert info_after["height"] == info_before["height"] == 180
        assert info_after["fps"] == info_before["fps"]
        assert info_after["total_frames"] == info_before["total_frames"]
        assert info_after["has_video"] == info_before["has_video"] is False


def test_load_rendered_video_rolls_back_all_geometry_on_zero_dim_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kinearc_ui

    good_clone = tmp_path / "good_clone.mp4"
    good_ref = tmp_path / "good_ref.mp4"
    _write_mp4(good_clone, [np.full((180, 320, 3), (20, 40, 80), dtype=np.uint8) for _ in range(6)], fps=30.0)
    _write_mp4(good_ref, [np.full((180, 320, 3), (10, 20, 40), dtype=np.uint8) for _ in range(6)], fps=24.0)

    state = kinearc_ui.UiState(
        clone_path=str(good_clone),
        ref_path=str(good_ref),
        out_dir=str(tmp_path / ".kinearc_rollback"),
    )
    bad_mp4 = tmp_path / "zero_dim.mp4"
    bad_mp4.write_bytes(b"placeholder")

    class _ZeroCap:
        def isOpened(self) -> bool:
            return True

        def get(self, prop: int) -> float:
            if prop == cv2.CAP_PROP_FPS:
                return 30.0
            return 0.0

        def release(self) -> None:
            pass

    monkeypatch.setattr(cv2, "VideoCapture", lambda _p: _ZeroCap())
    with pytest.raises(ValueError, match="Invalid video dimensions"):
        state.load_rendered_video(str(bad_mp4))

    assert state.clone_path == str(good_clone.resolve())
    assert state.ref_path == str(good_ref.resolve())
    assert state.ref_fps == pytest.approx(24.0)
    assert state.width == 320
    assert state.height == 180
    assert state.fps == pytest.approx(30.0)
    assert state.total_frames == 6
    assert state.duration_sec == pytest.approx(0.2)
