import http.client
import json
import math
import struct
import sys
import threading
import urllib.error
import urllib.request
import wave
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


def _write_wav(path: Path, segments: list[tuple[float, float, float]], sample_rate: int = 16000) -> None:
    """Write mono 16-bit PCM WAV from (duration_sec, freq_hz, amplitude) tuples."""
    samples: list[int] = []
    for dur_sec, freq_hz, amp in segments:
        count = int(round(dur_sec * sample_rate))
        for i in range(count):
            val = amp * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate)) if freq_hz > 0 and amp > 0 else 0.0
            samples.append(max(-32767, min(32767, int(round(val * 32767.0)))))

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


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


def _http_request(url: str, method: str = "GET", json_body: dict | None = None, headers: dict | None = None):
    req_headers = dict(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()), err.read()


def _raw_get(port: int, raw_path: str):
    """Send raw unnormalized HTTP request path (preserves literal /../ segments)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", raw_path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, dict(resp.getheaders()), body
    finally:
        conn.close()


def test_fixture_a_full_mp4_wav_sidecars_and_audio_endpoints(tmp_path: Path) -> None:
    import kinearc_ui

    clone_path = tmp_path / "clone.mp4"
    ref_path = tmp_path / "orig.mp4"
    voice_path = tmp_path / "vo.wav"
    bgm_path = tmp_path / "bgm.wav"
    sfx_wav = tmp_path / "pop.wav"
    cues_path = tmp_path / "cues.json"
    out_dir = tmp_path / ".kinearc_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cuts").mkdir(parents=True, exist_ok=True)

    clone_frames = []
    ref_frames = []
    for i in range(10):
        cf = np.full((240, 320, 3), (20, 30, 40), dtype=np.uint8)
        rf = np.full((240, 320, 3), (20, 30, 40), dtype=np.uint8)
        cv2.rectangle(cf, (20 + i * 8, 40), (80 + i * 8, 120), (0, 200, 255), -1)
        cv2.rectangle(rf, (20 + i * 4, 40), (80 + i * 4, 120), (255, 180, 0), -1)
        clone_frames.append(cf)
        ref_frames.append(rf)
    _write_mp4(clone_path, clone_frames, fps=30.0)
    _write_mp4(ref_path, ref_frames, fps=30.0)

    # 1.55s WAV: 0.50s 440Hz + 0.55s silence + 0.50s 550Hz
    _write_wav(voice_path, [(0.50, 440.0, 0.5), (0.55, 0.0, 0.0), (0.50, 550.0, 0.8)])
    _write_wav(bgm_path, [(0.60, 220.0, 0.25)])
    _write_wav(sfx_wav, [(0.15, 880.0, 0.6)])

    cues_data = [{"file": str(sfx_wav), "time": 0.15, "volume": 0.85}]
    cues_path.write_text(json.dumps(cues_data), encoding="utf-8")

    # Sidecars matching extract_full_motion.py & verify_motion_diff.py schemas
    cut_img = np.full((60, 120, 3), (80, 160, 240), dtype=np.uint8)
    cv2.imwrite(str(out_dir / "cuts" / "cut_0000.png"), cut_img)
    (out_dir / "scene_cuts.json").write_text(
        json.dumps(
            {
                "fps": 30.0,
                "total_frames": 10,
                "cut_threshold": 18.0,
                "cuts": [
                    {
                        "cut_index": 0,
                        "before_frame": 4,
                        "after_frame": 5,
                        "timestamp_sec": 0.1667,
                        "delta_mae": 31.5,
                        "pair_image": "cuts/cut_0000.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (out_dir / "verification_report.json").write_text(
        json.dumps(
            {
                "overall_mae": 7.42,
                "overall_psnr_db": 28.9,
                "clone_loop_mae": 2.345,
                "worst_frames": [
                    {"rank": 1, "frame": 6, "timestamp_sec": 0.2, "mae": 18.7}
                ],
            }
        ),
        encoding="utf-8",
    )
    (out_dir / "metadata.json").write_text(
        json.dumps({"fps": 30.0, "working_size": [320, 240], "source_loop_mae": 1.125}),
        encoding="utf-8",
    )

    state = kinearc_ui.UiState(
        clone_path=str(clone_path),
        ref_path=str(ref_path),
        out_dir=str(out_dir),
        voice_path=str(voice_path),
        bgm_path=str(bgm_path),
        sfx_path=str(cues_path),
    )

    with _running_server(state) as (base_url, port):
        # Root placeholder HTML when scripts/ui/index.html is not yet created
        status, headers, body = _http_request(f"{base_url}/")
        assert status == 200
        assert "kinearc" in body.decode("utf-8").lower()

        # /api/info and /api/meta
        for info_ep in ("/api/info", "/api/meta"):
            st, _, raw = _http_request(f"{base_url}{info_ep}")
            assert st == 200
            info = json.loads(raw.decode("utf-8"))
            assert info["has_video"] is True
            assert info["has_ref"] is True
            assert info["hasRef"] is True
            assert info["has_live_scene"] is False
            assert info["mode_default"] == "clone"
            assert info["width"] == 320
            assert info["height"] == 240
            assert info["fps"] == pytest.approx(30.0)
            assert info["totalFrames"] == 10
            assert info["total_frames"] == 10
            assert info["duration_sec"] > 0.2
            assert len(info["scene_cuts"]) == 1
            assert info["scene_cuts"][0]["before_frame"] == 4
            assert len(info["worst_frames"]) == 1
            assert info["worst_frames"][0]["frame"] == 6
            assert info["clone_loop_mae"] == pytest.approx(2.345)
            assert info["source_loop_mae"] == pytest.approx(1.125)
            assert info["overall_mae"] == pytest.approx(7.42)
            assert info["sfx_cues"] == cues_data
            assert info["audio"]["voice"] is True
            assert info["audio"]["bgm"] is True

        # Frames: clone, diff, legacy route, png, and 404 on OOB
        for frame_url in (
            f"{base_url}/api/frame?idx=2&kind=clone",
            f"{base_url}/api/frame?idx=2&kind=diff",
            f"{base_url}/api/frame/clone/2",
        ):
            st, hdrs, img_bytes = _http_request(frame_url)
            assert st == 200
            assert hdrs.get("Content-Type", "").startswith("image/jpeg")
            assert img_bytes[:2] == b"\xff\xd8"
            decoded = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            assert decoded is not None and decoded.shape == (240, 320, 3)

        st_png, hdrs_png, png_bytes = _http_request(f"{base_url}/api/frame?idx=2&kind=clone&fmt=png")
        assert st_png == 200
        assert hdrs_png.get("Content-Type", "").startswith("image/png")
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

        st_oob, _, oob_raw = _http_request(f"{base_url}/api/frame?idx=999&kind=clone")
        assert st_oob == 404
        assert "error" in json.loads(oob_raw.decode("utf-8"))

        # Waveform peaks
        st_pk, _, pk_raw = _http_request(f"{base_url}/api/audio-peaks?track=voice&bins=40")
        assert st_pk == 200
        peaks = json.loads(pk_raw.decode("utf-8"))
        assert len(peaks["bins"]) == 40
        assert all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in peaks["bins"])
        assert peaks["duration_sec"] > 1.0
        assert peaks["max_peak"] > 0.1
        # Middle silent section bins should be near 0 while ends are active
        assert max(peaks["bins"][16:23]) < 0.05
        assert max(peaks["bins"][:10]) > 0.4
        assert max(peaks["bins"][30:]) > 0.7

        # Notes CRUD + snapshot + selection streaming
        st_post, _, note_raw = _http_request(
            f"{base_url}/api/notes",
            method="POST",
            json_body={"frame": 2, "bbox": [20, 30, 100, 110], "text": "Fix alignment"},
        )
        assert st_post == 201
        created = json.loads(note_raw.decode("utf-8"))
        assert created["id"] == 1
        assert created["status"] == "open"
        assert created["image"] == "selection/note_1.png"
        assert (out_dir / "selection.json").is_file()
        assert (out_dir / "selection" / "note_1.png").is_file()

        st_sel, _, sel_bytes = _http_request(f"{base_url}/selection/note_1.png")
        assert st_sel == 200
        assert sel_bytes[:8] == b"\x89PNG\r\n\x1a\n"

        st_patch, _, patch_raw = _http_request(
            f"{base_url}/api/notes/1",
            method="PATCH",
            json_body={"status": "done", "text": "Aligned"},
        )
        assert st_patch == 200
        assert json.loads(patch_raw.decode("utf-8"))["status"] == "done"

        st_del, _, _ = _http_request(f"{base_url}/api/notes/1", method="DELETE")
        assert st_del == 200
        assert not (out_dir / "selection" / "note_1.png").exists()
        assert json.loads((out_dir / "selection.json").read_text(encoding="utf-8")) == []

        # Range request on /video/clone & /cuts serving
        st_rng, rng_hdrs, rng_bytes = _http_request(
            f"{base_url}/video/clone",
            headers={"Range": "bytes=0-63"},
        )
        assert st_rng == 206
        assert len(rng_bytes) == 64
        assert "Content-Range" in rng_hdrs

        st_cut, _, _ = _http_request(f"{base_url}/cuts/cut_0000.png")
        assert st_cut == 200
        st_cut_trav, _, _ = _raw_get(port, "/cuts/../../secret.txt")
        assert st_cut_trav == 403

        # Cut pauses
        st_cp, _, cp_raw = _http_request(
            f"{base_url}/api/audio/cut-pauses",
            method="POST",
            json_body={"track": "voice", "threshold": -32.0, "min_silence": 0.4, "pad": 0.05},
        )
        assert st_cp == 200
        cp_res = json.loads(cp_raw.decode("utf-8"))
        assert cp_res["ok"] is True
        assert len(cp_res["keep_segments"]) == 2
        renders_dir = out_dir / "renders"
        assert renders_dir.is_dir()
        trimmed_file = out_dir / cp_res["out"]
        cuts_file = out_dir / cp_res["cuts_json"]
        assert trimmed_file.is_file()
        assert cuts_file.is_file()
        assert Path(state.voice_path).resolve() == trimmed_file.resolve()

        # Audio mix with nonexistent path -> 400 JSON and server remains alive!
        st_bad_mix, _, bad_mix_raw = _http_request(
            f"{base_url}/api/audio/mix",
            method="POST",
            json_body={"voice": str(tmp_path / "missing_voice_xyz.wav")},
        )
        assert st_bad_mix == 400
        assert "error" in json.loads(bad_mix_raw.decode("utf-8"))

        st_alive, _, _ = _http_request(f"{base_url}/api/info")
        assert st_alive == 200

        # Valid audio mix -> writes MP4 in <out_dir>/renders/ and streams via /renders/
        st_mix, _, mix_raw = _http_request(
            f"{base_url}/api/audio/mix",
            method="POST",
            json_body={"voice_vol": 1.0, "bgm_vol": 0.3, "fade_out": 0.1, "out": "final_mix.mp4"},
        )
        assert st_mix == 200
        mix_res = json.loads(mix_raw.decode("utf-8"))
        assert mix_res["ok"] is True
        mixed_mp4 = out_dir / mix_res["out"]
        assert mixed_mp4.is_file()
        st_render, _, render_bytes = _http_request(f"{base_url}/renders/final_mix.mp4")
        assert st_render == 200
        assert len(render_bytes) > 100


def test_fixture_b_live_scene_only_and_path_traversal_guard(tmp_path: Path) -> None:
    import kinearc_ui

    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    scene_html = scenes_dir / "01.html"
    scene_html.write_text(
        "<!doctype html><html><body><script>window.kinearc = { seek(t) {} };</script></body></html>",
        encoding="utf-8",
    )
    (scenes_dir / "scene.mjs").write_text("export const version = 1;\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP_SECRET", encoding="utf-8")

    out_dir = tmp_path / ".kinearc_analysis"
    state = kinearc_ui.UiState(clone_path=None, scene_path=str(scene_html), out_dir=str(out_dir))

    with _running_server(state) as (base_url, port):
        st_info, _, raw_info = _http_request(f"{base_url}/api/info")
        assert st_info == 200
        info = json.loads(raw_info.decode("utf-8"))
        assert info["has_video"] is False
        assert info["has_live_scene"] is True
        assert info["mode_default"] == "live"
        assert info["live_scene_url"] == "/api/scene/01.html"

        st_scene, hdr_scene, body_scene = _http_request(f"{base_url}/api/scene/01.html")
        assert st_scene == 200
        assert "text/html" in hdr_scene.get("Content-Type", "")
        assert "no-store" in hdr_scene.get("Cache-Control", "")
        assert "window.kinearc" in body_scene.decode("utf-8")

        st_mjs, hdr_mjs, _ = _http_request(f"{base_url}/api/scene/scene.mjs")
        assert st_mjs == 200
        assert "javascript" in hdr_mjs.get("Content-Type", "")

        # Raw traversal and encoded traversal both MUST return 403!
        st_trav1, _, _ = _raw_get(port, "/api/scene/../../secret.txt")
        assert st_trav1 == 403
        st_trav2, _, _ = _raw_get(port, "/api/scene/%2e%2e/secret.txt")
        assert st_trav2 == 403

        # Notes still work in live-scene-only mode without crashing
        st_note, _, note_raw = _http_request(
            f"{base_url}/api/notes",
            method="POST",
            json_body={"frame": 15, "point": [120, 240], "text": "Adjust ease curve"},
        )
        assert st_note == 201
        note = json.loads(note_raw.decode("utf-8"))
        assert note["image"] == ""


def test_project_manifest_source_validation_and_waveform_errors(tmp_path: Path) -> None:
    import kinearc_ui

    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    (scenes_dir / "intro.html").write_text("<html><body>Intro</body></html>", encoding="utf-8")
    (scenes_dir / "cta.html").write_text("<html><body>CTA</body></html>", encoding="utf-8")
    voice_wav = tmp_path / "vo.wav"
    _write_wav(voice_wav, [(0.4, 440.0, 0.5)])

    proj_file = tmp_path / "kinearc.project.json"
    proj_file.write_text(
        json.dumps(
            {
                "width": 1280,
                "height": 720,
                "fps": 60,
                "duration_sec": 4.0,
                "scenes": ["scenes/intro.html", {"name": "CTA", "path": "scenes/cta.html"}],
                "audio": {"voice": "vo.wav"},
            }
        ),
        encoding="utf-8",
    )

    state = kinearc_ui.UiState(project_path=str(proj_file), out_dir=str(tmp_path / ".kinearc_analysis"))
    assert state.width == 1280
    assert state.height == 720
    assert state.fps == 60.0
    assert state.total_frames == 240
    assert len(state.scenes) == 2
    assert state.live_scene_url == "/api/scene/scenes/intro.html"
    assert Path(state.voice_path).resolve() == voice_wav.resolve()

    with pytest.raises(ValueError):
        kinearc_ui.UiState(out_dir=str(tmp_path / ".kinearc_analysis"))

    with pytest.raises(SystemExit) as exc_info:
        kinearc_ui.main(["--no-open"])
    assert exc_info.value.code != 0

    with pytest.raises(FileNotFoundError):
        kinearc_ui.extract_waveform_peaks(str(tmp_path / "no_audio.wav"))

    with pytest.raises(ValueError):
        kinearc_ui.extract_waveform_peaks(str(voice_wav), bins=0)


def test_review_viewer_compatibility_shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import kinearc_ui
    import review_viewer

    video_path = tmp_path / "sample.mp4"
    _write_mp4(video_path, [np.zeros((120, 160, 3), dtype=np.uint8) for _ in range(4)], fps=30.0)

    legacy_out = tmp_path / "legacy_out"
    state = review_viewer.ViewerState(str(video_path), None, str(legacy_out))
    assert isinstance(state, kinearc_ui.UiState)
    assert Path(state.out_dir).resolve() == legacy_out.resolve()

    captured = []
    monkeypatch.setattr(kinearc_ui, "main", lambda argv=None: captured.append(argv))
    review_viewer.main([str(video_path), "--no-open"])
    assert captured == [[str(video_path), "--no-open"]]



def test_cross_fps_ref_alignment_dual_mode_and_ui_static_serving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import kinearc_ui

    # Clone at 60fps (12 frames = 0.20s), Ref at 30fps (6 frames = 0.20s) at half resolution.
    # At clone idx=6 (t=0.10s), aligned ref frame is idx=3, which has bright green vs dark clone.
    clone_frames = [np.full((120, 160, 3), (10, 10, 10), dtype=np.uint8) for _ in range(12)]
    ref_frames = [np.full((60, 80, 3), (10, 10, 10), dtype=np.uint8) for _ in range(6)]
    ref_frames[3] = np.full((60, 80, 3), (0, 255, 0), dtype=np.uint8)

    clone_mp4 = tmp_path / "clone60.mp4"
    ref_mp4 = tmp_path / "ref30.mp4"
    _write_mp4(clone_mp4, clone_frames, fps=60.0)
    _write_mp4(ref_mp4, ref_frames, fps=30.0)

    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    scene_html = scenes_dir / "01.html"
    scene_html.write_text("<!doctype html><html><body>Dual Scene</body></html>", encoding="utf-8")

    ui_dir = tmp_path / "mock_ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / "index.html").write_text("<!doctype html><html><body>Custom UI</body></html>", encoding="utf-8")
    (ui_dir / "app.js").write_text("console.log('kinearc');\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("NO_ESCAPE", encoding="utf-8")
    monkeypatch.setattr(kinearc_ui, "UI_DIR", str(ui_dir))

    silent_wav = tmp_path / "silent.wav"
    _write_wav(silent_wav, [(0.3, 0.0, 0.0)])

    state = kinearc_ui.UiState(
        clone_path=str(clone_mp4),
        ref_path=str(ref_mp4),
        scene_path=str(scene_html),
        out_dir=str(tmp_path / ".kinearc_analysis"),
        voice_path=str(silent_wav),
    )

    # Verify cross-FPS aligned diff peaks at clone idx=6 (aligned to ref idx=3)
    diff_at_6 = state.get_diff_frame_bgr(6)
    diff_at_0 = state.get_diff_frame_bgr(0)
    assert diff_at_6 is not None and diff_at_6.shape == (120, 160, 3)
    assert diff_at_0 is not None and diff_at_0.shape == (120, 160, 3)
    assert float(diff_at_0[..., 0].mean()) > float(diff_at_0[..., 2].mean())  # Cool blue at 0 diff
    assert float(diff_at_6[..., 2].mean()) > float(diff_at_6[..., 0].mean())  # Hot red at aligned diff

    # Silent waveform returns all 0.0 bins cleanly
    silent_peaks = kinearc_ui.extract_waveform_peaks(str(silent_wav), bins=20)
    assert silent_peaks["bins"] == [0.0] * 20
    assert silent_peaks["max_peak"] == 0.0

    with _running_server(state) as (base_url, port):
        st_info, _, raw_info = _http_request(f"{base_url}/api/info")
        assert st_info == 200
        info = json.loads(raw_info.decode("utf-8"))
        assert info["has_video"] is True
        assert info["has_live_scene"] is True
        assert info["mode_default"] == "clone"
        assert info["audio"]["video"] is False

        # UI static serving + traversal guard
        st_root, _, body_root = _http_request(f"{base_url}/")
        assert st_root == 200 and "Custom UI" in body_root.decode("utf-8")
        st_js, hdr_js, _ = _http_request(f"{base_url}/ui/app.js")
        assert st_js == 200 and "javascript" in hdr_js.get("Content-Type", "")
        st_ui_trav, _, _ = _raw_get(port, "/ui/../outside.txt")
        assert st_ui_trav == 403

        # Error responses keep server healthy
        st_bad_kind, _, _ = _http_request(f"{base_url}/api/frame?idx=0&kind=bogus")
        assert st_bad_kind == 400
        st_missing_bgm, _, _ = _http_request(f"{base_url}/api/audio-peaks?track=bgm")
        assert st_missing_bgm == 404
        st_silent_vid_peaks, _, silent_vid_raw = _http_request(f"{base_url}/api/audio-peaks?track=video")
        assert st_silent_vid_peaks == 404
        assert "no audio stream" in json.loads(silent_vid_raw.decode("utf-8"))["error"].lower()
        st_no_vid_audio, _, _ = _http_request(
            f"{base_url}/api/audio/cut-pauses",
            method="POST",
            json_body={"track": "video"},
        )
        assert st_no_vid_audio == 400
        st_ok, _, _ = _http_request(f"{base_url}/api/info")
        assert st_ok == 200


def test_hardening_notes_validation_geometry_cross_drive_and_muxed_video_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    import audio_mix
    import kinearc_ui

    silent_mp4 = tmp_path / "silent.mp4"
    _write_mp4(silent_mp4, [np.full((120, 160, 3), (30, 40, 50), dtype=np.uint8) for _ in range(6)], fps=30.0)
    voice_wav = tmp_path / "vo.wav"
    _write_wav(voice_wav, [(0.3, 440.0, 0.7)])
    muxed_mp4 = tmp_path / "muxed.mp4"
    audio_mix.cmd_mix(
        argparse.Namespace(
            video=str(silent_mp4),
            voice=str(voice_wav),
            bgm=None,
            sfx=None,
            out=str(muxed_mp4),
            voice_vol=1.0,
            bgm_vol=0.35,
            video_vol=1.0,
            fade_out=0.0,
            keep_video_audio=False,
        )
    )

    state_muxed = kinearc_ui.UiState(clone_path=str(muxed_mp4), out_dir=str(tmp_path / ".kinearc_muxed"))
    assert state_muxed.build_info_payload()["audio"]["video"] is True

    with _running_server(state_muxed) as (base_url, _port):
        st_pk, _, pk_raw = _http_request(f"{base_url}/api/audio-peaks?track=video&bins=20")
        assert st_pk == 200
        pk = json.loads(pk_raw.decode("utf-8"))
        assert len(pk["bins"]) == 20
        assert pk["max_peak"] > 0.1

        # Invalid POST /api/notes optional fields return HTTP 400 JSON cleanly
        invalid_note_bodies = [
            {"frame": -1, "text": "neg"},
            {"frame": True, "text": "bool frame"},
            {"frame": 0, "time_sec": "not-a-num"},
            {"frame": 0, "time_sec": -0.25},
            {"frame": 0, "bbox": [1, 2]},
            {"frame": 0, "bbox": [1, 2, "x", 4]},
            {"frame": 0, "point": [1]},
            {"frame": 0, "point": [True, 2]},
            {"frame": 0, "text": None},
            {"frame": 0, "text": 123},
        ]
        for body in invalid_note_bodies:
            st, _, raw = _http_request(f"{base_url}/api/notes", method="POST", json_body=body)
            assert st == 400, f"Expected 400 for {body!r}, got {st}"
            assert "error" in json.loads(raw.decode("utf-8"))

        # Valid note + invalid PATCH validation
        st_ok_note, _, _ = _http_request(
            f"{base_url}/api/notes",
            method="POST",
            json_body={"frame": 1, "time_sec": 0.033, "point": [10, 20], "text": "Valid"},
        )
        assert st_ok_note == 201
        st_bad_patch1, _, _ = _http_request(
            f"{base_url}/api/notes/1", method="PATCH", json_body={"status": "invalid"}
        )
        assert st_bad_patch1 == 400
        st_bad_patch2, _, _ = _http_request(
            f"{base_url}/api/notes/1", method="PATCH", json_body={"text": None}
        )
        assert st_bad_patch2 == 400

        st_alive, _, _ = _http_request(f"{base_url}/api/info")
        assert st_alive == 200

    # Geometry validation: non-finite/non-positive FPS fallback to 30.0 & invalid width/height raises
    bad_proj = tmp_path / "bad_dims.project.json"
    bad_proj.write_text(json.dumps({"width": 0, "height": 720, "scenes": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        kinearc_ui.UiState(project_path=str(bad_proj), out_dir=str(tmp_path / ".kinearc_bad"))

    nan_proj = tmp_path / "nan_fps.project.json"
    scene_html = tmp_path / "scene.html"
    scene_html.write_text("<html></html>", encoding="utf-8")
    nan_proj.write_text(
        json.dumps({"width": 1280, "height": 720, "fps": -5, "scenes": ["scene.html"]}),
        encoding="utf-8",
    )
    nan_state = kinearc_ui.UiState(project_path=str(nan_proj), out_dir=str(tmp_path / ".kinearc_nan"))
    assert nan_state.fps == 30.0

    class _FakeCap:
        def __init__(self, w: float, h: float, fps_val: float):
            self._w = w
            self._h = h
            self._fps = fps_val
            self.released = False

        def isOpened(self) -> bool:
            return True

        def get(self, prop: int) -> float:
            if prop == cv2.CAP_PROP_FRAME_WIDTH:
                return self._w
            if prop == cv2.CAP_PROP_FRAME_HEIGHT:
                return self._h
            if prop == cv2.CAP_PROP_FPS:
                return self._fps
            if prop == cv2.CAP_PROP_FRAME_COUNT:
                return 10.0
            return 0.0

        def release(self) -> None:
            self.released = True

    monkeypatch.setattr(cv2, "VideoCapture", lambda _p: _FakeCap(320.0, 240.0, float("nan")))
    st_nan_cap = kinearc_ui.UiState(
        clone_path=str(silent_mp4),
        ref_path=str(silent_mp4),
        out_dir=str(tmp_path / ".kinearc_nan_cap"),
    )
    assert st_nan_cap.fps == 30.0
    assert st_nan_cap.ref_fps == 30.0

    monkeypatch.setattr(cv2, "VideoCapture", lambda _p: _FakeCap(0.0, 240.0, 30.0))
    with pytest.raises(ValueError):
        kinearc_ui.UiState(clone_path=str(silent_mp4), out_dir=str(tmp_path / ".kinearc_zero_cap"))

    monkeypatch.undo()

    # Cross-drive Windows commonpath ValueError inside _init_scenes must not crash
    def _raise_cross_drive(_paths):
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr("os.path.commonpath", _raise_cross_drive)
    cross_state = kinearc_ui.UiState(
        project_path=str(nan_proj),
        scene_path=str(scene_html),
        out_dir=str(tmp_path / ".kinearc_cross"),
    )
    assert cross_state.width == 1280
    assert cross_state.live_scene_url is None

    monkeypatch.undo()

    # _safe_write returns bool and stops stream_file_range immediately on broken pipe
    big_file = tmp_path / "big.bin"
    big_file.write_bytes(b"x" * (65536 * 4))
    handler_cls = kinearc_ui.make_handler(cross_state)
    h = handler_cls.__new__(handler_cls)
    h.headers = {}
    h.request_version = "HTTP/1.1"
    h.close_connection = True
    write_calls = 0

    class _FakeWFile:
        def write(self, data: bytes) -> None:
            nonlocal write_calls
            write_calls += 1
            if write_calls >= 2:
                raise BrokenPipeError("client disconnected")

    h.wfile = _FakeWFile()
    h.send_response = lambda *_a, **_kw: None
    h.send_header = lambda *_a, **_kw: None
    h.end_headers = lambda: None
    h.stream_file_range(str(big_file), "application/octet-stream")
    assert write_calls == 2

    # main() cancels open_timer in finally on KeyboardInterrupt
    import threading
    import webbrowser

    class _FakeTimer:
        def __init__(self, interval, fn):
            self.canceled = False
            self.daemon = False
            self.started = False

        def start(self):
            self.started = True

        def cancel(self):
            self.canceled = True

    class _FakeServer:
        def __init__(self):
            self.shut_down = False
            self.closed = False

        def serve_forever(self):
            raise KeyboardInterrupt()

        def shutdown(self):
            self.shut_down = True

        def server_close(self):
            self.closed = True

    fake_timers = []
    fake_server = _FakeServer()
    monkeypatch.setattr(threading, "Timer", lambda interval, fn: fake_timers.append(_FakeTimer(interval, fn)) or fake_timers[-1])
    monkeypatch.setattr(webbrowser, "open", lambda _u: True)
    monkeypatch.setattr(kinearc_ui, "create_server", lambda _st, port=4175: (fake_server, 4175))
    kinearc_ui.main([str(silent_mp4), "--out_dir", str(tmp_path / ".kinearc_ki")])
    assert len(fake_timers) == 1
    assert fake_timers[0].started is True
    assert fake_timers[0].canceled is True
    assert fake_server.shut_down is True
    assert fake_server.closed is True
