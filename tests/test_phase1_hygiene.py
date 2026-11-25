import ast
import py_compile
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
ENGINE_DIR = REPO_ROOT / "engine"
UI_DIR = SCRIPTS_DIR / "ui"
REFERENCES_DIR = REPO_ROOT / "references"

FORBIDDEN_LEGACY_ENGINE = "mot" + "lab"
FORBIDDEN_OLD_BRAND = "motion" + "2code"
FORBIDDEN_TONE_WORD = "stu" + "dio"

REPO_TEXT_EXTENSIONS = {".md", ".py", ".html", ".css", ".js", ".mjs", ".json"}

EXPECTED_SCRIPTS = {
    "audio_mix.py",
    "auto_cue.py",
    "build_sfx_pack.py",
    "extract_audio_style.py",
    "extract_full_motion.py",
    "kinearc_cli.py",
    "kinearc_ui.py",
    "measure_shapes_colors.py",
    "review_viewer.py",
    "track_objects.py",
    "verify_motion_diff.py",
}

EXPECTED_UI_ASSETS = (
    "index.html",
    "styles.css",
    "stage.js",
    "timeline.js",
    "annotations.js",
    "drawer.js",
    "app.js",
)

ANALYSIS_SCRIPTS_WITH_OUT_DIR = [
    "extract_full_motion.py",
    "track_objects.py",
    "measure_shapes_colors.py",
    "verify_motion_diff.py",
    "kinearc_ui.py",
    "review_viewer.py",
]


def _iter_repo_text_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {"__pycache__", ".pytest_cache", ".git"} for part in path.parts):
            continue
        if path.suffix.lower() in REPO_TEXT_EXTENSIONS:
            files.append(path)
    return files


def _write_solid_mp4(path: Path, count: int = 6, bgr: tuple[int, int, int] = (30, 60, 120)) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 30.0, (160, 120))
    assert writer.isOpened(), f"Could not create test video {path}"
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[:, :] = bgr
    try:
        for _ in range(count):
            writer.write(frame)
    finally:
        writer.release()


def test_zero_forbidden_terms_across_repo_files() -> None:
    patterns = [
        ("legacy_engine", re.compile(re.escape(FORBIDDEN_LEGACY_ENGINE), re.IGNORECASE)),
        ("old_brand", re.compile(re.escape(FORBIDDEN_OLD_BRAND), re.IGNORECASE)),
        ("forbidden_word", re.compile(re.escape(FORBIDDEN_TONE_WORD), re.IGNORECASE)),
    ]
    hits: list[str] = []
    scanned = _iter_repo_text_files()
    assert {p.suffix.lower() for p in scanned} == REPO_TEXT_EXTENSIONS

    for path in scanned:
        rel = path.relative_to(REPO_ROOT).as_posix()
        for label, pat in patterns:
            if pat.search(rel):
                hits.append(f"filename {rel} [{label}]")

        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for label, pat in patterns:
                if pat.search(line):
                    hits.append(f"{rel}:{line_no} [{label}] -> {line.strip()}")

    assert hits == [], "Forbidden terms found:\n" + "\n".join(hits)


def test_zero_legacy_analysis_dir_in_docs_and_scripts() -> None:
    legacy_dir_pat = re.compile(r"\.motion_analysis")
    hits: list[str] = []

    for path in _iter_repo_text_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("tests/"):
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if legacy_dir_pat.search(line):
                hits.append(f"{rel}:{line_no} -> {line.strip()}")

    assert hits == [], "Legacy analysis directory reference found:\n" + "\n".join(hits)


def test_py_compile_all_scripts(tmp_path: Path) -> None:
    script_paths = sorted(SCRIPTS_DIR.glob("*.py"))
    assert {p.name for p in script_paths} == EXPECTED_SCRIPTS

    for script_path in script_paths:
        compiled = tmp_path / f"{script_path.stem}.pyc"
        py_compile.compile(str(script_path), cfile=str(compiled), doraise=True)
        assert compiled.is_file()


def test_references_web_interactive_exists_and_legacy_doc_removed() -> None:
    legacy_ref = REFERENCES_DIR / f"{FORBIDDEN_LEGACY_ENGINE}.md"
    assert not legacy_ref.exists(), f"Deprecated reference still exists: {legacy_ref}"

    web_doc = REFERENCES_DIR / "web-interactive.md"
    assert web_doc.is_file(), "references/web-interactive.md is missing"
    content = web_doc.read_text(encoding="utf-8")
    for required in (
        "ScrollTrigger",
        "Element.animate",
        "ScrollTimeline",
        "motionTracks.ts",
        "prefers-reduced-motion",
        "window.kinearc.seek",
    ):
        assert required in content, f"references/web-interactive.md missing section/token: {required}"


def test_scripts_default_out_dir_is_kinearc_analysis_and_viewer_prompt_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for script_name in ANALYSIS_SCRIPTS_WITH_OUT_DIR:
        script_path = SCRIPTS_DIR / script_name
        tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))
        found_out_dir_default = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value != "--out_dir":
                continue
            for kw in node.keywords:
                if kw.arg == "default" and isinstance(kw.value, ast.Constant):
                    assert kw.value.value == ".kinearc_analysis", (
                        f"{script_name} --out_dir default is {kw.value.value!r}, expected '.kinearc_analysis'"
                    )
                    found_out_dir_default = True
        assert found_out_dir_default, f"{script_name} missing --out_dir argument with '.kinearc_analysis' default"

    monkeypatch.syspath_prepend(str(SCRIPTS_DIR))
    import kinearc_ui as kui
    import review_viewer as rv

    assert issubclass(rv.ViewerState, kui.UiState)
    assert rv.make_handler is kui.make_handler
    assert rv.ReusableThreadingTCPServer is kui.ReusableThreadingTCPServer
    assert "kinearc" in kui.PLACEHOLDER_HTML

    delegated_argv: list[list[str] | None] = []
    monkeypatch.setattr(kui, "main", lambda argv=None: delegated_argv.append(argv))
    rv.main(["--no-open", "--scene", "demo.html"])
    assert delegated_argv == [["--no-open", "--scene", "demo.html"]]

    # Verify measure_shapes_colors.py & track_objects.py default .kinearc_analysis output and explicit --out_dir
    video_path = tmp_path / "sample.mp4"
    _write_solid_mp4(video_path)

    proc_track = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "track_objects.py"), str(video_path)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_track.returncode == 0, proc_track.stderr
    assert (tmp_path / ".kinearc_analysis" / "motion_tracks.json").is_file()
    assert (tmp_path / ".kinearc_analysis" / "motionTracks.ts").is_file()

    proc_measure_default = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "measure_shapes_colors.py"), str(video_path), "0"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_measure_default.returncode == 0, proc_measure_default.stderr
    assert (tmp_path / ".kinearc_analysis" / "geometry_report.json").is_file()

    custom_dir = tmp_path / "custom_out"
    proc_measure_custom = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPTS_DIR / "measure_shapes_colors.py"),
            str(video_path),
            "0",
            "--out_dir",
            str(custom_dir),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_measure_custom.returncode == 0, proc_measure_custom.stderr
    assert (custom_dir / "geometry_report.json").is_file()

    explicit_out = tmp_path / "explicit_dir" / "custom_geometry.json"
    proc_measure_explicit = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPTS_DIR / "measure_shapes_colors.py"),
            str(video_path),
            "0",
            "--out",
            str(explicit_out),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_measure_explicit.returncode == 0, proc_measure_explicit.stderr
    assert explicit_out.is_file()

    state_default = rv.ViewerState(str(video_path), None, str(tmp_path / ".kinearc_analysis"))
    assert Path(state_default.sel_json).name == "selection.json"
    assert Path(state_default.sel_dir).is_dir()

    state_legacy = rv.ViewerState(str(video_path), None, str(tmp_path / ".motion_analysis"))
    assert Path(state_legacy.sel_dir).is_dir()

    proc_audio_help = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "audio_mix.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_audio_help.returncode == 0
    assert "kinearc" in proc_audio_help.stdout.lower()


def test_ui_core_assets_title_selection_json_and_docs() -> None:
    for asset_name in EXPECTED_UI_ASSETS:
        asset_path = UI_DIR / asset_name
        assert asset_path.is_file(), f"Missing core UI asset: {asset_path}"
        assert asset_path.stat().st_size > 0, f"Empty core UI asset: {asset_path}"

    index_html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "<title>kinearc</title>" in index_html

    annotations_js = (UI_DIR / "annotations.js").read_text(encoding="utf-8")
    assert ".kinearc_analysis" in annotations_js
    assert "${cleanDir}/selection.json" in annotations_js

    for doc_rel in (
        "README.md",
        "SKILL.md",
        "references/video-cloning.md",
        "references/audio-and-footage.md",
        "references/web-interactive.md",
    ):
        doc_text = (REPO_ROOT / doc_rel).read_text(encoding="utf-8")
        assert "kinearc_ui.py" in doc_text, f"{doc_rel} should document kinearc_ui.py"


def test_engine_files_and_v3_docs_truthfulness() -> None:
    for rel_path in (
        "engine/package.json",
        "engine/browser_find.mjs",
        "engine/render.mjs",
        "references/kinearc-engine.md",
    ):
        p = REPO_ROOT / rel_path
        assert p.is_file(), f"Missing required v3.0 asset: {p}"
        assert p.stat().st_size > 0, f"Empty required v3.0 asset: {p}"

    skill_md = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
    readme_md = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "v3.0" in skill_md
    assert "v3.0" in readme_md
    assert "kinearc_cli.py" in skill_md and "kinearc_cli.py" in readme_md
    assert "engine/render.mjs" in skill_md and "engine/render.mjs" in readme_md
    assert "references/kinearc-engine.md" in skill_md and "references/kinearc-engine.md" in readme_md
    assert "/api/render" in skill_md and "/api/render" in readme_md

    stale_patterns = [
        re.compile(r"arrives in Phase 3", re.IGNORECASE),
        re.compile(r"\bupcoming\b", re.IGNORECASE),
        re.compile(r"\bon\s+the\s+roadmap\b|\broadmap\s+(?:item|feature|placeholder)\b", re.IGNORECASE),
    ]
    for doc_rel in (
        "SKILL.md",
        "README.md",
        "references/3d.md",
        "references/ad-craft.md",
        "references/kinearc-engine.md",
        "references/video-cloning.md",
        "references/web-interactive.md",
        "scripts/ui/drawer.js",
    ):
        txt = (REPO_ROOT / doc_rel).read_text(encoding="utf-8")
        for pat in stale_patterns:
            assert not pat.search(txt), f"Stale placeholder phrase {pat.pattern!r} found in {doc_rel}"
