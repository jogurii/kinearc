import json
import math
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

import cv2
import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
ENGINE_DIR = REPO_ROOT / "engine"
BROWSER_FIND_MJS = ENGINE_DIR / "browser_find.mjs"
RENDER_MJS = ENGINE_DIR / "render.mjs"


def _require_runtime_tools() -> tuple[str, str, str]:
    node_bin = shutil.which("node")
    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")
    assert node_bin, "Node.js 24+ is required for engine tests"
    assert ffmpeg_bin, "ffmpeg is required on PATH for engine tests"
    assert ffprobe_bin, "ffprobe is required on PATH for engine tests"
    return node_bin, ffmpeg_bin, ffprobe_bin


def _ffprobe_json(ffprobe_bin: str, video_path: Path) -> dict:
    proc = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _write_wav(path: Path, duration_sec: float = 0.6, freq_hz: float = 440.0, amp: float = 0.4, sample_rate: int = 16000) -> None:
    count = int(round(duration_sec * sample_rate))
    samples = [
        max(-32767, min(32767, int(round(amp * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate)) * 32767.0))))
        for i in range(count)
    ]
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_browser_find_env_override_and_invalid_override(tmp_path: Path) -> None:
    node_bin, _, _ = _require_runtime_tools()
    assert BROWSER_FIND_MJS.is_file(), f"Missing {BROWSER_FIND_MJS}"

    fake_chrome = tmp_path / "custom-chrome.exe"
    fake_chrome.write_bytes(b"binary")
    missing_chrome = tmp_path / "does-not-exist-chrome.exe"

    script = f"""
import assert from 'node:assert/strict';
import {{ pathToFileURL }} from 'node:url';

const mod = await import({json.dumps(BROWSER_FIND_MJS.as_uri())});
const {{ findBrowserExecutable }} = mod;

// 1. Valid CHROME_PATH override
const hit = findBrowserExecutable({{
  env: {{ CHROME_PATH: {json.dumps(str(fake_chrome))} }},
}});
assert.equal(hit, {json.dumps(str(fake_chrome))});

// 2. Explicit nonexistent CHROME_PATH must throw cleanly instead of falling back
assert.throws(
  () => findBrowserExecutable({{ env: {{ CHROME_PATH: {json.dumps(str(missing_chrome))} }} }}),
  /CHROME_PATH/
);

// 3. Cross-platform win32 Edge fallback
const winEdge = 'C:\\\\Program Files (x86)\\\\Microsoft\\\\Edge\\\\Application\\\\msedge.exe';
assert.equal(
  findBrowserExecutable({{
    platform: 'win32',
    env: {{
      PROGRAMFILES: 'C:\\\\Program Files',
      'PROGRAMFILES(X86)': 'C:\\\\Program Files (x86)',
      LOCALAPPDATA: 'C:\\\\Users\\\\demo\\\\AppData\\\\Local',
    }},
    exists: (p) => p === winEdge,
  }}),
  winEdge
);

// 4. Cross-platform darwin Chrome lookup
const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
assert.equal(
  findBrowserExecutable({{
    platform: 'darwin',
    env: {{}},
    exists: (p) => p === macChrome,
  }}),
  macChrome
);

// 5. Cross-platform linux PATH lookup & null when absent
assert.equal(
  findBrowserExecutable({{
    platform: 'linux',
    env: {{ PATH: '/opt/bin:/usr/local/bin' }},
    exists: (p) => p === '/opt/bin/chromium',
  }}),
  '/opt/bin/chromium'
);
assert.equal(
  findBrowserExecutable({{
    platform: 'linux',
    env: {{ PATH: '' }},
    exists: () => false,
  }}),
  null
);

console.log('BROWSER_FIND_OK');
"""
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"STDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}"
    assert "BROWSER_FIND_OK" in proc.stdout


def test_stills_capture_produces_pngs(tmp_path: Path) -> None:
    node_bin, _, _ = _require_runtime_tools()
    assert RENDER_MJS.is_file(), f"Missing {RENDER_MJS}"

    scene_html = tmp_path / "stills_scene.html"
    scene_html.write_text(
        """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Stills Scene</title></head>
<body style="margin:0;overflow:hidden;background:#09090b;">
<canvas id="c" width="640" height="360" style="width:100vw;height:100vh;display:block;"></canvas>
<script>
const c = document.getElementById('c');
const ctx = c.getContext('2d');
function draw(t) {
  ctx.fillStyle = '#09090b';
  ctx.fillRect(0, 0, 640, 360);
  const x = Math.round(40 + Math.min(1, Math.max(0, t)) * 420);
  ctx.fillStyle = '#ff6b2c';
  ctx.fillRect(x, 100, 140, 160);
}
const q = new URLSearchParams(location.search);
const initT = parseFloat(q.get('t') || '0') || 0;
const ready = Promise.resolve().then(() => draw(initT));
window.kinearc = { totalDuration: 1.0, ready, seek: draw };
</script>
</body>
</html>
""",
        encoding="utf-8",
    )

    out_dir = tmp_path / "stills_out"
    proc = subprocess.run(
        [
            node_bin,
            str(RENDER_MJS),
            "stills",
            "--scene",
            str(scene_html),
            "--out_dir",
            str(out_dir),
            "--times",
            "0.1,0.6",
            "--scale",
            "1",
            "--width",
            "640",
            "--height",
            "360",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"stills failed:\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}"

    still_0 = out_dir / "still_0_0.1s.png"
    still_1 = out_dir / "still_1_0.6s.png"
    assert still_0.is_file(), f"Missing {still_0}"
    assert still_1.is_file(), f"Missing {still_1}"

    img0 = cv2.imread(str(still_0))
    img1 = cv2.imread(str(still_1))
    assert img0 is not None and img1 is not None
    assert img0.shape[1] == 640 and img0.shape[0] == 360
    assert img1.shape[1] == 640 and img1.shape[0] == 360
    diff_mean = float(np.mean(np.abs(img0.astype(np.float32) - img1.astype(np.float32))))
    assert diff_mean > 1.0, f"Expected distinct pixels between t=0.1s and t=0.6s, got mean diff {diff_mean}"


def test_render_4k_scale2_and_webcodecs_or_fallback_exact_ffprobe(tmp_path: Path) -> None:
    _node_bin, _ffmpeg_bin, ffprobe_bin = _require_runtime_tools()
    assert RENDER_MJS.is_file(), f"Missing {RENDER_MJS}"

    scene_html = tmp_path / "portrait_4k.html"
    scene_html.write_text(
        """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Portrait 4K Alias Scene</title></head>
<body style="margin:0;overflow:hidden;background:#0a0f1c;">
<canvas id="c" style="width:100vw;height:100vh;display:block;"></canvas>
<script>
const q = new URLSearchParams(location.search);
const rawS = parseFloat(q.get('scale') || '1');
const S = Number.isFinite(rawS) && rawS > 0 ? rawS : 1;
const W = 1080, H = 1920;
const canvas = document.getElementById('c');
canvas.width = Math.round(W * S);
canvas.height = Math.round(H * S);
const ctx = canvas.getContext('2d');

window.TOTAL = 1.0;
window.renderAt = function(t) {
  ctx.setTransform(S, 0, 0, S, 0, 0);
  ctx.fillStyle = '#0a0f1c';
  ctx.fillRect(0, 0, W, H);
  const p = Math.min(1, Math.max(0, t / 1.0));
  ctx.fillStyle = '#22d3ee';
  ctx.fillRect(140, Math.round(200 + p * 1000), 800, 320);
};
window.renderAt(0);
</script>
</body>
</html>
""",
        encoding="utf-8",
    )

    proj_json = tmp_path / "kinearc.project.json"
    proj_json.write_text(
        json.dumps(
            {
                "fps": 60,
                "width": 1080,
                "height": 1920,
                "scenes": ["portrait_4k.html"],
            }
        ),
        encoding="utf-8",
    )

    out_mp4 = tmp_path / "out_4k.mp4"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPTS_DIR / "kinearc_cli.py"),
            "render",
            "--project",
            str(proj_json),
            "--out",
            str(out_mp4),
            "--scale",
            "2",
            "--fps",
            "60",
            "--crf",
            "16",
            "--json-progress",
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, f"4K render failed:\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}"
    assert out_mp4.is_file() and out_mp4.stat().st_size > 1024

    events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    progress_events = [ev for ev in events if ev.get("type") == "progress"]
    assert len(progress_events) >= 1, f"Expected --json-progress events, got:\n{proc.stdout}"
    assert progress_events[-1]["progress"] == pytest.approx(100.0, abs=0.5)

    probe = _ffprobe_json(ffprobe_bin, out_mp4)
    video_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    assert len(video_streams) == 1
    vs = video_streams[0]
    assert vs["width"] == 2160
    assert vs["height"] == 3840
    assert vs["codec_name"] == "h264"
    assert vs["pix_fmt"] == "yuv420p"
    assert vs["avg_frame_rate"] == "60/1"
    assert float(vs["duration"]) == pytest.approx(1.0, abs=0.08)
    frame_count = int(vs.get("nb_read_frames") or vs.get("nb_frames") or 0)
    assert frame_count >= 55


def test_render_even_dimension_clamping_and_with_audio_manifest(tmp_path: Path) -> None:
    node_bin, _, ffprobe_bin = _require_runtime_tools()
    assert RENDER_MJS.is_file(), f"Missing {RENDER_MJS}"

    # 1. Odd logical dimensions (321x181 -> clamped 320x180), silent render
    odd_dir = tmp_path / "odd_silent"
    odd_dir.mkdir(parents=True, exist_ok=True)
    odd_scene = odd_dir / "odd.html"
    odd_scene.write_text(
        """<!doctype html>
<html><body style="margin:0;overflow:hidden;background:#101018;">
<canvas id="c" width="321" height="181" style="width:100vw;height:100vh;display:block;"></canvas>
<script>
const ctx = document.getElementById('c').getContext('2d');
const seek = (t) => {
  ctx.fillStyle = '#101018';
  ctx.fillRect(0, 0, 321, 181);
  ctx.fillStyle = '#a855f7';
  ctx.fillRect(Math.round(t * 200), 40, 80, 80);
};
window.kinearc = { totalDuration: 0.3, ready: Promise.resolve().then(() => seek(0)), seek };
</script>
</body></html>
""",
        encoding="utf-8",
    )
    odd_proj = odd_dir / "kinearc.project.json"
    odd_proj.write_text(
        json.dumps({"fps": 30, "width": 321, "height": 181, "scenes": ["odd.html"], "audio": None}),
        encoding="utf-8",
    )
    odd_mp4 = odd_dir / "odd_out.mp4"
    proc_odd = subprocess.run(
        [node_bin, str(RENDER_MJS), "render", "--project", str(odd_proj), "--out", str(odd_mp4), "--scale", "1"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc_odd.returncode == 0, f"Odd dimension render failed:\n{proc_odd.stderr}\n{proc_odd.stdout}"
    probe_odd = _ffprobe_json(ffprobe_bin, odd_mp4)
    v_odd = [s for s in probe_odd["streams"] if s["codec_type"] == "video"]
    a_odd = [s for s in probe_odd["streams"] if s["codec_type"] == "audio"]
    assert len(v_odd) == 1 and len(a_odd) == 0
    assert v_odd[0]["width"] == 320 and v_odd[0]["height"] == 180
    assert v_odd[0]["codec_name"] == "h264" and v_odd[0]["pix_fmt"] == "yuv420p"
    assert v_odd[0]["avg_frame_rate"] == "30/1"

    # 2. Multi-scene project (Canvas scene + Pure DOM/SVG fallback scene) + WAV audio mux
    multi_dir = tmp_path / "multi_audio"
    (multi_dir / "scenes").mkdir(parents=True, exist_ok=True)
    (multi_dir / "audio").mkdir(parents=True, exist_ok=True)

    scene_canvas = multi_dir / "scenes" / "01_canvas.html"
    scene_canvas.write_text(
        """<!doctype html>
<html><body style="margin:0;overflow:hidden;background:#091526;">
<canvas id="c" width="320" height="180" style="width:100vw;height:100vh;display:block;"></canvas>
<script>
const ctx = document.getElementById('c').getContext('2d');
window.kinearc = {
  totalDuration: 0.3,
  boxColor: '#facc15',
  ready: Promise.resolve(),
  seek(t) {
    ctx.fillStyle = '#091526';
    ctx.fillRect(0, 0, 320, 180);
    ctx.fillStyle = this.boxColor;
    ctx.fillRect(20 + Math.round(t * 250), 50, 70, 70);
  }
};
window.kinearc.seek(0);
</script>
</body></html>
""",
        encoding="utf-8",
    )

    scene_dom = multi_dir / "scenes" / "02_dom.html"
    scene_dom.write_text(
        """<!doctype html>
<html><body style="margin:0;overflow:hidden;background:#1a0b2e;display:flex;align-items:center;justify-content:center;width:100vw;height:100vh;">
<div id="box" style="width:120px;height:60px;background:#34d399;border-radius:12px;"></div>
<script>
const box = document.getElementById('box');
const seek = (t) => {
  box.style.transform = `translateX(${Math.round((t - 0.15) * 180)}px)`;
};
window.kinearc = { totalDuration: 0.3, ready: Promise.resolve().then(() => seek(0)), seek };
</script>
</body></html>
""",
        encoding="utf-8",
    )

    voice_wav = multi_dir / "audio" / "voice.wav"
    bgm_wav = multi_dir / "audio" / "bgm.wav"
    _write_wav(voice_wav, duration_sec=0.6, freq_hz=440.0, amp=0.5)
    _write_wav(bgm_wav, duration_sec=0.6, freq_hz=220.0, amp=0.25)

    multi_proj = multi_dir / "kinearc.project.json"
    multi_proj.write_text(
        json.dumps(
            {
                "fps": 30,
                "width": 320,
                "height": 180,
                "scenes": [
                    {"path": "scenes/01_canvas.html", "duration": 0.3},
                    {"path": "scenes/02_dom.html", "duration": 0.3},
                ],
                "audio": {
                    "voice": "audio/voice.wav",
                    "bgm": "audio/bgm.wav",
                    "fade_out": 0.1,
                },
            }
        ),
        encoding="utf-8",
    )

    multi_mp4 = multi_dir / "final_with_audio.mp4"
    proc_multi = subprocess.run(
        [node_bin, str(RENDER_MJS), "render", "--project", str(multi_proj), "--out", str(multi_mp4), "--scale", "1"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert proc_multi.returncode == 0, f"Multi-scene + audio render failed:\n{proc_multi.stderr}\n{proc_multi.stdout}"
    probe_multi = _ffprobe_json(ffprobe_bin, multi_mp4)
    v_multi = [s for s in probe_multi["streams"] if s["codec_type"] == "video"]
    a_multi = [s for s in probe_multi["streams"] if s["codec_type"] == "audio"]
    assert len(v_multi) == 1 and v_multi[0]["codec_name"] == "h264"
    assert v_multi[0]["width"] == 320 and v_multi[0]["height"] == 180
    assert v_multi[0]["pix_fmt"] == "yuv420p"
    multi_frames = int(v_multi[0].get("nb_read_frames") or v_multi[0].get("nb_frames") or 0)
    assert multi_frames == 18, f"Expected 18 concatenated frames (9+9), got {multi_frames}"
    assert float(probe_multi["format"]["duration"]) == pytest.approx(0.6, abs=0.05)
    assert len(a_multi) == 1 and a_multi[0]["codec_name"] == "aac"


def test_broken_ready_promise_fails_cleanly_nonzero(tmp_path: Path) -> None:
    node_bin, _, _ = _require_runtime_tools()
    assert RENDER_MJS.is_file(), f"Missing {RENDER_MJS}"

    broken_html = tmp_path / "broken_ready.html"
    broken_html.write_text(
        """<!doctype html>
<html><body>
<canvas id="c" width="320" height="180"></canvas>
<script>
window.kinearc = {
  totalDuration: 0.5,
  ready: Promise.reject(new Error('font failed')),
  seek() {}
};
</script>
</body></html>
""",
        encoding="utf-8",
    )

    out_mp4 = tmp_path / "should_not_exist.mp4"
    proc = subprocess.run(
        [
            node_bin,
            str(RENDER_MJS),
            "render",
            "--project",
            str(broken_html),
            "--out",
            str(out_mp4),
            "--scale",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert proc.returncode != 0
    combined = (proc.stderr or "") + "\n" + (proc.stdout or "")
    assert "font failed" in combined or "ready" in combined.lower()
    assert not out_mp4.exists()


def test_stalled_ready_timeout_webgl_capture_and_engine_hygiene(tmp_path: Path) -> None:
    node_bin, _, ffprobe_bin = _require_runtime_tools()

    # 1. Verify default 15s ready timeout + zero npm dependencies + zero forbidden terms in engine/
    pkg = json.loads((ENGINE_DIR / "package.json").read_text(encoding="utf-8"))
    assert pkg.get("type") == "module"
    assert pkg.get("license") == "MIT"
    assert not pkg.get("dependencies") and not pkg.get("devDependencies")

    render_src = RENDER_MJS.read_text(encoding="utf-8")
    assert "DEFAULT_READY_TIMEOUT_MS = 15000" in render_src

    forbidden_terms = ("mot" + "lab", "motion" + "2code", "stu" + "dio")
    for p in sorted(ENGINE_DIR.iterdir()):
        if p.is_file():
            txt = p.read_text(encoding="utf-8").lower()
            for term in forbidden_terms:
                assert term not in txt, f"Forbidden term {term!r} found in {p.name}"

    # 2. Stalled `ready` promise times out cleanly citing the exact failing scene URL
    stalled_html = tmp_path / "stalled_scene.html"
    stalled_html.write_text(
        """<!doctype html>
<html><body>
<canvas id="c" width="320" height="180"></canvas>
<script>
window.kinearc = {
  totalDuration: 0.5,
  ready: new Promise(() => {}),
  seek() {}
};
</script>
</body></html>
""",
        encoding="utf-8",
    )
    stalled_out = tmp_path / "stalled.mp4"
    proc_stall = subprocess.run(
        [
            node_bin,
            str(RENDER_MJS),
            "render",
            "--project",
            str(stalled_html),
            "--out",
            str(stalled_out),
            "--timeout",
            "1200",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc_stall.returncode != 0
    stall_err = (proc_stall.stderr or "") + "\n" + (proc_stall.stdout or "")
    assert "stalled_scene.html" in stall_err
    assert "Timed out" in stall_err
    assert not stalled_out.exists()

    # 3. WebGL canvas capture in the same evaluation turn after seek(t)
    webgl_dir = tmp_path / "webgl_test"
    webgl_dir.mkdir(parents=True, exist_ok=True)
    webgl_html = webgl_dir / "webgl.html"
    webgl_html.write_text(
        """<!doctype html>
<html><body style="margin:0;overflow:hidden;">
<canvas id="gl" width="320" height="180" style="width:100vw;height:100vh;display:block;"></canvas>
<script>
const canvas = document.getElementById('gl');
const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
function seek(t) {
  if (!gl) return;
  const r = Math.min(1, Math.max(0, t / 0.4));
  gl.clearColor(r, 0.2, 1.0 - r, 1.0);
  gl.clear(gl.COLOR_BUFFER_BIT);
}
window.kinearc = { totalDuration: 0.4, ready: Promise.resolve().then(() => seek(0)), seek };
</script>
</body></html>
""",
        encoding="utf-8",
    )
    webgl_proj = webgl_dir / "kinearc.project.json"
    webgl_proj.write_text(
        json.dumps({"fps": 30, "width": 320, "height": 180, "scenes": ["webgl.html"]}),
        encoding="utf-8",
    )
    webgl_mp4 = webgl_dir / "webgl.mp4"
    proc_gl = subprocess.run(
        [node_bin, str(RENDER_MJS), "render", "--project", str(webgl_proj), "--out", str(webgl_mp4)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert proc_gl.returncode == 0, f"WebGL render failed:\n{proc_gl.stderr}\n{proc_gl.stdout}"
    probe_gl = _ffprobe_json(ffprobe_bin, webgl_mp4)
    v_gl = [s for s in probe_gl["streams"] if s["codec_type"] == "video"]
    assert len(v_gl) == 1 and v_gl[0]["codec_name"] == "h264"
    assert v_gl[0]["width"] == 320 and v_gl[0]["height"] == 180

    # Verify first frame is blue-dominant and last frame transitions to red-dominant (non-cleared buffer)
    cap = cv2.VideoCapture(str(webgl_mp4))
    ok0, frame0 = cap.read()
    last_frame = frame0
    while True:
        ok, frm = cap.read()
        if not ok:
            break
        last_frame = frm
    cap.release()
    assert ok0 and frame0 is not None and last_frame is not None
    # OpenCV BGR: channel 0 = Blue, channel 2 = Red
    assert float(np.mean(frame0[:, :, 0])) > float(np.mean(frame0[:, :, 2])) + 50.0
    assert float(np.mean(last_frame[:, :, 2])) > float(np.mean(last_frame[:, :, 0])) + 50.0

    # 4. kinearc_cli.py doctor reports engine_ready == True
    proc_doc = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "kinearc_cli.py"), "doctor", "--json", "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_doc.returncode == 0, proc_doc.stderr
    doc_json = json.loads(proc_doc.stdout)
    assert doc_json["engine_ready"] is True
    assert doc_json["ok"] is True


def test_mid_render_seek_error_and_startup_exception_clean_up_temp_dirs(tmp_path: Path) -> None:
    node_bin, _, _ = _require_runtime_tools()

    isolated_tmp = tmp_path / "isolated_tmp"
    isolated_tmp.mkdir(parents=True, exist_ok=True)
    isolated_env = os.environ.copy()
    isolated_env["TEMP"] = str(isolated_tmp)
    isolated_env["TMP"] = str(isolated_tmp)
    isolated_env["TMPDIR"] = str(isolated_tmp)

    # 1. Mid-render seek(t) throw after FFmpeg pipe has started
    mid_err_dir = tmp_path / "mid_err"
    mid_err_dir.mkdir(parents=True, exist_ok=True)
    mid_html = mid_err_dir / "mid_throw.html"
    mid_html.write_text(
        """<!doctype html>
<html><body style="margin:0;overflow:hidden;">
<canvas id="c" width="320" height="180" style="width:100vw;height:100vh;display:block;"></canvas>
<script>
const ctx = document.getElementById('c').getContext('2d');
window.kinearc = {
  totalDuration: 0.5,
  ready: Promise.resolve(),
  seek(t) {
    if (t > 0.1) {
      throw new Error('mid-render seek explosion');
    }
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(0, 0, 320, 180);
  }
};
window.kinearc.seek(0);
</script>
</body></html>
""",
        encoding="utf-8",
    )
    mid_proj = mid_err_dir / "kinearc.project.json"
    mid_proj.write_text(
        json.dumps({"fps": 30, "width": 320, "height": 180, "scenes": ["mid_throw.html"]}),
        encoding="utf-8",
    )
    mid_out = mid_err_dir / "should_fail.mp4"
    proc_mid = subprocess.run(
        [node_bin, str(RENDER_MJS), "render", "--project", str(mid_proj), "--out", str(mid_out)],
        env=isolated_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc_mid.returncode != 0
    mid_combined = (proc_mid.stderr or "") + "\n" + (proc_mid.stdout or "")
    assert "mid-render seek explosion" in mid_combined
    assert "UnhandledPromiseRejection" not in mid_combined
    assert not mid_out.exists()
    leaked_mid = [p for p in isolated_tmp.iterdir() if p.name.startswith("kinearc-")]
    assert leaked_mid == [], f"Leaked temp dirs after mid-render error: {leaked_mid}"

    # 2. Startup JS exception when `ready` is omitted must still surface and fail non-zero
    startup_html = mid_err_dir / "startup_err.html"
    startup_html.write_text(
        """<!doctype html>
<html><body>
<canvas id="c" width="320" height="180"></canvas>
<script>
window.TOTAL = 0.2;
window.renderAt = function() {};
throw new Error('startup script boom');
</script>
</body></html>
""",
        encoding="utf-8",
    )
    startup_out = mid_err_dir / "startup_fail.mp4"
    proc_start = subprocess.run(
        [node_bin, str(RENDER_MJS), "render", "--project", str(startup_html), "--out", str(startup_out)],
        env=isolated_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc_start.returncode != 0
    start_combined = (proc_start.stderr or "") + "\n" + (proc_start.stdout or "")
    assert "startup script boom" in start_combined
    assert not startup_out.exists()
    leaked_start = [p for p in isolated_tmp.iterdir() if p.name.startswith("kinearc-")]
    assert leaked_start == [], f"Leaked temp dirs after startup error: {leaked_start}"
