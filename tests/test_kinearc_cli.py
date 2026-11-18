import json
import ntpath
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def test_validate_manifest_scales_even_and_preserves_audio(tmp_path: Path) -> None:
    import kinearc_cli

    scene_dir = tmp_path / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    scene_html = scene_dir / "intro.html"
    scene_html.write_text("<!doctype html><html><body>kinearc</body></html>", encoding="utf-8")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    vo_wav = audio_dir / "voice.wav"
    vo_wav.write_bytes(b"RIFFdemo")

    proj_json = tmp_path / "kinearc.project.json"
    proj_json.write_text(
        json.dumps(
            {
                "fps": 60,
                "width": 1080,
                "height": 1920,
                "scenes": [{"path": "scenes/intro.html", "duration": 4.5}],
                "audio": {"voice": "audio/voice.wav"},
            }
        ),
        encoding="utf-8",
    )

    scaled = kinearc_cli.validate_manifest(str(proj_json), scale=2)
    assert kinearc_cli.validate_manifest(proj_json, scale=2) == scaled
    assert scaled["kind"] == "project"
    assert scaled["base_width"] == 1080
    assert scaled["base_height"] == 1920
    assert scaled["width"] == 2160
    assert scaled["height"] == 3840
    assert scaled["fps"] == 60.0
    assert scaled["scale"] == 2.0
    assert scaled["scenes"] == [{"path": str(scene_html.resolve()), "duration": 4.5}]
    assert scaled["audio"] == {
        "voice": str(vo_wav.resolve()),
        "bgm": None,
        "sfx": None,
        "voice_vol": 1.0,
        "bgm_vol": 0.35,
        "video_vol": 1.0,
        "fade_out": 1.5,
        "keep_video_audio": False,
    }

    # Odd dimensions clamp cleanly down to even pixel dimensions
    odd_proj = tmp_path / "odd.project.json"
    odd_proj.write_text(
        json.dumps(
            {
                "fps": 30,
                "width": 1081,
                "height": 1921,
                "scenes": ["scenes/intro.html"],
            }
        ),
        encoding="utf-8",
    )
    odd_res = kinearc_cli.validate_manifest(str(odd_proj), scale=1)
    assert odd_res["width"] == 1080
    assert odd_res["height"] == 1920
    assert odd_res["width"] % 2 == 0 and odd_res["height"] % 2 == 0
    assert odd_res["audio"] is None

    # Standalone HTML scene defaults to 1920x1080 @ 60fps and scales cleanly
    scene_res = kinearc_cli.validate_manifest(str(scene_html), scale=2, fps_override=30)
    assert scene_res["kind"] == "scene"
    assert scene_res["width"] == 3840
    assert scene_res["height"] == 2160
    assert scene_res["fps"] == 30.0
    assert scene_res["audio"] is None

    # even_dimension edge validation
    assert kinearc_cli.even_dimension(1) == 2
    for bad in (True, False, 0, -2, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            kinearc_cli.even_dimension(bad)


def test_validate_manifest_omitted_audio_and_missing_scene_or_audio_errors(tmp_path: Path) -> None:
    import kinearc_cli

    scene_html = tmp_path / "scene.html"
    scene_html.write_text("<html></html>", encoding="utf-8")

    # Omitted audio & empty audio dict normalize to None
    no_audio_proj = tmp_path / "no_audio.project.json"
    no_audio_proj.write_text(json.dumps({"scenes": ["scene.html"]}), encoding="utf-8")
    assert kinearc_cli.validate_manifest(str(no_audio_proj))["audio"] is None

    empty_audio_proj = tmp_path / "empty_audio.project.json"
    empty_audio_proj.write_text(json.dumps({"scenes": ["scene.html"], "audio": {}}), encoding="utf-8")
    assert kinearc_cli.validate_manifest(str(empty_audio_proj))["audio"] is None

    # Missing scene raises FileNotFoundError
    missing_scene_proj = tmp_path / "missing_scene.project.json"
    missing_scene_proj.write_text(json.dumps({"scenes": ["does_not_exist.html"]}), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        kinearc_cli.validate_manifest(str(missing_scene_proj))

    # Missing audio path inside "audio" raises FileNotFoundError
    missing_audio_proj = tmp_path / "missing_audio.project.json"
    missing_audio_proj.write_text(
        json.dumps({"scenes": ["scene.html"], "audio": {"bgm": "missing_bgm.mp3"}}),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        kinearc_cli.validate_manifest(str(missing_audio_proj))

    # Invalid scale or empty scenes raises ValueError
    with pytest.raises(ValueError):
        kinearc_cli.validate_manifest(str(no_audio_proj), scale=0)
    with pytest.raises(ValueError):
        kinearc_cli.validate_manifest(str(no_audio_proj), scale=True)  # type: ignore[arg-type]

    bad_scenes_proj = tmp_path / "empty_scenes.project.json"
    bad_scenes_proj.write_text(json.dumps({"scenes": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        kinearc_cli.validate_manifest(str(bad_scenes_proj))


def test_find_browser_executable_respects_chrome_path_and_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    import kinearc_cli

    custom_chrome = "/opt/custom/chrome-headless"
    found = kinearc_cli.find_browser_executable(
        env={"CHROME_PATH": custom_chrome},
        path_exists=lambda p: p == custom_chrome,
        which=lambda _name: None,
    )
    assert found == custom_chrome

    # Explicit nonexistent CHROME_PATH must return None instead of silently falling back
    assert (
        kinearc_cli.find_browser_executable(
            env={"CHROME_PATH": "/nonexistent/custom-chrome"},
            path_exists=lambda p: p == "/usr/bin/google-chrome",
            which=lambda _name: "/usr/bin/chromium",
        )
        is None
    )

    # Windows lookup (Program Files & LocalAppData fallback)
    monkeypatch.setattr(sys, "platform", "win32")
    win_edge = ntpath.join(r"C:\Program Files (x86)", "Microsoft", "Edge", "Application", "msedge.exe")
    assert (
        kinearc_cli.find_browser_executable(
            env={
                "PROGRAMFILES": r"C:\Program Files",
                "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
                "LOCALAPPDATA": r"C:\Users\demo\AppData\Local",
            },
            path_exists=lambda p: p == win_edge,
            which=lambda _name: None,
        )
        == win_edge
    )

    # macOS lookup
    monkeypatch.setattr(sys, "platform", "darwin")
    mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert (
        kinearc_cli.find_browser_executable(
            env={},
            path_exists=lambda p: p == mac_chrome,
            which=lambda _name: None,
        )
        == mac_chrome
    )

    # Linux lookup via PATH (`which`)
    monkeypatch.setattr(sys, "platform", "linux")
    assert (
        kinearc_cli.find_browser_executable(
            env={},
            path_exists=lambda _p: False,
            which=lambda name: "/usr/bin/chromium" if name == "chromium" else None,
        )
        == "/usr/bin/chromium"
    )

    # None when nothing matches
    assert (
        kinearc_cli.find_browser_executable(
            env={},
            path_exists=lambda _p: False,
            which=lambda _name: None,
        )
        is None
    )


def test_doctor_subcommand_json_and_passthrough_help(monkeypatch: pytest.MonkeyPatch) -> None:
    import kinearc_cli

    proc_doc = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "kinearc_cli.py"), "doctor", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_doc.returncode == 0, proc_doc.stderr
    payload = json.loads(proc_doc.stdout)
    for key in ("python", "ffmpeg", "ffprobe", "node", "browser", "engine_ready", "ok"):
        assert key in payload, f"doctor JSON missing key {key!r}"
    assert isinstance(payload["ok"], bool)
    assert isinstance(payload["engine_ready"], bool)
    assert "cv2" in payload["python"] and "numpy" in payload["python"]

    # run_doctor must factor engine_ready into ok
    monkeypatch.setattr(kinearc_cli, "_probe_node", lambda: {"path": "node", "version": "v24.0.0", "major": 24, "min_major": 24, "ok": True})
    monkeypatch.setattr(kinearc_cli, "find_browser_executable", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(kinearc_cli.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None)
    monkeypatch.setattr(kinearc_cli, "ENGINE_RENDER", str(REPO_ROOT / "engine" / "__missing_render__.mjs"))
    missing_eng_doc = kinearc_cli.run_doctor()
    assert missing_eng_doc["engine_ready"] is False
    if missing_eng_doc["python"]["ok"]:
        assert missing_eng_doc["ok"] is False

    # --strict exits 1 when core dependency is missing
    monkeypatch.setattr(
        kinearc_cli,
        "run_doctor",
        lambda: {
            "python": {"version": "3.14", "cv2": "5.0", "numpy": "2.0", "ok": True},
            "ffmpeg": {"path": None, "ok": False},
            "ffprobe": {"path": None, "ok": False},
            "node": {"path": None, "version": None, "major": None, "min_major": 24, "ok": False},
            "browser": {"path": None, "ok": False},
            "engine_ready": False,
            "ok": False,
        },
    )
    assert kinearc_cli.main(["doctor", "--json"]) == 0
    assert kinearc_cli.main(["doctor", "--json", "--strict"]) == 1

    # audio --help passthrough reaches audio_mix.py CLI parser
    proc_audio = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "kinearc_cli.py"), "audio", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_audio.returncode == 0, proc_audio.stderr
    assert "cut-pauses" in proc_audio.stdout and "mix" in proc_audio.stdout


def test_render_validates_manifest_before_launching_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import kinearc_cli

    with pytest.raises(FileNotFoundError):
        kinearc_cli.main(["render", "--project", str(tmp_path / "missing.json"), "--out", str(tmp_path / "out.mp4")])

    scene_html = tmp_path / "scene.html"
    scene_html.write_text("<!doctype html><html><body>demo</body></html>", encoding="utf-8")

    # Missing engine/render.mjs fails clearly AFTER manifest validation passes
    monkeypatch.setattr(kinearc_cli, "ENGINE_RENDER", str(tmp_path / "nonexistent_engine" / "render.mjs"))
    with pytest.raises(FileNotFoundError, match=r"render\.mjs"):
        kinearc_cli.main(["render", "--project", str(scene_html), "--out", str(tmp_path / "out.mp4")])

    with pytest.raises(FileNotFoundError, match=r"render\.mjs"):
        kinearc_cli.main(
            [
                "stills",
                "--scene",
                str(scene_html),
                "--out_dir",
                str(tmp_path / "stills"),
                "--times",
                "0,1.5",
            ]
        )


def test_render_stills_invocation_passthrough_and_reference_doc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import kinearc_cli

    # Verify audio aliases (voice_path/bgm_path/sfx_path) and keep_video_audio=True
    scene_html = tmp_path / "scene.html"
    scene_html.write_text("<html></html>", encoding="utf-8")
    vo_wav = tmp_path / "vo.wav"
    bgm_mp3 = tmp_path / "bgm.mp3"
    cues_json = tmp_path / "cues.json"
    vo_wav.write_bytes(b"vo")
    bgm_mp3.write_bytes(b"bgm")
    cues_json.write_text("[]", encoding="utf-8")

    alias_proj = tmp_path / "alias.project.json"
    alias_proj.write_text(
        json.dumps(
            {
                "scenes": [{"file": "scene.html", "total": 3.0}],
                "audio": {
                    "voice": "",
                    "voice_path": "vo.wav",
                    "bgm": "   ",
                    "bgm_path": "bgm.mp3",
                    "sfx_path": "cues.json",
                    "voice_vol": 1.2,
                    "bgm_vol": 0.25,
                    "video_vol": 0.8,
                    "fade_out": 2.0,
                    "keep_video_audio": True,
                },
            }
        ),
        encoding="utf-8",
    )
    parsed = kinearc_cli.validate_manifest(str(alias_proj))
    assert parsed["scenes"] == [{"path": str(scene_html.resolve()), "duration": 3.0}]
    assert parsed["audio"] == {
        "voice": str(vo_wav.resolve()),
        "bgm": str(bgm_mp3.resolve()),
        "sfx": str(cues_json.resolve()),
        "voice_vol": 1.2,
        "bgm_vol": 0.25,
        "video_vol": 0.8,
        "fade_out": 2.0,
        "keep_video_audio": True,
    }

    keep_only_proj = tmp_path / "keep_only.project.json"
    keep_only_proj.write_text(
        json.dumps({"scenes": ["scene.html"], "audio": {"keep_video_audio": True}}),
        encoding="utf-8",
    )
    keep_parsed = kinearc_cli.validate_manifest(str(keep_only_proj))
    assert keep_parsed["audio"] is not None and keep_parsed["audio"]["keep_video_audio"] is True

    # Verify CLI --help and doctor human summary + reference doc (before subprocess monkeypatching)
    proc_help = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "kinearc_cli.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_help.returncode == 0
    for sub in ("doctor", "render", "stills", "extract", "track", "measure", "verify", "ui", "audio"):
        assert sub in proc_help.stdout

    proc_human_doc = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "kinearc_cli.py"), "doctor"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_human_doc.returncode == 0
    assert "kinearc Environment Doctor" in proc_human_doc.stdout

    ref_doc = REPO_ROOT / "references" / "kinearc-engine.md"
    assert ref_doc.is_file()
    ref_text = ref_doc.read_text(encoding="utf-8")
    for token in (
        "kinearc_cli.py",
        "doctor",
        "kinearc.project.json",
        "window.kinearc",
        "totalDuration",
        "seek",
        "renderAt",
        "preserveDrawingBuffer: true",
        "--scale 2",
    ):
        assert token in ref_text, f"references/kinearc-engine.md missing {token!r}"

    # Mock engine/render.mjs and node execution for render (--json-progress) and stills
    fake_engine = tmp_path / "engine" / "render.mjs"
    fake_engine.parent.mkdir(parents=True, exist_ok=True)
    fake_engine.write_text("// stub\n", encoding="utf-8")
    monkeypatch.setattr(kinearc_cli, "ENGINE_RENDER", str(fake_engine))
    monkeypatch.setattr(kinearc_cli.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)

    recorded_popen: list[list[str]] = []

    class _FakeStdout:
        def __init__(self, lines: list[str]):
            self._lines = iter(lines)
            self.closed = False

        def __iter__(self):
            return self._lines

        def close(self) -> None:
            self.closed = True

    class _FakeProc:
        def __init__(self, cmd: list[str]):
            recorded_popen.append(cmd)
            self.stdout = _FakeStdout(['{"event":"progress","frame":1}\n', '{"event":"done"}\n'])
            self.returncode = 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

    monkeypatch.setattr(kinearc_cli.subprocess, "Popen", lambda cmd, **_kw: _FakeProc(cmd))
    out_mp4 = tmp_path / "out_4k.mp4"
    rc = kinearc_cli.main(
        ["render", "--project", str(alias_proj), "--out", str(out_mp4), "--scale", "2", "--crf", "16", "--json-progress"]
    )
    assert rc == 0
    assert len(recorded_popen) == 1
    assert recorded_popen[0][:4] == ["/usr/bin/node", str(fake_engine), "render", "--project"]
    assert "--json-progress" in recorded_popen[0]
    out_text = capsys.readouterr().out
    assert '{"event":"progress","frame":1}' in out_text
    assert '{"event":"done"}' in out_text

    recorded_run: list[list[str]] = []

    class _FakeCompleted:
        returncode = 0

    monkeypatch.setattr(
        kinearc_cli.subprocess,
        "run",
        lambda cmd, **_kw: recorded_run.append(cmd) or _FakeCompleted(),
    )
    stills_rc = kinearc_cli.main(
        ["stills", "--scene", str(scene_html), "--out_dir", str(tmp_path / "stills_out"), "--times", "0, 1.5", "--scale", "2"]
    )
    assert stills_rc == 0
    assert recorded_run[0][:3] == ["/usr/bin/node", str(fake_engine), "stills"]
    assert "--times" in recorded_run[0] and "0,1.5" in recorded_run[0]

    with pytest.raises(ValueError):
        kinearc_cli.main(["stills", "--scene", str(scene_html), "--times", "0,bad"])

    # Passthrough delegation: argv-accepting module (`ui`) and 0-arg `main()` module (`track`)
    import kinearc_ui
    import track_objects

    ui_calls: list[list[str] | None] = []
    monkeypatch.setattr(kinearc_ui, "main", lambda argv=None: ui_calls.append(argv))
    assert kinearc_cli.main(["ui", "--no-open", "--scene", str(scene_html)]) == 0
    assert ui_calls == [["--no-open", "--scene", str(scene_html)]]

    monkeypatch.setattr(kinearc_ui, "main", lambda _argv=None: True)
    assert kinearc_cli.main(["ui"]) == 0
    monkeypatch.setattr(kinearc_ui, "main", lambda _argv=None: 2)
    assert kinearc_cli.main(["ui"]) == 2

    track_sys_argvs: list[list[str]] = []
    before_argv = list(sys.argv)
    monkeypatch.setattr(track_objects, "main", lambda: track_sys_argvs.append(list(sys.argv)))
    assert kinearc_cli.main(["track", "demo.mp4", "--out_dir", "out"]) == 0
    assert len(track_sys_argvs) == 1
    assert track_sys_argvs[0][1:] == ["demo.mp4", "--out_dir", "out"]
    assert sys.argv == before_argv


def test_streaming_node_utf8_on_cp1252_and_child_reap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import kinearc_cli

    node_bin = shutil.which("node")
    assert node_bin, "Node.js is required for streaming UTF-8 regression test"

    # 1. Subprocess with PYTHONUTF8=0 and PYTHONIOENCODING unset relaying non-ASCII UTF-8 paths
    scene_html = tmp_path / "scene.html"
    scene_html.write_text("<!doctype html><html><body>demo</body></html>", encoding="utf-8")

    fake_engine = tmp_path / "fake_render.mjs"
    fake_engine.write_text(
        "const idx = process.argv.indexOf('--out');\n"
        "const outArg = idx >= 0 ? process.argv[idx + 1] : '';\n"
        "console.log(JSON.stringify({ type: 'progress', frame: 1, total: 1, progress: 100 }));\n"
        "console.log(JSON.stringify({ type: 'done', out: 'C:/tmp/Caf\\u00e9\\u2014render/out_4k.mp4', arg: outArg }));\n",
        encoding="utf-8",
    )

    out_path = tmp_path / "Café—render" / "out_4k.mp4"
    driver = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import kinearc_cli\n"
        f"kinearc_cli.ENGINE_RENDER = {str(fake_engine)!r}\n"
        f"sys.exit(kinearc_cli.main(['render', '--project', {str(scene_html)!r}, '--out', {str(out_path)!r}, '--json-progress']))\n"
    )
    sub_env = os.environ.copy()
    sub_env["PYTHONUTF8"] = "0"
    sub_env.pop("PYTHONIOENCODING", None)

    proc = subprocess.run(
        [sys.executable, "-B", "-c", driver],
        env=sub_env,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    stdout_utf8 = proc.stdout.decode("utf-8", errors="strict")
    assert "C:/tmp/Café—render/out_4k.mp4" in stdout_utf8
    assert "Café—render" in stdout_utf8

    # 2. Abnormal exception while reading stdout kills & reaps the live child cleanly
    captured_procs: list[subprocess.Popen[str]] = []
    real_popen = subprocess.Popen

    def _recording_popen(*args, **kwargs):
        p = real_popen(*args, **kwargs)
        captured_procs.append(p)
        return p

    monkeypatch.setattr(kinearc_cli.subprocess, "Popen", _recording_popen)

    def _failing_write(text: str) -> int:
        raise RuntimeError(f"abort on {text.strip()}")

    monkeypatch.setattr(sys.stdout, "write", _failing_write)

    with pytest.raises(RuntimeError, match="abort on first_line"):
        kinearc_cli._run_streaming_node(
            [node_bin, "-e", "console.log('first_line'); setInterval(() => {}, 5000);"],
            os.environ.copy(),
            stream_stdout=True,
        )

    assert len(captured_procs) == 1
    child = captured_procs[0]
    assert child.poll() is not None, "Child process should have been killed and reaped on exception"
    assert child.stdout is not None and child.stdout.closed

    # 3. TimeoutExpired fallback kills & waits and falls back to 1 if returncode is None
    monkeypatch.undo()

    class _TimeoutFakeStdout:
        def __init__(self) -> None:
            self.closed = False

        def __iter__(self):
            return iter(["ok\n"])

        def close(self) -> None:
            self.closed = True

    class _TimeoutFakeProc:
        def __init__(self, final_rc: int | None) -> None:
            self.stdout = _TimeoutFakeStdout()
            self.returncode = None
            self.killed = False
            self._final_rc = final_rc
            self._waits = 0

        def poll(self):
            return self.returncode

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None):
            self._waits += 1
            if timeout is not None and self._waits == 1:
                raise subprocess.TimeoutExpired("node", timeout)
            self.returncode = self._final_rc
            return self.returncode

    fake_7 = _TimeoutFakeProc(7)
    monkeypatch.setattr(kinearc_cli.subprocess, "Popen", lambda *_a, **_kw: fake_7)
    assert kinearc_cli._run_streaming_node(["node"], {}, stream_stdout=True) == 7
    assert fake_7.killed is True and fake_7.stdout.closed is True

    fake_none = _TimeoutFakeProc(None)
    monkeypatch.setattr(kinearc_cli.subprocess, "Popen", lambda *_a, **_kw: fake_none)
    assert kinearc_cli._run_streaming_node(["node"], {}, stream_stdout=True) == 1
    assert fake_none.killed is True and fake_none.stdout.closed is True

