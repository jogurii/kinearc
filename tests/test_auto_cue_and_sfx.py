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


def test_multistyle_organic_sfx_pack_and_spatial_room_mix(tmp_path: Path) -> None:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import audio_mix
    import auto_cue
    import build_sfx_pack
    import numpy as np

    # 1. All 3 organic acoustic styles generate finite stereo 44.1kHz WAVs without warnings
    for style_name in build_sfx_pack.VALID_STYLES:
        out_style_dir = tmp_path / f"pack_{style_name}"
        res = build_sfx_pack.build_sfx_pack(out_style_dir, style=style_name)
        assert res["style"] == style_name
        assert len(res["files"]) == 24
        cat = json.loads(Path(res["catalog"]).read_text(encoding="utf-8"))
        assert cat.get("style") == style_name
        # Spot check bgm_ambient & ui_tap stereo & finite RMS
        for check_name in ("ui_tap.wav", "bgm_groove.wav", "bgm_ambient.wav"):
            wav_p = out_style_dir / check_name
            with wave.open(str(wav_p), "rb") as wf:
                assert wf.getnchannels() == 2
                assert wf.getframerate() == 44100
                data = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(np.float64)
                assert np.all(np.isfinite(data))
                assert float(np.sqrt(np.mean(data ** 2))) > 200.0

    # 2. Auto-cue cycles round-robin variants on repeated events (tap -> ui_tap, ui_tap_02, ui_tap_03)
    s_rr = tmp_path / "rr_scene.html"
    s_rr.write_text(
        """<!doctype html><script>
        window.TOTAL = 2.0;
        // @cue 0.20 tap
        // @cue 0.60 tap
        // @cue 1.00 tap pan=-0.5
        </script>""",
        encoding="utf-8",
    )
    rr_cues, _ = auto_cue.extract_scene_cues(s_rr)
    assert len({c["file"] for c in rr_cues}) == 3
    assert rr_cues[2].get("pan") == -0.5

    # 3. Spatial pan directs dominant energy to panned ear & room convolution adds tail vs dry
    tap_wav = str(REPO_ROOT / "assets" / "sfx" / "ui_tap.wav")
    bus_left = tmp_path / "left.wav"
    audio_mix._precomposite_sfx_bus(
        [{"file": tap_wav, "time": 0.05, "volume": 0.85, "pan": -0.95}],
        0.5,
        str(bus_left),
        humanize=False,
        room_wet=0.0,
    )
    with wave.open(str(bus_left), "rb") as wf:
        arr = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").reshape(-1, 2).astype(np.float64)
        l_rms = float(np.sqrt(np.mean(arr[:, 0] ** 2)))
        r_rms = float(np.sqrt(np.mean(arr[:, 1] ** 2)))
        assert l_rms > r_rms * 1.25

    bus_wet = tmp_path / "wet.wav"
    audio_mix._precomposite_sfx_bus(
        [{"file": tap_wav, "time": 0.05, "volume": 0.85, "pan": 0.0}],
        0.5,
        str(bus_wet),
        humanize=False,
        room_wet=0.16,
    )
    with wave.open(str(bus_wet), "rb") as wfw, wave.open(str(bus_left), "rb") as wfd:
        aw = np.frombuffer(wfw.readframes(wfw.getnframes()), dtype="<i2").reshape(-1, 2).astype(np.float64)
        tail_rms = float(np.sqrt(np.mean(aw[int(0.14 * 48000) : int(0.24 * 48000)] ** 2)))
        assert tail_rms > 1.0


def test_extract_audio_style_and_per_scene_material_matching(tmp_path: Path) -> None:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import audio_mix
    import auto_cue
    import extract_audio_style
    import numpy as np

    # 1. Universal reference audio extractor works on any clean WAV/video input (no hardcoding)
    sr = 48000
    dur = 2.4
    n = int(sr * dur)
    t = np.arange(n, dtype=np.float64) / sr
    sig = np.zeros((n, 2), dtype=np.float64)
    # Place 3 distinct transient events: crisp air burst at 0.25s, sub drop at 0.90s, chime at 1.65s
    rng = np.random.default_rng(77)
    s0 = int(0.25 * sr)
    k0 = int(0.06 * sr)
    burst = rng.standard_normal(k0)
    freqs0 = np.fft.rfftfreq(k0, 1.0 / sr)
    hi_burst = np.fft.irfft(np.fft.rfft(burst) * (freqs0 >= 4500.0), n=k0) * np.exp(-np.arange(k0) / (0.01 * sr))
    hi_burst /= float(np.max(np.abs(hi_burst))) or 1.0
    sig[s0 : s0 + k0, :] += (hi_burst * 0.65)[:, None]

    s1 = int(0.90 * sr)
    k1 = int(0.28 * sr)
    t1 = np.arange(k1) / sr
    sub_drop = np.sin(2.0 * np.pi * 55.0 * t1) * np.exp(-t1 / 0.08) * 0.72
    sig[s1 : s1 + k1, :] += sub_drop[:, None]

    s2 = int(1.65 * sr)
    k2 = int(0.35 * sr)
    t2 = np.arange(k2) / sr
    chime = (0.5 * np.sin(2.0 * np.pi * 1320.0 * t2) + 0.35 * np.sin(2.0 * np.pi * 5280.0 * t2)) * np.exp(-t2 / 0.10) * 0.60
    sig[s2 : s2 + k2, :] += chime[:, None]

    ref_wav = tmp_path / "custom_ref.wav"
    extract_audio_style._write_stereo_wav(ref_wav, sig, sr=sr)

    out_extract = tmp_path / "extracted_pack"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPTS_DIR / "kinearc_cli.py"),
            "extract-audio",
            "--input",
            str(ref_wav),
            "--out_dir",
            str(out_extract),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    prof = json.loads((out_extract / "audio_profile.json").read_text(encoding="utf-8"))
    assert prof["has_audio"] is True
    assert prof["recommended_bgm_mode"] == "none"
    assert len(prof["extracted_stems"]) >= 2
    assert (out_extract / "extracted_cues.json").is_file()
    assert prof["remake_file_count"] == 24
    assert (out_extract / "sfx" / "catalog.json").is_file()
    assert (out_extract / "sfx" / "ui_tap.wav").is_file()

    # 2. Per-scene visual analyzer maps bright cool crystal vs dark obsidian deep-space distinctly
    light_crystal_scene = tmp_path / "scene_light.html"
    light_crystal_scene.write_text(
        """<!doctype html><style>body{background:#f6f7fb}</style><script>
        const m = createCrystalMesh(8, 0.8, 2.0, 0.2);
        drawCraftBackdrop(ctx, W, H, t, { theme: "pearl", coolPool: "rgba(56, 189, 248, 0.20)" });
        // @cue 0.40 tap
        </script>""",
        encoding="utf-8",
    )
    dark_portal_scene = tmp_path / "scene_dark.html"
    dark_portal_scene.write_text(
        """<!doctype html><style>body{background:#05040c}</style><script>
        const m = createTorusKnotMesh(1.0, 0.2);
        drawCraftBackdrop(ctx, W, H, t, { theme: "midnight", warmPool: "rgba(180, 90, 220, 0.22)" });
        drawPortalFlash(ctx, W, H, t);
        // @cue 0.40 tap
        </script>""",
        encoding="utf-8",
    )
    explicit_override = tmp_path / "scene_override.html"
    explicit_override.write_text(
        """<!doctype html><script>
        // @scene-audio material=metal temp=cool space=medium tilt_db=1.4 room=0.09
        // @cue 0.20 tap
        </script>""",
        encoding="utf-8",
    )

    cues_light, _ = auto_cue.extract_scene_cues(light_crystal_scene)
    cues_dark, _ = auto_cue.extract_scene_cues(dark_portal_scene)
    cues_ovr, _ = auto_cue.extract_scene_cues(explicit_override)

    assert cues_light[0]["tilt_db"] > 0.5
    assert cues_light[0]["cutoff_hz"] >= 15000.0
    assert cues_light[0]["room"] < cues_dark[0]["room"]
    assert cues_dark[0]["tilt_db"] < -1.0
    assert cues_dark[0]["cutoff_hz"] <= 9000.0
    assert cues_dark[0]["sub_boost"] > 1.1
    assert cues_ovr[0]["tilt_db"] == 1.4 and cues_ovr[0]["room"] == 0.09

    # 3. Audio mixer applies per-cue tilt/cutoff/sub_boost: dark cue outputs measurably stronger low end & softer highs
    tap_file = str(REPO_ROOT / "assets" / "sfx" / "ui_tap.wav")
    wav_bright = tmp_path / "mix_bright.wav"
    wav_dark = tmp_path / "mix_dark.wav"
    audio_mix._precomposite_sfx_bus([{**cues_light[0], "file": tap_file}], 0.5, str(wav_bright), humanize=False)
    audio_mix._precomposite_sfx_bus([{**cues_dark[0], "file": tap_file}], 0.5, str(wav_dark), humanize=False)

    with wave.open(str(wav_bright), "rb") as wb, wave.open(str(wav_dark), "rb") as wd:
        ab = np.frombuffer(wb.readframes(wb.getnframes()), dtype="<i2").reshape(-1, 2).mean(axis=1).astype(np.float64)
        ad = np.frombuffer(wd.readframes(wd.getnframes()), dtype="<i2").reshape(-1, 2).mean(axis=1).astype(np.float64)
        fb = np.fft.rfftfreq(len(ab), 1.0 / 48000)
        fd = np.fft.rfftfreq(len(ad), 1.0 / 48000)
        pb = np.abs(np.fft.rfft(ab)) ** 2
        pd = np.abs(np.fft.rfft(ad)) ** 2
        hi_ratio_b = float(np.sum(pb[fb >= 4000.0]) / (np.sum(pb) + 1e-9))
        hi_ratio_d = float(np.sum(pd[fd >= 4000.0]) / (np.sum(pd) + 1e-9))
        assert hi_ratio_b > hi_ratio_d * 1.4







