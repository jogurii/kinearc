import json
import subprocess
import sys
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def test_sfx_pack_catalog_and_audio_mix_bundled_fallback(tmp_path: Path) -> None:
    catalog_path = REPO_ROOT / "assets" / "sfx" / "catalog.json"
    assert catalog_path.is_file(), "Missing assets/sfx/catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog.get("version") == "3.0"
    events = catalog.get("events", {})
    for required_kind in (
        "key",
        "tap",
        "latch",
        "tick",
        "swish",
        "whoosh",
        "sub_impact",
        "ping",
        "riser",
        "chord",
        "swell",
        "glint",
        "bloom",
        "portal",
    ):
        assert required_kind in events, f"Missing event kind {required_kind!r} in catalog.json"
        for rel_file in events[required_kind]["files"]:
            wav_path = REPO_ROOT / "assets" / rel_file
            assert wav_path.is_file() and wav_path.stat().st_size > 500, f"Missing WAV {wav_path}"
            with wave.open(str(wav_path), "rb") as wf:
                assert wf.getframerate() == 44100
                assert wf.getsampwidth() == 2
                assert wf.getnframes() > 200

    for bgm_name in ("bgm_groove.wav", "bgm_ambient.wav"):
        bgm_path = REPO_ROOT / "assets" / "sfx" / bgm_name
        assert bgm_path.is_file() and bgm_path.stat().st_size > 50000, f"Missing BGM {bgm_name}"

    # Verify audio_mix.py resolves bundled "sfx/key_clack_01.wav" from an isolated temp project
    cues_json = tmp_path / "cues.json"
    cues_json.write_text(
        json.dumps([{"file": "sfx/key_clack_01.wav", "time": 0.05, "volume": 0.75}]),
        encoding="utf-8",
    )
    out_wav = tmp_path / "out_mix.wav"
    proc = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "audio_mix.py"), "mix", "--sfx", str(cues_json), "--out", str(out_wav)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert out_wav.is_file() and out_wav.stat().st_size > 1000
    assert "Warning: SFX file not found" not in proc.stderr


def test_autocue_single_scene_and_multiscene_project_manifest(tmp_path: Path) -> None:
    s1 = tmp_path / "s1.html"
    s1.write_text(
        """<!doctype html><script>
        window.TOTAL = 3.0;
        // @cue 0.02 transition volume=0.8
        // @cue 0.45 typing duration=0.5 count=6 volume=0.65
        // @cue 1.80 latch volume=0.78
        </script>""",
        encoding="utf-8",
    )
    s2 = tmp_path / "s2.html"
    s2.write_text(
        """<!doctype html><script>
        window.TOTAL = 2.5;
        // @cue 0.00 transition volume=0.82
        // @cue 0.60 scrub duration=0.4 ticks=5 volume=0.55
        // @cue 2.10 chord volume=0.88
        </script>""",
        encoding="utf-8",
    )
    proj = tmp_path / "kinearc.project.json"
    proj.write_text(
        json.dumps(
            {
                "fps": 60,
                "width": 1920,
                "height": 1080,
                "scenes": [
                    {"path": "s1.html", "duration": 3.0},
                    {"path": "s2.html", "duration": 2.5},
                ],
            }
        ),
        encoding="utf-8",
    )
    out_cues = tmp_path / "audio" / "cues.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPTS_DIR / "kinearc_cli.py"),
            "autocue",
            "--project",
            str(proj),
            "--out",
            str(out_cues),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert out_cues.is_file()
    cues = json.loads(out_cues.read_text(encoding="utf-8"))
    assert len(cues) >= 16
    assert all(c["time"] >= 0.0 for c in cues)
    assert cues == sorted(cues, key=lambda c: c["time"])
    # Scene 2 chord at 3.0 + 2.10 = 5.10s
    assert any(abs(c["time"] - 5.10) < 0.05 and "analog_chord" in c["file"] for c in cues)
    # Typing burst produced multiple key_clack variants
    clacks = [c for c in cues if "key_clack_" in c["file"]]
    assert len(clacks) == 6
    assert len({c["file"] for c in clacks}) >= 2

    # Standalone --scene invocation without explicit @cue annotations falls back to springProgress/transition heuristics
    s_auto = tmp_path / "s_auto.html"
    s_auto.write_text(
        """<!doctype html><script>
        registerScene({ totalDuration: 3.0, onFrame({ t }) {
          const a = springProgress(t, { delay: 0.25 });
          const b = springProgress(t, { delay: 1.15 });
        }});
        </script>""",
        encoding="utf-8",
    )
    out_auto = tmp_path / "auto_cues.json"
    proc_scene = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPTS_DIR / "kinearc_cli.py"),
            "autocue",
            "--scene",
            str(s_auto),
            "--out",
            str(out_auto),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc_scene.returncode == 0, proc_scene.stderr
    auto_cues = json.loads(out_auto.read_text(encoding="utf-8"))
    assert len(auto_cues) >= 3


def test_anti_ai_slop_reference_and_craft_gl3d_runtime() -> None:
    ref_doc = REPO_ROOT / "references" / "anti-ai-slop.md"
    assert ref_doc.is_file(), "Missing references/anti-ai-slop.md"
    ref_text = ref_doc.read_text(encoding="utf-8")
    for token in (
        "Ban List",
        "Obsidian",
        "Editorial",
        "Optical",
        "Pearl",
        "Negative Space",
        "autocue",
        "drawFilmGrain",
        "drawTactileCursor",
        "drawMachinedPanel",
        "drawBlurRevealText",
        "drawPearlCard",
        "drawPortalFlash",
    ):
        assert token in ref_text, f"references/anti-ai-slop.md missing token {token!r}"

    skill_md = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
    readme_md = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "references/anti-ai-slop.md" in skill_md
    assert "references/anti-ai-slop.md" in readme_md
    assert "autocue" in skill_md and "autocue" in readme_md

    craft_js = REPO_ROOT / "assets" / "craft" / "kinearc-gl3d.js"
    assert craft_js.is_file(), "Missing assets/craft/kinearc-gl3d.js"
    js_text = craft_js.read_text(encoding="utf-8")
    for fn_name in (
        "export function drawCraftBackdrop",
        "export function drawMachinedPanel",
        "export function drawTactileCursor",
        "export function drawFilmGrain",
        "export function drawKineticHeadline",
        "export function drawBlurRevealText",
        "export function drawPearlCard",
        "export function drawPortalFlash",
        "export function createCylinderMesh",
        "export function createChamferSlabMesh",
    ):
        assert fn_name in js_text, f"assets/craft/kinearc-gl3d.js missing {fn_name!r}"


def test_overhauled_promo_and_tutorial_anti_slop_and_autocue_density() -> None:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import kinearc_cli

    promo_dir = REPO_ROOT / "examples" / "kinearc-promo-3d"
    tut_dir = REPO_ROOT / "examples" / "kinearc-tutorial"

    # Both widescreen (16:9) and vertical (9:16) manifests exist for Promo and validate cleanly
    widescreen_manifest = kinearc_cli.validate_manifest(promo_dir / "kinearc.project.json")
    vertical_manifest = kinearc_cli.validate_manifest(promo_dir / "kinearc.vertical.project.json")
    assert widescreen_manifest["width"] == 1920 and widescreen_manifest["height"] == 1080
    assert vertical_manifest["width"] == 1080 and vertical_manifest["height"] == 1920
    assert widescreen_manifest["scenes"] == vertical_manifest["scenes"]

    tut_manifest = kinearc_cli.validate_manifest(tut_dir / "kinearc.project.json")
    assert tut_manifest["width"] == 1920 and tut_manifest["height"] == 1080

    for ex_dir in (promo_dir, tut_dir):
        scenes = sorted((ex_dir / "scenes").glob("*.html"))
        assert len(scenes) >= 4
        for scene_p in scenes:
            txt = scene_p.read_text(encoding="utf-8")
            assert "#6c8cff" not in txt.lower(), f"Banned AI indigo #6c8cff still in {scene_p.name}"
            assert "#3ad29f" not in txt.lower(), f"Banned AI mint #3ad29f still in {scene_p.name}"
            assert "drawCraftBackdrop" in txt, f"{scene_p.name} missing drawCraftBackdrop"
            assert "drawFilmGrain" in txt, f"{scene_p.name} missing drawFilmGrain"
            assert "@cue" in txt, f"{scene_p.name} missing declarative @cue directives"
            if ex_dir == promo_dir:
                assert "responsive: true" in txt, f"Promo scene {scene_p.name} must support responsive: true for 16:9 + 9:16"

    promo_cues = json.loads((promo_dir / "audio" / "cues.json").read_text(encoding="utf-8"))
    tut_cues = json.loads((tut_dir / "audio" / "cues.json").read_text(encoding="utf-8"))
    assert len(promo_cues) >= 18, f"Expected >= 18 breathable tactile cues in promo, got {len(promo_cues)}"
    assert len(tut_cues) >= 24, f"Expected >= 24 breathable tactile cues in tutorial, got {len(tut_cues)}"


def test_audio_mix_handles_dense_cues_without_cli_length_overflow(tmp_path: Path) -> None:
    # Regression guard: 220+ SFX cues used to exceed Windows CreateProcess 32KB cmdline limit (WinError 206)
    cues = [
        {
            "file": f"sfx/key_clack_0{(i % 3) + 1}.wav",
            "time": round(0.05 + i * 0.04, 3),
            "volume": 0.65,
        }
        for i in range(220)
    ]
    cues_json = tmp_path / "dense_cues.json"
    cues_json.write_text(json.dumps(cues), encoding="utf-8")
    out_wav = tmp_path / "dense_mix.wav"
    proc = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "audio_mix.py"), "mix", "--sfx", str(cues_json), "--out", str(out_wav)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert out_wav.is_file() and out_wav.stat().st_size > 100000


def test_torus_knot_mesh_uses_continuous_frame_without_flip() -> None:
    for rel_js in (
        "assets/craft/kinearc-gl3d.js",
        "examples/kinearc-promo-3d/scenes/kinearc-gl3d.js",
        "examples/kinearc-tutorial/scenes/kinearc-gl3d.js",
    ):
        txt = (REPO_ROOT / rel_js).read_text(encoding="utf-8")
        assert "Math.abs(T[1]) < 0.9" not in txt, f"Discontinuous up-vector flip found in {rel_js}"


def test_autocue_ignores_quoted_strings_and_infers_const_total(tmp_path: Path) -> None:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import auto_cue

    s1 = tmp_path / "code_demo.html"
    s1.write_text(
        """<!doctype html><script>
        const TOTAL = 6.0;
        const codeLines = [
          "// @cue 0.45 transition volume=0.84",
          "// @cue 1.38 typing duration=0.76 count=9",
        ];
        // @cue 0.02 swish volume=0.72
        // @cue 5.20 chord volume=0.88
        </script>""",
        encoding="utf-8",
    )
    cues, dur = auto_cue.extract_scene_cues(s1)
    assert dur == 6.0
    # 0.02 - 0.030 preroll clamps cleanly to 0.0
    assert cues[0]["time"] == 0.0 and "air_swish_fast" in cues[0]["file"]
    # Quoted "// @cue 0.45 transition" and "// @cue 1.38 typing" must NOT inject phantom cues
    assert len(cues) == 2, f"Expected only 2 real cues, got {cues}"
    assert abs(cues[1]["time"] - 5.20) < 0.01

    # Missing scene path/file/src/html raises ValueError cleanly
    bad_proj = tmp_path / "bad.project.json"
    bad_proj.write_text(json.dumps({"scenes": [{"duration": 3.0}]}), encoding="utf-8")
    try:
        auto_cue.generate_project_cues(bad_proj)
        assert False, "Expected ValueError for scene object without path/file/src/html"
    except ValueError:
        pass


def test_audio_mix_preserves_unity_gain_after_overlapping_peak(tmp_path: Path) -> None:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import audio_mix

    # Construct a hot 0.90 stereo overlap at t=0.05s followed by a quiet 0.40 impulse-like cue at t=1.50s
    cues = [
        ("assets/sfx/sub_impact.wav", 0.05, 0.95),
        ("assets/sfx/sub_impact.wav", 0.05, 0.95),  # overlaps -> raw peak > 1.3
        ("assets/sfx/ui_tap.wav", 1.50, 0.70),
    ]
    resolved_cues = [(str(REPO_ROOT / f), t, v) for f, t, v in cues]
    bus_wav = tmp_path / "bus.wav"
    audio_mix._precomposite_sfx_bus(resolved_cues, 2.5, str(bus_wav))

    bus_quiet = tmp_path / "bus_quiet.wav"
    audio_mix._precomposite_sfx_bus([(str(REPO_ROOT / "assets/sfx/ui_tap.wav"), 1.50, 0.70)], 2.5, str(bus_quiet))

    with wave.open(str(bus_wav), "rb") as wf_hot, wave.open(str(bus_quiet), "rb") as wf_ref:
        import numpy as np

        hot = np.frombuffer(wf_hot.readframes(wf_hot.getnframes()), dtype="<i2").reshape(-1, 2)
        ref = np.frombuffer(wf_ref.readframes(wf_ref.getnframes()), dtype="<i2").reshape(-1, 2)
        # Region t=1.50s..1.60s (samples 72000..76800) must stay within 5% of unity reference gain
        s0, s1 = int(1.50 * 48000), int(1.56 * 48000)
        peak_hot = int(np.max(np.abs(hot[s0:s1])))
        peak_ref = int(np.max(np.abs(ref[s0:s1])))
        assert peak_hot >= int(peak_ref * 0.95), f"Global normalization attenuated quiet cue: {peak_hot} vs {peak_ref}"


def test_chamfer_slab_mesh_is_watertight_manifold() -> None:
    import shutil

    node_bin = shutil.which("node")
    assert node_bin
    script = (
        "import { createChamferSlabMesh } from './assets/craft/kinearc-gl3d.js';\n"
        "const m = createChamferSlabMesh(2.0, 1.2, 0.22, 0.06);\n"
        "const p = m.positions;\n"
        "const key = (i) => `${p[i].toFixed(4)},${p[i+1].toFixed(4)},${p[i+2].toFixed(4)}`;\n"
        "const edges = new Map();\n"
        "for (let t = 0; t < p.length; t += 9) {\n"
        "  const vs = [key(t), key(t+3), key(t+6)];\n"
        "  for (let k = 0; k < 3; k++) {\n"
        "    const a = vs[k], b = vs[(k+1)%3];\n"
        "    const ek = a < b ? `${a}|${b}` : `${b}|${a}`;\n"
        "    edges.set(ek, (edges.get(ek) || 0) + 1);\n"
        "  }\n"
        "}\n"
        "const bad = [...edges.entries()].filter(([, c]) => c !== 2);\n"
        "if (bad.length) { console.error('Non-manifold edges:', bad.length, bad.slice(0,5)); process.exit(1); }\n"
        "console.log('manifold edges:', edges.size);\n"
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout





