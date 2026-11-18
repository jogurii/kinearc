import json
import math
import re
import shutil
import struct
import subprocess
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
UI_DIR = SCRIPTS_DIR / "ui"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

FORBIDDEN_LEGACY_ENGINE = "mot" + "lab"
FORBIDDEN_OLD_BRAND = "motion" + "2code"
FORBIDDEN_TONE_WORD = "stu" + "dio"

UI_JS_MODULES = ("stage.js", "timeline.js", "annotations.js", "drawer.js", "app.js")


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


def _build_fixture_a(tmp_path: Path):
    import kinearc_ui

    clone_path = tmp_path / "clone.mp4"
    ref_path = tmp_path / "orig.mp4"
    voice_path = tmp_path / "vo.wav"
    bgm_path = tmp_path / "bgm.wav"
    sfx_wav = tmp_path / "pop.wav"
    cues_path = tmp_path / "cues.json"
    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    scene_html = scenes_dir / "01.html"
    scene_html.write_text(
        "<!doctype html><html><body><script>"
        "window.kinearc = { totalDuration: 2.0, ready: Promise.resolve(), seek(t) { window.__lastT = t; } };"
        "</script></body></html>",
        encoding="utf-8",
    )

    out_dir = tmp_path / ".kinearc_analysis"
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

    _write_wav(voice_path, [(0.45, 440.0, 0.5), (0.55, 0.0, 0.0), (0.45, 550.0, 0.8)])
    _write_wav(bgm_path, [(0.60, 220.0, 0.25)])
    _write_wav(sfx_wav, [(0.15, 880.0, 0.6)])

    cues_data = [{"file": str(sfx_wav), "time": 0.15, "volume": 0.85}]
    cues_path.write_text(json.dumps(cues_data), encoding="utf-8")

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
                    {"rank": 1, "frame": 6, "timestamp_sec": 0.2, "mae": 18.7},
                    {"rank": 2, "frame": 2, "timestamp_sec": 0.067, "mae": 11.4},
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
        scene_path=str(scene_html),
        out_dir=str(out_dir),
        voice_path=str(voice_path),
        bgm_path=str(bgm_path),
        sfx_path=str(cues_path),
    )
    return state, out_dir


def test_all_ui_assets_hygiene_and_node_syntax() -> None:
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js is required to check scripts/ui/*.js"

    patterns = [
        ("legacy_engine", re.compile(re.escape(FORBIDDEN_LEGACY_ENGINE), re.IGNORECASE)),
        ("old_brand", re.compile(re.escape(FORBIDDEN_OLD_BRAND), re.IGNORECASE)),
        ("forbidden_word", re.compile(re.escape(FORBIDDEN_TONE_WORD), re.IGNORECASE)),
    ]

    all_assets = [UI_DIR / "index.html", UI_DIR / "styles.css", *(UI_DIR / m for m in UI_JS_MODULES)]
    hits: list[str] = []
    for asset in all_assets:
        assert asset.is_file(), f"Missing UI asset: {asset}"
        content = asset.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            for label, pat in patterns:
                if pat.search(line):
                    hits.append(f"{asset.name}:{line_no} [{label}] -> {line.strip()}")
        non_ns = content.replace("http://www.w3.org/2000/svg", "")
        assert "https://" not in non_ns and "http://" not in non_ns, f"External URL found in {asset.name}"

    assert hits == [], "Forbidden terms found in scripts/ui/:\n" + "\n".join(hits)

    for js_name in UI_JS_MODULES:
        js_path = UI_DIR / js_name
        proc = subprocess.run(
            [node_bin, "--check", str(js_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"node --check failed for {js_name}:\n{proc.stderr}"


def test_node_unit_checks_timeline_annotations_drawer() -> None:
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js is required for ES module unit tests"

    timeline_uri = (UI_DIR / "timeline.js").as_uri()
    annotations_uri = (UI_DIR / "annotations.js").as_uri()
    drawer_uri = (UI_DIR / "drawer.js").as_uri()
    app_uri = (UI_DIR / "app.js").as_uri()

    script = rf"""
import assert from 'node:assert/strict';
import {{
  toFiniteNumber,
  formatTimecode,
  formatTimecodeReadout,
  shouldIgnoreShortcutTarget,
  computeMarkerPercent,
  computeLoopStatus,
  buildMarkerDescriptors,
  createTimeline,
}} from {json.dumps(timeline_uri)};
import {{
  normalizeBox,
  formatSelectionTarget,
  buildRevisionPrompt,
  createAnnotations,
}} from {json.dumps(annotations_uri)};
import {{
  summarizeQaState,
  buildExportPresetHint,
  createDrawer,
}} from {json.dumps(drawer_uri)};

// 1. Timecode formatting
assert.equal(formatTimecode(0), '00:00.00');
assert.equal(formatTimecode(-5), '00:00.00');
assert.equal(formatTimecode(NaN), '00:00.00');
assert.equal(formatTimecode(1.25), '00:01.25');
assert.equal(formatTimecode(65.5), '01:05.50');
assert.equal(formatTimecode(59.999), '01:00.00');
assert.equal(formatTimecodeReadout(1.5, 4.0, 45), '00:01.50 / 00:04.00 · f45');

// 2. Keyboard-input ignore checks
assert.equal(shouldIgnoreShortcutTarget({{ tagName: 'INPUT' }}), true);
assert.equal(shouldIgnoreShortcutTarget({{ tagName: 'input' }}), true);
assert.equal(shouldIgnoreShortcutTarget({{ tagName: 'TEXTAREA' }}), true);
assert.equal(shouldIgnoreShortcutTarget({{ tagName: 'SELECT' }}), true);
assert.equal(shouldIgnoreShortcutTarget({{ tagName: 'DIV', isContentEditable: true }}), true);
assert.equal(shouldIgnoreShortcutTarget({{ tagName: 'DIV', isContentEditable: false }}), false);
assert.equal(shouldIgnoreShortcutTarget({{ tagName: 'BUTTON' }}), false);
assert.equal(shouldIgnoreShortcutTarget(null), false);

// 3. Marker percentage math & clamping
assert.equal(computeMarkerPercent({{ frame: 0, totalFrames: 10 }}), 0);
assert.equal(computeMarkerPercent({{ frame: 9, totalFrames: 10 }}), 100);
assert.ok(Math.abs(computeMarkerPercent({{ frame: 5, totalFrames: 11 }}) - 50) < 0.001);
assert.equal(computeMarkerPercent({{ timeSec: 1.5, durationSec: 3.0 }}), 50);
assert.equal(computeMarkerPercent({{ timeSec: 10, durationSec: 3.0 }}), 100);
assert.equal(computeMarkerPercent({{ timeSec: -1, durationSec: 3.0 }}), 0);
assert.equal(computeMarkerPercent({{}}), 0);

// 4. Loop status
assert.equal(computeLoopStatus({{}}).present, false);
assert.equal(computeLoopStatus({{ clone_loop_mae: null, source_loop_mae: '' }}).present, false);
assert.equal(computeLoopStatus({{ clone_loop_mae: 2.5 }}).clean, true);
assert.equal(computeLoopStatus({{ clone_loop_mae: 6.0 }}).clean, true);
assert.equal(computeLoopStatus({{ clone_loop_mae: 6.1 }}).clean, false);
assert.equal(computeLoopStatus({{ source_loop_mae: 8.2 }}).clean, false);

// 5. Empty-state & populated marker descriptors
assert.deepEqual(buildMarkerDescriptors({{}}), []);
assert.deepEqual(buildMarkerDescriptors({{ scene_cuts: [], worst_frames: [], sfx_cues: [] }}), []);

const markers = buildMarkerDescriptors({{
  fps: 30,
  total_frames: 61,
  duration_sec: 2.0,
  scene_cuts: [{{ cut_index: 0, before_frame: 29, after_frame: 30, timestamp_sec: 1.0, delta_mae: 24.5 }}],
  worst_frames: [
    {{ rank: 3, frame: 10, mae: 5.0 }},
    {{ rank: 1, frame: 45, mae: 19.25 }},
    {{ rank: 2, frame: 15, mae: 12.1 }},
    {{ rank: 6, frame: 59, mae: 1.0 }},
    {{ rank: 4, frame: 20, mae: 4.0 }},
    {{ rank: 5, frame: 25, mae: 3.0 }},
  ],
  sfx_cues: [{{ file: 'C:\\\\sfx\\\\whoosh.wav', time: 0.5 }}],
}});
const worstMarkers = markers.filter((m) => m.kind === 'worst');
assert.equal(worstMarkers.length, 5);
assert.equal(worstMarkers[0].rank, 1);
assert.equal(worstMarkers[0].frame, 45);
assert.equal(worstMarkers[0].tooltip, 'MAE 19.25 @ f45');
const cutMarker = markers.find((m) => m.kind === 'cut');
assert.equal(cutMarker.frame, 30);
assert.equal(cutMarker.pct, 50);
const sfxMarker = markers.find((m) => m.kind === 'sfx');
assert.equal(sfxMarker.file, 'whoosh.wav');
assert.equal(sfxMarker.tooltip, 'whoosh.wav @ 0.50s');

// 6. Annotations pure helpers
assert.deepEqual(normalizeBox([120, 300], [40, 80]), [40, 80, 120, 300]);
assert.equal(formatSelectionTarget({{ frame: 4, timeSec: 0.133 }}), 'Frame f4 (0.13s) · Full frame');
assert.equal(formatSelectionTarget({{ frame: 4, timeSec: 0.133, point: [10, 20] }}), 'Frame f4 (0.13s) · Point (10, 20)');
assert.equal(formatSelectionTarget({{ frame: 4, timeSec: 0.133, bbox: [1, 2, 3, 4] }}), 'Frame f4 (0.13s) · Box [1, 2, 3, 4]');

const promptCustom = buildRevisionPrompt({{
  outDir: '/tmp/work/.kinearc_analysis',
  notes: [
    {{ id: 1, status: 'open', frame: 5, time_sec: 0.17, bbox: [10, 20, 30, 40], text: 'Fix bounce', image: 'selection/note_1.png' }},
    {{ id: 2, status: 'done', frame: 2, time_sec: 0.07, text: 'Already resolved' }},
  ],
}});
assert.ok(promptCustom.includes('/tmp/work/.kinearc_analysis/selection.json'));
assert.ok(promptCustom.includes('1 open'));
assert.ok(promptCustom.includes('Fix bounce'));
assert.ok(!promptCustom.includes('Already resolved'));
assert.ok(buildRevisionPrompt({{}}).includes('.kinearc_analysis/selection.json'));

// 7. Drawer QA & Export helpers
const qaEmpty = summarizeQaState({{ scene_cuts: [], worst_frames: [] }});
assert.equal(qaEmpty.hasQaMetrics, false);
assert.equal(qaEmpty.loopKnown, false);
assert.equal(qaEmpty.worstFrames.length, 0);
assert.equal(qaEmpty.sceneCuts.length, 0);

const qaFull = summarizeQaState({{
  overall_mae: 4.5,
  overall_psnr_db: 33.2,
  clone_loop_mae: 7.5,
  worst_frames: [{{ rank: 1, frame: 3, mae: 9.1 }}],
  scene_cuts: [{{ cut_index: 0, before_frame: 1, after_frame: 2, pair_image: 'cuts/cut_0000.png' }}],
}});
assert.equal(qaFull.hasQaMetrics, true);
assert.equal(qaFull.loopKnown, true);
assert.equal(qaFull.loopClean, false);
assert.equal(qaFull.sceneCuts[0].thumbUrl, '/cuts/cut_0000.png');

for (const preset of ['still', '1080p60', '4k60']) {{
  const hint = buildExportPresetHint(preset, {{ width: 1080, height: 1920, fps: 60 }}, 12);
  assert.ok(hint.includes('kinearc_cli.py'), `Missing runnable CLI command on ${{preset}}`);
  assert.ok(!/arrives in Phase 3/i.test(hint), `Stale Phase 3 placeholder on ${{preset}}`);
  assert.ok(!/stu\u0064io/i.test(hint));
  assert.ok(!/motion\u0032code/i.test(hint));
}}
assert.ok(buildExportPresetHint('still', {{ width: 1080, height: 1920, fps: 60 }}, 12).includes('stills'));
assert.ok(buildExportPresetHint('1080p60', {{ width: 1080, height: 1920, fps: 60 }}, 12).includes('--scale 1'));
assert.ok(buildExportPresetHint('4k60', {{ width: 1080, height: 1920, fps: 60 }}, 12).includes('--scale 2'));

// 7b. Regression: null / empty-string JSON fields MUST NOT coerce via Number(null) === 0
assert.equal(toFiniteNumber(null), null);
assert.equal(toFiniteNumber(undefined), null);
assert.equal(toFiniteNumber(''), null);
assert.equal(toFiniteNumber('   '), null);
assert.equal(toFiniteNumber(false), null);
assert.equal(toFiniteNumber(0), 0);
assert.equal(toFiniteNumber('0'), 0);

const nullMarkers = buildMarkerDescriptors({{
  fps: 30,
  total_frames: 60,
  duration_sec: 2.0,
  scene_cuts: [
    {{ cut_index: null, before_frame: 9, after_frame: null, timestamp_sec: '', delta_mae: null }},
    {{ cut_index: 1, before_frame: null, after_frame: null, timestamp_sec: null, delta_mae: '' }},
  ],
  worst_frames: [
    {{ rank: null, frame: 5, timestamp_sec: null, mae: 4.0 }},
    {{ rank: 1, frame: 12, timestamp_sec: 0.4, mae: 15.0 }},
    {{ rank: 2, frame: '', mae: 99.0 }},
    {{ rank: 3, frame: null, mae: 88.0 }},
  ],
}});
const nullCuts = nullMarkers.filter((m) => m.kind === 'cut');
assert.equal(nullCuts[0].frame, 10);
assert.ok(!nullCuts[0].tooltip.includes('ΔMAE'));
assert.equal(nullCuts[1].frame, 0);
assert.equal(nullCuts[1].tooltip, 'Cut @ f0');

const nullWorst = nullMarkers.filter((m) => m.kind === 'worst');
assert.equal(nullWorst.length, 2);
assert.equal(nullWorst[0].rank, 1);
assert.equal(nullWorst[0].frame, 12);
assert.equal(nullWorst[1].frame, 5);

const qaNulls = summarizeQaState({{
  overall_mae: null,
  overall_psnr_db: '',
  clone_loop_mae: null,
  source_loop_mae: '',
  worst_frames: [],
  scene_cuts: [
    {{ cut_index: null, before_frame: 4, after_frame: null, timestamp_sec: null, delta_mae: null }},
    {{ cut_index: '', before_frame: null, after_frame: '', timestamp_sec: '', delta_mae: '' }},
  ],
}});
assert.equal(qaNulls.hasQaMetrics, false);
assert.equal(qaNulls.loopKnown, false);
assert.equal(qaNulls.overallMaeLabel, '—');
assert.equal(qaNulls.psnrLabel, '—');
assert.equal(qaNulls.loopMaeLabel, '—');
assert.equal(qaNulls.sceneCuts[0].cutIndex, 0);
assert.equal(qaNulls.sceneCuts[0].beforeFrame, 4);
assert.equal(qaNulls.sceneCuts[0].afterFrame, 5);
assert.equal(qaNulls.sceneCuts[0].timestampSec, null);
assert.equal(qaNulls.sceneCuts[0].deltaMae, null);
assert.equal(qaNulls.sceneCuts[1].beforeFrame, null);
assert.equal(qaNulls.sceneCuts[1].afterFrame, 0);
assert.equal(qaNulls.sceneCuts[1].timestampSec, null);
assert.equal(qaNulls.sceneCuts[1].deltaMae, null);

const qaWorstNullSort = summarizeQaState({{
  worst_frames: [
    {{ rank: null, frame: 8, mae: 9.0 }},
    {{ rank: 1, frame: 2, mae: 12.0 }},
    {{ rank: 2, frame: '', mae: 50.0 }},
  ],
}});
assert.equal(qaWorstNullSort.worstFrames.length, 2);
assert.equal(qaWorstNullSort.worstFrames[0].frame, 2);
assert.equal(qaWorstNullSort.worstFrames[1].frame, 8);

// 8. Behavioral DOM integration across timeline, annotations, and drawer
class MockClassList {{
  constructor() {{ this.set = new Set(); }}
  add(...n) {{ for (const x of n) this.set.add(x); }}
  remove(...n) {{ for (const x of n) this.set.delete(x); }}
  toggle(name, force) {{
    if (force === undefined) {{
      if (this.set.has(name)) {{ this.set.delete(name); return false; }}
      this.set.add(name); return true;
    }}
    if (force) {{ this.set.add(name); return true; }}
    this.set.delete(name); return false;
  }}
  contains(name) {{ return this.set.has(name); }}
}}

function makeEl(tag, id = '') {{
  const attrs = {{}};
  const listeners = {{}};
  const el = {{
    tagName: tag.toUpperCase(),
    id,
    className: '',
    style: {{}},
    classList: new MockClassList(),
    dataset: {{}},
    children: [],
    value: '',
    min: '',
    max: '',
    checked: false,
    disabled: false,
    hidden: false,
    textContent: '',
    ownerDocument: null,
    setAttribute(k, v) {{ attrs[k] = String(v); }},
    getAttribute(k) {{ return attrs[k] ?? null; }},
    appendChild(c) {{ el.children.push(c); return c; }},
    append(...items) {{ for (const c of items) el.children.push(c); }},
    replaceChildren(...items) {{ el.children = [...items]; }},
    addEventListener(type, fn, opts) {{
      const list = (listeners[type] ||= []);
      list.push(fn);
      if (opts && opts.signal && typeof opts.signal.addEventListener === 'function') {{
        opts.signal.addEventListener('abort', () => {{
          const idx = list.indexOf(fn);
          if (idx >= 0) list.splice(idx, 1);
        }}, {{ once: true }});
      }}
    }},
    dispatchEvent(evt) {{
      evt.target = evt.target || el;
      for (const fn of listeners[evt.type] || []) fn(evt);
    }},
    querySelectorAll() {{ return []; }},
    getBoundingClientRect() {{ return {{ left: 0, top: 0, width: 600, height: 58 }}; }},
    blur() {{}},
    focus() {{}},
  }};
  return el;
}}

const doc = {{
  createElement(tag) {{
    const el = makeEl(tag);
    el.ownerDocument = doc;
    return el;
  }},
}};

const winListeners = {{}};
globalThis.window = {{
  devicePixelRatio: 1,
  addEventListener(type, fn) {{ (winListeners[type] ||= []).push(fn); }},
  dispatchEvent(evt) {{ for (const fn of winListeners[evt.type] || []) fn(evt); }},
}};

const copiedLog = [];
Object.defineProperty(globalThis, 'navigator', {{
  value: {{ clipboard: {{ async writeText(txt) {{ copiedLog.push(txt); }} }} }},
  configurable: true,
}});

const findById = (root, targetId) => {{
  if (!root) return null;
  if (root.id === targetId) return root;
  for (const child of root.children || []) {{
    const found = findById(child, targetId);
    if (found) return found;
  }}
  return null;
}};

const fetchUrls = [];
let lastMixPayload = null;
const notesStore = [{{ id: 1, status: 'open', frame: 2, time_sec: 0.067, bbox: [10, 10, 40, 40], point: null, text: 'Initial', image: 'selection/note_1.png' }}];
globalThis.fetch = async (url, opts = {{}}) => {{
  fetchUrls.push(url);
  if (url.startsWith('/api/audio-peaks')) {{
    return {{ ok: true, status: 200, async json() {{ return {{ bins: [0.1, 0.5, 0.9, 0.2] }}; }} }};
  }}
  if (url === '/api/notes' && (!opts.method || opts.method === 'GET')) {{
    return {{ ok: true, status: 200, async json() {{ return [...notesStore]; }} }};
  }}
  if (url === '/api/notes' && opts.method === 'POST') {{
    const body = JSON.parse(opts.body);
    const created = {{ id: 2, status: 'open', ...body, image: 'selection/note_2.png' }};
    notesStore.push(created);
    return {{ ok: true, status: 201, async json() {{ return created; }} }};
  }}
  if (url === '/api/audio/mix') {{
    lastMixPayload = opts.body ? JSON.parse(opts.body) : null;
    return {{ ok: false, status: 400, async json() {{ return {{ error: 'No audio sources specified for mix' }}; }} }};
  }}
  return {{ ok: false, status: 404, async json() {{ return {{ error: 'Not found' }}; }} }};
}};

const seekLog = [];
let overlayDrawerFn = null;
const mockStage = {{
  mode: 'clone',
  fitCalls: 0,
  seekTime(t, f) {{ seekLog.push({{ t, f }}); return Promise.resolve(); }},
  setAnnotationsDrawer(fn) {{ overlayDrawerFn = fn; }},
  redrawOverlay() {{}},
  fitStage() {{ this.fitCalls += 1; }},
  toFrameCoords(cx, cy) {{ return [cx * 2, cy * 2]; }},
  getState() {{ return {{ mode: this.mode, fps: 30, totalFrames: 30, durationSec: 1.0, currentFrameIdx: 0, currentTimeSec: 0 }}; }},
}};

const tEls = {{
  btnPlay: makeEl('button', 'btnPlay'),
  btnPrev1: makeEl('button', 'btnPrev1'),
  btnNext1: makeEl('button', 'btnNext1'),
  btnPrev10: makeEl('button', 'btnPrev10'),
  btnNext10: makeEl('button', 'btnNext10'),
  scrubber: makeEl('input', 'scrubber'),
  playheadLine: makeEl('div', 'playheadLine'),
  timecodeReadout: makeEl('div', 'timecodeReadout'),
  loopStatusPill: makeEl('span', 'loopStatusPill'),
  timelineTrack: makeEl('div', 'timelineTrack'),
  waveformCanvas: makeEl('canvas', 'waveformCanvas'),
  markersLayer: makeEl('div', 'markersLayer'),
}};
tEls.markersLayer.ownerDocument = doc;
tEls.waveformCanvas.getContext = () => ({{ clearRect() {{}}, fillRect() {{}}, fillStyle: '' }});

const toasts = [];
const tl = createTimeline({{
  stage: mockStage,
  info: {{
    fps: 30, total_frames: 30, duration_sec: 1.0,
    clone_loop_mae: 2.1,
    scene_cuts: [{{ cut_index: 0, before_frame: 14, after_frame: 15, timestamp_sec: 0.5 }}],
    worst_frames: [{{ rank: 1, frame: 20, mae: 14.2 }}],
    sfx_cues: [{{ file: 'click.wav', time: 0.25 }}],
    audio: {{ voice: true }},
  }},
  onToast: (m, k) => toasts.push({{ m, k }}),
  elements: tEls,
}});

await new Promise((r) => setTimeout(r, 10));
assert.equal(tEls.markersLayer.children.length, 3);
assert.equal(tEls.loopStatusPill.classList.contains('clean'), true);
tEls.btnNext10.dispatchEvent({{ type: 'click' }});
assert.equal(tl.getState().currentFrame, 10);
window.dispatchEvent({{ type: 'keydown', key: 'ArrowRight', shiftKey: false, target: makeEl('div'), preventDefault() {{}} }});
assert.equal(tl.getState().currentFrame, 11);
// Ignored when typing in TEXTAREA
window.dispatchEvent({{ type: 'keydown', key: 'ArrowRight', shiftKey: false, target: makeEl('textarea'), preventDefault() {{}} }});
assert.equal(tl.getState().currentFrame, 11);
// Clicking worst marker seeks to f20
tEls.markersLayer.children.find((b) => b.dataset.markerKind === 'worst').dispatchEvent({{ type: 'click', stopPropagation() {{}} }});
assert.equal(tl.getState().currentFrame, 20);
// updateTiming with null / empty-string preserves valid fps, totalFrames & durationSec
tl.updateTiming({{ fps: null, total_frames: null, duration_sec: '' }});
assert.equal(tl.getState().fps, 30);
assert.equal(tl.getState().totalFrames, 30);
assert.equal(tl.getState().durationSec, 1.0);

const aEls = {{
  overlayCanvas: makeEl('canvas', 'overlayCanvas'),
  selectionTarget: makeEl('span', 'selectionTarget'),
  btnClearSel: makeEl('button', 'btnClearSel'),
  noteInput: makeEl('textarea', 'noteInput'),
  btnSaveNote: makeEl('button', 'btnSaveNote'),
  btnCopyRevision: makeEl('button', 'btnCopyRevision'),
  btnCopyPrompt: makeEl('button', 'btnCopyPrompt'),
  notesList: makeEl('div', 'notesList'),
}};
aEls.notesList.ownerDocument = doc;
const ann = createAnnotations({{
  stage: mockStage,
  timeline: tl,
  info: {{ out_dir: '.kinearc_analysis' }},
  getCurrentFrame: () => tl.getState(),
  onSeek: (f) => tl.seekToFrame(f),
  onToast: (m, k) => toasts.push({{ m, k }}),
  elements: aEls,
}});
await new Promise((r) => setTimeout(r, 10));
assert.equal(aEls.notesList.children.length, 1);

// Point click (< 6px) then drag box (>= 6px)
aEls.overlayCanvas.dispatchEvent({{ type: 'pointerdown', button: 0, clientX: 10, clientY: 20 }});
aEls.overlayCanvas.dispatchEvent({{ type: 'pointerup', button: 0, clientX: 12, clientY: 21 }});
assert.deepEqual(ann.getSelection().point, [24, 42]);
aEls.overlayCanvas.dispatchEvent({{ type: 'pointerdown', button: 0, clientX: 10, clientY: 20 }});
aEls.overlayCanvas.dispatchEvent({{ type: 'pointermove', button: 0, clientX: 50, clientY: 60 }});
aEls.overlayCanvas.dispatchEvent({{ type: 'pointerup', button: 0, clientX: 50, clientY: 60 }});
assert.deepEqual(ann.getSelection().bbox, [20, 40, 100, 120]);

// Draw overlay with xOffset in SBS mode
const strokeColors = [];
overlayDrawerFn({{
  ctx: {{
    save() {{}}, restore() {{}}, fillRect() {{}}, fillText() {{}},
    strokeRect() {{ strokeColors.push(this.strokeStyle); }},
    measureText() {{ return {{ width: 20 }}; }},
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textBaseline: '', globalAlpha: 1,
  }},
  frameIdx: 2, xOffset: 1080, width: 1080, height: 1920,
}});
assert.ok(strokeColors.includes('#ffb454'));
assert.ok(strokeColors.includes('#ff5d7a'));

// drawOverlay ignores non-finite/null frameIdx without coercing null -> 0
const nullFrameStrokes = [];
overlayDrawerFn({{
  ctx: {{
    save() {{}}, restore() {{}}, fillRect() {{}}, fillText() {{}},
    strokeRect() {{ nullFrameStrokes.push(this.strokeStyle); }},
    measureText() {{ return {{ width: 20 }}; }},
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textBaseline: '', globalAlpha: 1,
  }},
  frameIdx: null, xOffset: 0, width: 1080, height: 1920,
}});
assert.ok(!nullFrameStrokes.includes('#ffb454'));

aEls.noteInput.value = 'Adjust timing';
await ann.saveNote();
assert.equal(aEls.notesList.children.length, 2);
// Clicking a note card pauses playback and seeks to the note's frame
tl.play();
assert.equal(tl.getState().playing, true);
aEls.notesList.children[0].dispatchEvent({{ type: 'click' }});
assert.equal(tl.getState().playing, false);
assert.equal(tl.getState().currentFrame, 2);

await ann.copyRevisionPrompt();
assert.equal(copiedLog.length, 1);
assert.ok(copiedLog[0].includes('.kinearc_analysis/selection.json'));

const tabBtns = ['notes', 'qa', 'audio'].map((t) => {{
  const b = makeEl('button');
  b.dataset.tab = t;
  return b;
}});
const dEls = {{
  workspace: makeEl('main', 'workspace'),
  rightDrawer: makeEl('aside', 'rightDrawer'),
  btnToggleDrawer: makeEl('button', 'btnToggleDrawer'),
  btnTopExport: makeEl('button', 'btnTopExport'),
  tabNotes: makeEl('section', 'tab-notes'),
  tabQa: makeEl('section', 'tab-qa'),
  tabAudio: makeEl('section', 'tab-audio'),
  qaSummary: makeEl('div', 'qaSummary'),
  loopBadge: makeEl('div', 'loopBadge'),
  worstFramesList: makeEl('div', 'worstFramesList'),
  sceneCutsList: makeEl('div', 'sceneCutsList'),
  audioControlsMount: makeEl('div', 'audioControlsMount'),
  exportControlsMount: makeEl('div', 'exportControlsMount'),
}};
for (const k of Object.keys(dEls)) dEls[k].ownerDocument = doc;
dEls.rightDrawer.querySelectorAll = () => tabBtns;
const drw = createDrawer({{
  info: {{}},
  stage: mockStage,
  timeline: tl,
  onToast: (m, k) => toasts.push({{ m, k }}),
  elements: dEls,
}});
assert.ok(dEls.qaSummary.children.some((c) => c.textContent.includes('No QA report loaded')));
assert.equal(dEls.btnToggleDrawer.classList.contains('active'), true);
dEls.btnToggleDrawer.dispatchEvent({{ type: 'click' }});
assert.equal(dEls.workspace.classList.contains('drawer-collapsed'), true);
assert.equal(dEls.rightDrawer.classList.contains('collapsed'), true);
assert.equal(dEls.btnToggleDrawer.classList.contains('active'), false);
dEls.btnTopExport.dispatchEvent({{ type: 'click' }});
assert.equal(drw.isCollapsed(), false);
assert.equal(drw.getActiveTab(), 'audio');
assert.equal(dEls.btnToggleDrawer.classList.contains('active'), true);

// Active export preset persists across setInfo()
const btn4k = findById(dEls.exportControlsMount, 'btnExport4K');
assert.ok(btn4k);
await btn4k.dispatchEvent({{ type: 'click' }});
drw.setInfo({{ width: 1080, height: 1920, fps: 60 }});
const hintBoxEl = findById(dEls.exportControlsMount, 'exportHintBox');
assert.ok(hintBoxEl && hintBoxEl.textContent.includes('4K 60fps'));

// Empty fade-out input falls back to 1.5s & triggers 400 error toast cleanly
const fadeInputEl = findById(dEls.audioControlsMount, 'audioFadeOut');
assert.ok(fadeInputEl);
fadeInputEl.value = '';
const btnMix = findById(dEls.audioControlsMount, 'btnAudioMix');
assert.ok(btnMix);
await btnMix.dispatchEvent({{ type: 'click' }});
await new Promise((r) => setTimeout(r, 10));
assert.equal(lastMixPayload.fade_out, 1.5);
assert.ok(toasts.some((t) => t.k === 'error' && t.m.includes('No audio sources specified')));

// Silent MP4 / explicit false audio flags must NOT trigger /api/audio-peaks fetches
fetchUrls.length = 0;
tl.setInfo({{
  fps: 30, total_frames: 30, duration_sec: 1.0, has_video: true,
  audio: {{ voice: false, bgm: false, sfx: false, video: false }},
}});
await new Promise((r) => setTimeout(r, 10));
assert.equal(fetchUrls.filter((u) => u.includes('/api/audio-peaks')).length, 0);

tl.destroy();
ann.destroy();
drw.destroy();

// 8c. Drawer live /api/render + polling + Open in Stage / Diff + destroy timer cleanup
const renderCalls = [];
let pollStep = 0;
let reloadCalls = [];
const prevFetch = globalThis.fetch;
globalThis.fetch = async (url, opts = {{}}) => {{
  renderCalls.push({{ url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null }});
  if (url === '/api/render' && opts.method === 'POST') {{
    const body = JSON.parse(opts.body);
    return {{
      ok: true,
      status: 202,
      async json() {{
        return {{ ok: true, job_id: body.mode === 'stills' ? 'stilljob1' : 'mp4job1', status: 'running', mode: body.mode, scale: body.scale }};
      }},
    }};
  }}
  if (url === '/api/render/mp4job1') {{
    pollStep += 1;
    if (pollStep === 1) {{
      return {{
        ok: true, status: 200,
        async json() {{ return {{ job_id: 'mp4job1', mode: 'mp4', status: 'running', frame: 4, total: 8, progress: 50.0 }}; }},
      }};
    }}
    return {{
      ok: true, status: 200,
      async json() {{ return {{ job_id: 'mp4job1', mode: 'mp4', status: 'done', frame: 8, total: 8, progress: 100.0, out: 'renders/render_mp4job1.mp4', url: '/renders/render_mp4job1.mp4' }}; }},
    }};
  }}
  if (url === '/api/render/stilljob1') {{
    return {{
      ok: true, status: 200,
      async json() {{
        return {{
          job_id: 'stilljob1', mode: 'stills', status: 'done', frame: 1, total: 1, progress: 100.0,
          out: 'renders/stills_stilljob1/still_0_0s.png', url: '/renders/stills_stilljob1/still_0_0s.png',
          stills: [
            {{ out: 'renders/stills_stilljob1/still_0_0s.png', url: '/renders/stills_stilljob1/still_0_0s.png' }},
            {{ out: 'bad', url: '//evil.test/steal.png' }},
            {{ out: 'bad2', url: 'javascript:alert(1)' }},
            {{ out: 'bad3', url: '/\\\\evil.test/steal.png' }},
          ],
        }};
      }},
    }};
  }}
  if (url === '/api/render/load' && opts.method === 'POST') {{
    return {{
      ok: true, status: 200,
      async json() {{
        return {{ ok: true, info: {{ width: 1920, height: 1080, fps: 60, totalFrames: 8, total_frames: 8, has_video: true, has_ref: false, has_live_scene: true, has_render_engine: true }} }};
      }},
    }};
  }}
  return prevFetch(url, opts);
}};

const dElsLive = {{
  workspace: makeEl('main', 'workspaceLive'),
  rightDrawer: makeEl('aside', 'rightDrawerLive'),
  btnToggleDrawer: makeEl('button', 'btnToggleDrawerLive'),
  btnTopExport: makeEl('button', 'btnTopExportLive'),
  tabNotes: makeEl('section', 'tab-notes-live'),
  tabQa: makeEl('section', 'tab-qa-live'),
  tabAudio: makeEl('section', 'tab-audio-live'),
  qaSummary: makeEl('div', 'qaSummaryLive'),
  loopBadge: makeEl('div', 'loopBadgeLive'),
  worstFramesList: makeEl('div', 'worstFramesListLive'),
  sceneCutsList: makeEl('div', 'sceneCutsListLive'),
  audioControlsMount: makeEl('div', 'audioControlsMountLive'),
  exportControlsMount: makeEl('div', 'exportControlsMountLive'),
}};
for (const k of Object.keys(dElsLive)) dElsLive[k].ownerDocument = doc;
dElsLive.rightDrawer.querySelectorAll = () => tabBtns;
const liveToasts = [];
const drwLive = createDrawer({{
  info: {{ width: 1920, height: 1080, fps: 60, has_live_scene: true, has_render_engine: true }},
  stage: mockStage,
  timeline: tl,
  onStageReload: (nextInfo) => reloadCalls.push(nextInfo),
  onToast: (m, k) => liveToasts.push({{ m, k }}),
  elements: dElsLive,
}});

const btnLive4K = findById(dElsLive.exportControlsMount, 'btnExport4K');
const progressWrapEl = findById(dElsLive.exportControlsMount, 'renderProgressWrap');
const progressBarEl = findById(dElsLive.exportControlsMount, 'renderProgressBar');
const statusTextEl = findById(dElsLive.exportControlsMount, 'renderStatusText');
const btnOpenVidEl = findById(dElsLive.exportControlsMount, 'btnOpenRenderedVideo');
const resultLinksEl = findById(dElsLive.exportControlsMount, 'renderResultLinks');
assert.ok(btnLive4K && progressWrapEl && progressBarEl && statusTextEl && btnOpenVidEl && resultLinksEl);
assert.equal(btnOpenVidEl.classList.contains('hidden'), true);

await btnLive4K.dispatchEvent({{ type: 'click' }});
await new Promise((r) => setTimeout(r, 320));
assert.ok(statusTextEl.textContent.includes('4/8 (50%)'));
assert.equal(progressBarEl.style.width, '50.0%');
await new Promise((r) => setTimeout(r, 320));
assert.equal(progressBarEl.style.width, '100.0%');
assert.equal(btnOpenVidEl.classList.contains('hidden'), false);
assert.ok(liveToasts.some((t) => t.k === 'ok' && t.m.includes('Render complete')));

await btnOpenVidEl.dispatchEvent({{ type: 'click' }});
await new Promise((r) => setTimeout(r, 20));
assert.equal(reloadCalls.length, 1);
assert.equal(reloadCalls[0].has_video, true);

const btnLiveStill = findById(dElsLive.exportControlsMount, 'btnExportStill');
await btnLiveStill.dispatchEvent({{ type: 'click' }});
await new Promise((r) => setTimeout(r, 320));
assert.equal(resultLinksEl.classList.contains('hidden'), false);
assert.equal(resultLinksEl.children.length, 1);
assert.equal(resultLinksEl.children[0].children[0].href, '/renders/stills_stilljob1/still_0_0s.png');

// Destroy clears pending poll timer and aborts in-flight /api/render/load reload callback
pollStep = 0;
const countBeforeDestroy = renderCalls.length;
await btnLive4K.dispatchEvent({{ type: 'click' }});
drwLive.destroy();
const countAtDestroy = renderCalls.length;
await new Promise((r) => setTimeout(r, 350));
assert.equal(renderCalls.length, countAtDestroy);
assert.ok(countAtDestroy >= countBeforeDestroy + 1);
btnOpenVidEl.dispatchEvent({{ type: 'click' }});
assert.equal(reloadCalls.length, 1);
globalThis.fetch = prevFetch;

// 8b. MP4 Playback Seek Coalescing (prevents frame-fetch starvation while keeping Live smooth)
let fakeNow = 1000;
const origPerf = globalThis.performance;
const origRaf = globalThis.requestAnimationFrame;
const origCaf = globalThis.cancelAnimationFrame;
const rafQueue = [];
let rafSeq = 0;
globalThis.performance = {{ now: () => fakeNow }};
globalThis.requestAnimationFrame = (fn) => {{
  const id = ++rafSeq;
  rafQueue.push({{ id, fn }});
  return id;
}};
globalThis.cancelAnimationFrame = (id) => {{
  const idx = rafQueue.findIndex((x) => x.id === id);
  if (idx >= 0) rafQueue.splice(idx, 1);
}};

const coalesceLog = [];
const seekResolvers = [];
const pendingStage = {{
  mode: 'clone',
  seekTime(t, f) {{
    coalesceLog.push({{ t, f, mode: this.mode }});
    return new Promise((resolve) => {{ seekResolvers.push(resolve); }});
  }},
  getState() {{ return {{ mode: this.mode, fps: 30, totalFrames: 60, durationSec: 2.0, currentFrameIdx: 0, currentTimeSec: 0 }}; }},
}};

const tEls2 = {{
  btnPlay: makeEl('button', 'btnPlay2'),
  btnPrev1: makeEl('button', 'btnPrev1_2'),
  btnNext1: makeEl('button', 'btnNext1_2'),
  btnPrev10: makeEl('button', 'btnPrev10_2'),
  btnNext10: makeEl('button', 'btnNext10_2'),
  scrubber: makeEl('input', 'scrubber2'),
  playheadLine: makeEl('div', 'playheadLine2'),
  timecodeReadout: makeEl('div', 'timecodeReadout2'),
  loopStatusPill: makeEl('span', 'loopStatusPill2'),
  timelineTrack: makeEl('div', 'timelineTrack2'),
  waveformCanvas: makeEl('canvas', 'waveformCanvas2'),
  markersLayer: makeEl('div', 'markersLayer2'),
}};
tEls2.markersLayer.ownerDocument = doc;
tEls2.waveformCanvas.getContext = () => ({{ clearRect() {{}}, fillRect() {{}}, fillStyle: '' }});

const tl2 = createTimeline({{
  stage: pendingStage,
  info: {{ fps: 30, total_frames: 60, duration_sec: 2.0, audio: {{ voice: false, bgm: false, video: false }} }},
  elements: tEls2,
}});

tl2.play();
assert.equal(rafQueue.length, 1);
// Tick 1: advances to f1 and issues first fetch (stays pending)
fakeNow = 1040;
rafQueue.shift().fn(fakeNow);
assert.equal(tl2.getState().currentFrame, 1);
assert.equal(coalesceLog.length, 1);
assert.equal(coalesceLog[0].f, 1);

// Tick 2 & Tick 3 while seek 1 is STILL pending: time/frame advance smoothly, zero overlapping seekTime calls!
fakeNow = 1080;
rafQueue.shift().fn(fakeNow);
assert.equal(tl2.getState().currentFrame, 2);
assert.equal(coalesceLog.length, 1);

fakeNow = 1120;
rafQueue.shift().fn(fakeNow);
assert.equal(tl2.getState().currentFrame, 3);
assert.equal(coalesceLog.length, 1);

// Resolving seek 1 immediately catches up to latest frame (f3), coalescing skipped f2!
seekResolvers.shift()();
await Promise.resolve();
await Promise.resolve();
await Promise.resolve();
assert.equal(coalesceLog.length, 2);
assert.equal(coalesceLog[1].f, 3);

// Tick 4 while seek 2 (f3) is pending advances to f4 without overlapping seekTime
fakeNow = 1160;
rafQueue.shift().fn(fakeNow);
assert.equal(tl2.getState().currentFrame, 4);
assert.equal(coalesceLog.length, 2);

// Resolving seek 2 catches up to f4
seekResolvers.shift()();
await Promise.resolve();
await Promise.resolve();
await Promise.resolve();
assert.equal(coalesceLog.length, 3);
assert.equal(coalesceLog[2].f, 4);

// Resolving seek 3 leaves queue idle until next frame tick
seekResolvers.shift()();
await Promise.resolve();
await Promise.resolve();

// Live mode continues seeking smoothly on every tick without coalescing
pendingStage.mode = 'live';
fakeNow = 1200;
rafQueue.shift().fn(fakeNow);
fakeNow = 1240;
rafQueue.shift().fn(fakeNow);
assert.equal(coalesceLog.length, 5);
while (seekResolvers.length) seekResolvers.shift()();

// Manual seek while MP4 playback seek is pending immediately dispatches & invalidates stale promise
pendingStage.mode = 'clone';
fakeNow = 1280;
rafQueue.shift().fn(fakeNow);
assert.equal(coalesceLog.length, 6);
const staleResolver = seekResolvers.shift();
tl2.seekToFrame(20);
assert.equal(coalesceLog.length, 7);
assert.equal(coalesceLog[6].f, 20);
staleResolver();
await Promise.resolve();
await Promise.resolve();
assert.equal(coalesceLog.length, 7);

tl2.destroy();
while (seekResolvers.length) seekResolvers.shift()();
globalThis.performance = origPerf;
globalThis.requestAnimationFrame = origRaf;
globalThis.cancelAnimationFrame = origCaf;

// 9. app.js bootstrap() graceful error toast when /api/info fails
const toastEl = makeEl('div', 'toastContainer');
toastEl.ownerDocument = doc;
globalThis.document = {{
  readyState: 'loading',
  addEventListener() {{}},
  getElementById(id) {{ return id === 'toastContainer' ? toastEl : null; }},
  createElement(tag) {{ return doc.createElement(tag); }},
}};
globalThis.window.__kinearcStage = mockStage;
globalThis.fetch = async () => ({{ ok: false, status: 503, async json() {{ return {{}}; }} }});
const {{ bootstrap }} = await import({json.dumps(app_uri)});
const appRes = await bootstrap();
assert.equal(appRes, null);
assert.equal(toastEl.children.length, 1);
assert.equal(toastEl.children[0].classList.contains('error'), true);
assert.ok(toastEl.children[0].textContent.includes('503'));

console.log('NODE_UNIT_ALL_OK');
"""

    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Node unit tests failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert "NODE_UNIT_ALL_OK" in proc.stdout


def test_full_stack_http_roundtrip_fixture_a_and_b(tmp_path: Path) -> None:
    import kinearc_ui

    # Fixture A: MP4 + ref + WAV + Live scene + sidecars
    state_a, out_dir_a = _build_fixture_a(tmp_path / "fix_a")
    with _running_server(state_a) as (base_url, _port):
        st_root, hdr_root, body_root = _http_request(f"{base_url}/")
        assert st_root == 200
        assert "text/html" in hdr_root.get("Content-Type", "")
        assert "<title>kinearc</title>" in body_root.decode("utf-8")

        for mod in UI_JS_MODULES:
            st_js, hdr_js, body_js = _http_request(f"{base_url}/ui/{mod}")
            assert st_js == 200, f"Failed serving /ui/{mod}"
            assert "javascript" in hdr_js.get("Content-Type", "")
            assert len(body_js) > 50

        st_css, hdr_css, body_css = _http_request(f"{base_url}/ui/styles.css")
        assert st_css == 200
        assert "text/css" in hdr_css.get("Content-Type", "")
        assert ".marker-worst" in body_css.decode("utf-8")

        st_info, _, raw_info = _http_request(f"{base_url}/api/info")
        assert st_info == 200
        info = json.loads(raw_info.decode("utf-8"))
        assert info["has_video"] is True and info["has_live_scene"] is True
        assert len(info["scene_cuts"]) == 1
        assert len(info["worst_frames"]) == 2
        assert len(info["sfx_cues"]) == 1

        st_pk, _, raw_pk = _http_request(f"{base_url}/api/audio-peaks?track=voice&bins=600")
        assert st_pk == 200
        peaks = json.loads(raw_pk.decode("utf-8"))
        assert len(peaks["bins"]) == 600
        assert all(isinstance(x, float) and 0.0 <= x <= 1.0 for x in peaks["bins"])

        st_note, _, raw_note = _http_request(
            f"{base_url}/api/notes",
            method="POST",
            json_body={"frame": 2, "bbox": [10, 20, 80, 90], "text": "Fix alignment"},
        )
        assert st_note == 201
        note = json.loads(raw_note.decode("utf-8"))
        assert note["image"] == "selection/note_1.png"
        assert (out_dir_a / "selection" / "note_1.png").is_file()

        st_cp, _, raw_cp = _http_request(
            f"{base_url}/api/audio/cut-pauses",
            method="POST",
            json_body={"track": "voice", "threshold": -32.0, "min_silence": 0.4, "pad": 0.05},
        )
        assert st_cp == 200
        cp = json.loads(raw_cp.decode("utf-8"))
        assert cp["ok"] is True and len(cp["keep_segments"]) == 2

        st_bad, _, raw_bad = _http_request(
            f"{base_url}/api/audio/mix",
            method="POST",
            json_body={"voice": str(tmp_path / "does_not_exist.wav")},
        )
        assert st_bad == 400
        assert "error" in json.loads(raw_bad.decode("utf-8"))

        st_mix, _, raw_mix = _http_request(
            f"{base_url}/api/audio/mix",
            method="POST",
            json_body={"voice_vol": 1.0, "bgm_vol": 0.35, "fade_out": 0.1},
        )
        assert st_mix == 200
        mix = json.loads(raw_mix.decode("utf-8"))
        assert mix["ok"] is True
        assert (out_dir_a / mix["out"]).is_file()

    # Fixture B: MP4-only with no ref, no sidecars, no audio
    fix_b = tmp_path / "fix_b"
    fix_b.mkdir(parents=True, exist_ok=True)
    mp4_only = fix_b / "plain.mp4"
    _write_mp4(mp4_only, [np.full((120, 160, 3), (30, 60, 90), dtype=np.uint8) for _ in range(5)], fps=30.0)
    state_b = kinearc_ui.UiState(clone_path=str(mp4_only), out_dir=str(fix_b / ".kinearc_analysis"))

    with _running_server(state_b) as (base_url_b, _port_b):
        st_root_b, _, _ = _http_request(f"{base_url_b}/")
        assert st_root_b == 200
        st_info_b, _, raw_info_b = _http_request(f"{base_url_b}/api/info")
        assert st_info_b == 200
        info_b = json.loads(raw_info_b.decode("utf-8"))
        assert info_b["has_video"] is True
        assert info_b["has_ref"] is False
        assert info_b["has_live_scene"] is False
        assert info_b["scene_cuts"] == []
        assert info_b["worst_frames"] == []
        assert info_b["sfx_cues"] == []
        assert info_b["audio"]["voice"] is False
        assert info_b["audio"]["bgm"] is False

        st_notes_b, _, raw_notes_b = _http_request(f"{base_url_b}/api/notes")
        assert st_notes_b == 200
        assert json.loads(raw_notes_b.decode("utf-8")) == []

        st_pk_b, _, _ = _http_request(f"{base_url_b}/api/audio-peaks?track=voice&bins=600")
        assert st_pk_b == 404


def test_headless_browser_e2e_populated_and_empty_states(tmp_path: Path) -> None:
    import kinearc_cli

    discovered = kinearc_cli.find_browser_executable()
    browser = Path(discovered) if discovered else None
    if browser is None or not browser.is_file():
        pytest.skip("No local Chrome/Edge binary found for headless E2E browser smoke check")

    import kinearc_ui

    def run_dump_dom(url: str, profile_name: str) -> str:
        profile_dir = tmp_path / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                f"--user-data-dir={profile_dir}",
                "--virtual-time-budget=2500",
                "--dump-dom",
                url,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            check=False,
        )
        assert proc.returncode == 0, f"Headless browser failed:\n{proc.stderr}"
        return proc.stdout

    # 1. Fixture A (Full MP4 + WAV + Live Scene + Sidecars + saved note)
    state_a, _ = _build_fixture_a(tmp_path / "browser_fix_a")
    with _running_server(state_a) as (base_url, _port):
        st_n, _, _ = _http_request(
            f"{base_url}/api/notes",
            method="POST",
            json_body={"frame": 2, "point": [80, 60], "text": "Verify curve easing"},
        )
        assert st_n == 201
        dom_a = run_dump_dom(base_url, "profile_a")
        assert "<title>kinearc</title>" in dom_a
        assert "320×240 · 30fps · 10f" in dom_a
        assert "00:00.00 / 00:00.33 · f0" in dom_a
        assert "Loop MAE 2.35 (clean)" in dom_a
        assert 'data-marker-kind="cut"' in dom_a
        assert 'data-marker-kind="worst"' in dom_a
        assert 'data-marker-kind="sfx"' in dom_a
        assert "Verify curve easing" in dom_a
        assert "7.42" in dom_a
        assert "28.90 dB" in dom_a
        assert "/cuts/cut_0000.png" in dom_a
        assert 'id="btnCutPauses"' in dom_a
        assert 'id="btnAudioMix"' in dom_a
        assert 'id="btnExport4K"' in dom_a
        assert 'toast error' not in dom_a

    # 2. Fixture B (MP4-only empty state)
    fix_b = tmp_path / "browser_fix_b"
    fix_b.mkdir(parents=True, exist_ok=True)
    mp4_only = fix_b / "plain.mp4"
    _write_mp4(mp4_only, [np.full((120, 160, 3), (40, 50, 60), dtype=np.uint8) for _ in range(6)], fps=30.0)
    state_b = kinearc_ui.UiState(clone_path=str(mp4_only), out_dir=str(fix_b / ".kinearc_analysis"))
    with _running_server(state_b) as (base_url_b, _port_b):
        dom_b = run_dump_dom(base_url_b, "profile_b")
        assert "<title>kinearc</title>" in dom_b
        assert "160×120 · 30fps · 6f" in dom_b
        assert "No QA report loaded" in dom_b
        assert "No revision notes yet" in dom_b
        assert 'id="loopStatusPill" class="loop-status-pill tabular hidden"' in dom_b
        assert 'toast error' not in dom_b

    # 3. Fixture C (Live HTML scene only — verifies kinearc:sceneready updates timeline)
    fix_c = tmp_path / "browser_fix_c"
    scenes_c = fix_c / "scenes"
    scenes_c.mkdir(parents=True, exist_ok=True)
    scene_c = scenes_c / "01.html"
    scene_c.write_text(
        "<!doctype html><html><body><script>"
        "window.kinearc = { totalDuration: 2.5, ready: Promise.resolve(), seek(t) {} };"
        "</script></body></html>",
        encoding="utf-8",
    )
    state_c = kinearc_ui.UiState(scene_path=str(scene_c), out_dir=str(fix_c / ".kinearc_analysis"))
    with _running_server(state_c) as (base_url_c, _port_c):
        dom_c = run_dump_dom(base_url_c, "profile_c")
        assert "<title>kinearc</title>" in dom_c
        assert "1920×1080 · 30fps · 75f" in dom_c
        assert "00:02.50" in dom_c
        assert 'toast error' not in dom_c
