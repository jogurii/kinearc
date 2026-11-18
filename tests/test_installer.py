import py_compile
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_PY = REPO_ROOT / "install.py"


def test_installer_copy_dry_run_link_and_uninstall(tmp_path: Path) -> None:
    compiled = tmp_path / "install.pyc"
    py_compile.compile(str(INSTALL_PY), cfile=str(compiled), doraise=True)
    assert compiled.is_file()

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    custom_root = tmp_path / "custom_skills"

    # 1. Dry-run does not touch disk
    proc_dry = subprocess.run(
        [
            sys.executable,
            "-B",
            str(INSTALL_PY),
            "--agent",
            "gemini,kiro",
            "--skill-dir",
            str(custom_root),
            "--home",
            str(fake_home),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_dry.returncode == 0, proc_dry.stderr
    assert "dry-run-copy" in proc_dry.stdout
    assert not (fake_home / ".gemini" / "config" / "skills" / "kinearc").exists()
    assert not (custom_root / "kinearc").exists()

    # 2. Real copy into isolated home + custom skill dir (skipping cache dirs)
    proc_copy = subprocess.run(
        [
            sys.executable,
            "-B",
            str(INSTALL_PY),
            "--agent",
            "claude,agents",
            "--skill-dir",
            str(custom_root),
            "--home",
            str(fake_home),
            "--skip-doctor",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_copy.returncode == 0, proc_copy.stderr
    for target in (
        fake_home / ".claude" / "skills" / "kinearc",
        fake_home / ".agents" / "skills" / "kinearc",
        custom_root / "kinearc",
    ):
        assert (target / "SKILL.md").is_file()
        assert (target / "engine" / "render.mjs").is_file()
        assert (target / "scripts" / "kinearc_cli.py").is_file()
        assert (target / "references" / "kinearc-engine.md").is_file()
        assert not any(p.name in {"__pycache__", ".pytest_cache"} for p in target.rglob("*"))

    # 3. Link mode (--link) + uninstall removes ONLY kinearc without deleting sibling skill
    sibling = custom_root / "other_skill"
    sibling.mkdir(parents=True, exist_ok=True)
    (sibling / "keep.txt").write_text("ok", encoding="utf-8")

    proc_link = subprocess.run(
        [
            sys.executable,
            "-B",
            str(INSTALL_PY),
            "--agent",
            "none",
            "--skill-dir",
            str(custom_root),
            "--link",
            "--skip-doctor",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_link.returncode == 0, proc_link.stderr
    assert (custom_root / "kinearc" / "SKILL.md").is_file()

    proc_un = subprocess.run(
        [
            sys.executable,
            "-B",
            str(INSTALL_PY),
            "--agent",
            "none",
            "--skill-dir",
            str(custom_root),
            "--uninstall",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_un.returncode == 0, proc_un.stderr
    assert not (custom_root / "kinearc").exists()
    assert (sibling / "keep.txt").read_text(encoding="utf-8") == "ok"


def test_installer_rejects_unknown_agent() -> None:
    proc = subprocess.run(
        [sys.executable, "-B", str(INSTALL_PY), "--agent", "nonexistent_agent", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "Unsupported agent target" in proc.stderr


def test_audio_mix_resolves_relative_sfx_paths_from_cues_dir(tmp_path: Path) -> None:
    import json

    audio_dir = tmp_path / "proj" / "audio"
    sfx_dir = audio_dir / "sfx"
    sfx_dir.mkdir(parents=True, exist_ok=True)
    pop_wav = sfx_dir / "pop.wav"

    # Generate 0.1s mono 22.05kHz PCM WAV cleanly
    import struct
    import wave

    with wave.open(str(pop_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(struct.pack("<" + "h" * 2205, *([4000] * 2205)))

    cues_json = audio_dir / "cues.json"
    cues_json.write_text(json.dumps([{"file": "sfx/pop.wav", "time": 0.05, "volume": 0.8}]), encoding="utf-8")
    out_wav = tmp_path / "mixed.wav"

    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(REPO_ROOT / "scripts" / "audio_mix.py"),
            "mix",
            "--sfx",
            str(cues_json),
            "--out",
            str(out_wav),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert out_wav.is_file() and out_wav.stat().st_size > 1000
    assert "Warning: SFX file not found" not in proc.stderr
