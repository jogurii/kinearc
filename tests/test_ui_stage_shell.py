import json
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
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


def _http_get(url: str):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()), err.read()


def test_ui_files_exist_zero_forbidden_terms_and_exact_dom_slots() -> None:
    index_path = UI_DIR / "index.html"
    css_path = UI_DIR / "styles.css"
    stage_path = UI_DIR / "stage.js"

    for asset in (index_path, css_path, stage_path):
        assert asset.is_file(), f"Missing Task 2 UI asset: {asset}"

    patterns = [
        ("legacy_engine", re.compile(re.escape(FORBIDDEN_LEGACY_ENGINE), re.IGNORECASE)),
        ("old_brand", re.compile(re.escape(FORBIDDEN_OLD_BRAND), re.IGNORECASE)),
        ("forbidden_word", re.compile(re.escape(FORBIDDEN_TONE_WORD), re.IGNORECASE)),
    ]
    hits: list[str] = []
    for asset in (index_path, css_path, stage_path):
        content = asset.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            for label, pat in patterns:
                if pat.search(line):
                    hits.append(f"{asset.name}:{line_no} [{label}] -> {line.strip()}")
        # Verify zero external CDN scripts/stylesheets (W3C SVG namespace URI excluded)
        non_ns = content.replace("http://www.w3.org/2000/svg", "")
        assert "https://" not in non_ns and "http://" not in non_ns, f"External URL found in {asset.name}"

    assert hits == [], "Forbidden terms found in scripts/ui/:\n" + "\n".join(hits)

    html = index_path.read_text(encoding="utf-8")
    assert "<title>kinearc</title>" in html

    required_tokens = [
        'class="topbar"',
        'id="metaBadge"',
        'id="sceneSelect"',
        'id="modeTabs"',
        'data-mode="live"',
        'data-mode="clone"',
        'data-mode="sbs"',
        'data-mode="split"',
        'data-mode="onion"',
        'data-mode="diff"',
        'id="splitControl"',
        'id="safeZoneSelect"',
        'value="none"',
        'value="9:16"',
        'value="16:9"',
        'value="1:1"',
        'value="thirds"',
        'id="btnLoupe"',
        'id="btnToggleDrawer"',
        'id="btnCopyPrompt"',
        'id="btnTopExport"',
        'class="workspace"',
        'id="stagePane"',
        'id="stageWrap"',
        'id="liveFrame"',
        'id="stageCanvas"',
        'id="safeZoneOverlay"',
        'id="overlayCanvas"',
        'id="loupeLens"',
        'id="loupeCanvas"',
        'id="stageEmpty"',
        'id="rightDrawer"',
        'data-tab="notes"',
        'data-tab="qa"',
        'data-tab="audio"',
        'id="tab-notes"',
        'id="selectionTarget"',
        'id="noteInput"',
        'id="btnSaveNote"',
        'id="btnClearSel"',
        'id="notesList"',
        'id="btnCopyRevision"',
        'id="tab-qa"',
        'id="qaSummary"',
        'id="loopBadge"',
        'id="worstFramesList"',
        'id="sceneCutsList"',
        'id="tab-audio"',
        'id="audioControlsMount"',
        'id="exportControlsMount"',
        'id="timelineDock"',
        'id="btnPlay"',
        'id="btnPrev1"',
        'id="btnNext1"',
        'id="btnPrev10"',
        'id="btnNext10"',
        'id="timecodeReadout"',
        'id="loopStatusPill"',
        'id="timelineTrack"',
        'id="waveformCanvas"',
        'id="markersLayer"',
        'id="scrubber"',
        'id="playheadLine"',
        'src="/ui/stage.js"',
        'src="/ui/app.js"',
    ]
    for token in required_tokens:
        assert token in html, f"index.html missing expected token: {token}"

    css = css_path.read_text(encoding="utf-8")
    for color_token in ("#0b0d13", "#12151f", "#191d2b", "#262b3d", "#eceff7", "#8b93ad", "#6c8cff", "tabular-nums"):
        assert color_token in css, f"styles.css missing design token: {color_token}"


def test_http_serving_and_mime_types_without_app_js(tmp_path: Path) -> None:
    import kinearc_ui

    clone_mp4 = tmp_path / "clone.mp4"
    ref_mp4 = tmp_path / "ref.mp4"
    _write_mp4(clone_mp4, [np.full((120, 160, 3), (40, 80, 160), dtype=np.uint8) for _ in range(4)], fps=30.0)
    _write_mp4(ref_mp4, [np.full((120, 160, 3), (30, 90, 120), dtype=np.uint8) for _ in range(4)], fps=30.0)

    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    scene_html = scenes_dir / "01.html"
    scene_html.write_text(
        "<!doctype html><html><body><script>window.kinearc = { total: 2.0, ready: Promise.resolve(), seek(t) {} };</script></body></html>",
        encoding="utf-8",
    )

    state = kinearc_ui.UiState(
        clone_path=str(clone_mp4),
        ref_path=str(ref_mp4),
        scene_path=str(scene_html),
        out_dir=str(tmp_path / ".kinearc_analysis"),
    )

    with _running_server(state) as (base_url, _port):
        st_root, hdr_root, body_root = _http_get(f"{base_url}/")
        assert st_root == 200
        assert hdr_root.get("Content-Type", "").startswith("text/html")
        root_html = body_root.decode("utf-8")
        assert "<title>kinearc</title>" in root_html
        assert 'id="stageWrap"' in root_html

        st_css, hdr_css, body_css = _http_get(f"{base_url}/ui/styles.css")
        assert st_css == 200
        assert hdr_css.get("Content-Type", "").startswith("text/css")
        assert "#0b0d13" in body_css.decode("utf-8")

        st_js, hdr_js, body_js = _http_get(f"{base_url}/ui/stage.js")
        assert st_js == 200
        assert hdr_js.get("Content-Type", "").startswith("application/javascript")
        js_src = body_js.decode("utf-8")
        assert "export function createStage" in js_src
        assert "window.__kinearcStage" in js_src

        st_info, _, raw_info = _http_get(f"{base_url}/api/info")
        assert st_info == 200
        info = json.loads(raw_info.decode("utf-8"))
        assert info["has_video"] is True
        assert info["has_ref"] is True
        assert info["has_live_scene"] is True


def test_stage_js_node_syntax_and_behavior(tmp_path: Path) -> None:
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js is required to validate scripts/ui/stage.js"

    stage_path = UI_DIR / "stage.js"
    syntax_proc = subprocess.run(
        [node_bin, "--check", str(stage_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax_proc.returncode == 0, f"node --check failed: {syntax_proc.stderr}"

    # Behavioral ES module verification with mocked DOM, ResizeObserver, fetch, and ImageBitmap
    stage_uri = stage_path.as_uri()
    test_script = rf"""
import assert from 'node:assert/strict';
import {{ createStage }} from {json.dumps(stage_uri)};

class MockClassList {{
  constructor() {{ this.set = new Set(); }}
  add(...names) {{ for (const n of names) this.set.add(n); }}
  remove(...names) {{ for (const n of names) this.set.delete(n); }}
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
    style: {{}},
    classList: new MockClassList(),
    dataset: {{}},
    children: [],
    width: 0,
    height: 0,
    clientWidth: 0,
    clientHeight: 0,
    value: '',
    textContent: '',
    disabled: false,
    ownerDocument: null,
    setAttribute(k, v) {{ attrs[k] = String(v); }},
    getAttribute(k) {{ return attrs[k] ?? null; }},
    removeAttribute(k) {{ delete attrs[k]; }},
    appendChild(child) {{ el.children.push(child); return child; }},
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
      for (const fn of listeners[evt.type] || []) fn(evt);
    }},
    querySelectorAll() {{ return []; }},
    getBoundingClientRect() {{
      return {{
        left: 0,
        top: 0,
        width: parseFloat(el.style.width) || el.clientWidth || 800,
        height: parseFloat(el.style.height) || el.clientHeight || 600,
      }};
    }},
  }};
  return el;
}}

const doc = {{
  createElement(tag) {{
    const el = makeEl(tag);
    el.ownerDocument = doc;
    return el;
  }},
  createElementNS(_ns, tag) {{
    const el = makeEl(tag);
    el.ownerDocument = doc;
    return el;
  }},
}};

const ctxCalls = [];
function makeCtx() {{
  return {{
    save() {{}},
    restore() {{}},
    clearRect() {{}},
    fillRect() {{}},
    strokeRect() {{}},
    beginPath() {{}},
    rect() {{}},
    clip() {{}},
    fillText() {{}},
    measureText(t) {{ return {{ width: String(t).length * 7 }}; }},
    drawImage(...args) {{ ctxCalls.push(args); }},
    globalAlpha: 1,
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    font: '',
    textAlign: '',
    textBaseline: '',
    imageSmoothingEnabled: true,
  }};
}}

const stagePane = makeEl('section', 'stagePane');
stagePane.clientWidth = 1000;
stagePane.clientHeight = 600;
const stageWrap = makeEl('div', 'stageWrap');
const liveFrame = makeEl('iframe', 'liveFrame');
liveFrame.ownerDocument = doc;
const stageCanvas = makeEl('canvas', 'stageCanvas');
stageCanvas.getContext = () => makeCtx();
const overlayCanvas = makeEl('canvas', 'overlayCanvas');
overlayCanvas.getContext = () => makeCtx();
overlayCanvas.getBoundingClientRect = () => stageWrap.getBoundingClientRect();
const safeZoneOverlay = makeEl('svg', 'safeZoneOverlay');
safeZoneOverlay.ownerDocument = doc;
const loupeLens = makeEl('div', 'loupeLens');
const loupeCanvas = makeEl('canvas', 'loupeCanvas');
loupeCanvas.getContext = () => makeCtx();
const loupeBadge = makeEl('div', 'loupeBadge');
const stageEmpty = makeEl('div', 'stageEmpty');
const stageEmptyTitle = makeEl('strong', 'stageEmptyTitle');
const stageEmptyDesc = makeEl('p', 'stageEmptyDesc');
const metaBadge = makeEl('span', 'metaBadge');
const sceneSelect = makeEl('select', 'sceneSelect');
sceneSelect.ownerDocument = doc;
const splitControl = makeEl('div', 'splitControl');
const splitControlLabel = makeEl('span', 'splitControlLabel');
const splitSlider = makeEl('input', 'splitSlider');
const splitValue = makeEl('span', 'splitValue');
const safeZoneSelect = makeEl('select', 'safeZoneSelect');
const btnLoupe = makeEl('button', 'btnLoupe');

const modeButtons = ['live', 'clone', 'sbs', 'split', 'onion', 'diff'].map((m) => {{
  const b = makeEl('button');
  b.dataset.mode = m;
  return b;
}});
const modeTabs = makeEl('div', 'modeTabs');
modeTabs.querySelectorAll = () => modeButtons;

globalThis.window = {{
  devicePixelRatio: 1,
  addEventListener() {{}},
  dispatchEvent() {{}},
}};
globalThis.getComputedStyle = () => ({{ paddingLeft: '20', paddingRight: '20', paddingTop: '20', paddingBottom: '20' }});
globalThis.CustomEvent = class CustomEvent {{ constructor(type, init = {{}}) {{ this.type = type; this.detail = init.detail; }} }};

let abortedCount = 0;
let createdBitmaps = [];
const fetchLog = [];

globalThis.createImageBitmap = async (blob) => {{
  const bmp = {{
    id: createdBitmaps.length + 1,
    srcUrl: blob.url,
    closed: false,
    close() {{ this.closed = true; }},
  }};
  createdBitmaps.push(bmp);
  return bmp;
}};

globalThis.fetch = (url, opts = {{}}) => {{
  fetchLog.push(url);
  if (opts.signal) {{
    opts.signal.addEventListener('abort', () => {{ abortedCount += 1; }});
  }}
  return new Promise((resolve, reject) => {{
    const t = setTimeout(() => {{
      if (opts.signal?.aborted) {{
        const e = new Error('Aborted');
        e.name = 'AbortError';
        reject(e);
        return;
      }}
      resolve({{
        ok: true,
        status: 200,
        async blob() {{ return {{ url }}; }},
      }});
    }}, 25);
    opts.signal?.addEventListener('abort', () => {{
      clearTimeout(t);
      const e = new Error('Aborted');
      e.name = 'AbortError';
      reject(e);
    }});
  }});
}};

const stage = createStage({{
  stagePane, stageWrap, liveFrame, stageCanvas, safeZoneOverlay, overlayCanvas,
  loupeLens, loupeCanvas, loupeBadge, stageEmpty, stageEmptyTitle, stageEmptyDesc,
  metaBadge, sceneSelect, modeTabs, splitControl, splitControlLabel, splitSlider,
  splitValue, safeZoneSelect, btnLoupe,
}});

assert.equal(globalThis.window.__kinearcStage, stage);

// 1. Aspect-ratio fitting across 9:16, 16:9, 1:1, and double-wide sbs (avail = 960 x 560)
const aspectCases = [
  {{ w: 1080, h: 1920, mode: 'clone', expW: 1080, expH: 1920 }},
  {{ w: 1920, h: 1080, mode: 'clone', expW: 1920, expH: 1080 }},
  {{ w: 1080, h: 1080, mode: 'clone', expW: 1080, expH: 1080 }},
  {{ w: 1080, h: 1920, mode: 'sbs',   expW: 2160, expH: 1920 }},
  {{ w: 1920, h: 1080, mode: 'sbs',   expW: 3840, expH: 1080 }},
];

for (const tc of aspectCases) {{
  stage.init({{
    width: tc.w, height: tc.h, fps: 60, total_frames: 60,
    has_video: true, has_ref: true, has_live_scene: false, mode_default: tc.mode,
  }});
  const st = stage.getState();
  assert.equal(st.dispWidth, tc.expW);
  assert.equal(st.dispHeight, tc.expH);
  assert.ok(st.fitWidth > 0 && st.fitWidth <= 960, `fitWidth out of bounds: ${{st.fitWidth}}`);
  assert.ok(st.fitHeight > 0 && st.fitHeight <= 560, `fitHeight out of bounds: ${{st.fitHeight}}`);
  const ratioDiff = Math.abs((st.fitWidth / st.fitHeight) - (tc.expW / tc.expH));
  assert.ok(ratioDiff < 0.01, `Aspect mismatch for ${{tc.w}}x${{tc.h}} ${{tc.mode}}: ${{ratioDiff}}`);
}}

// 2. Mode transitions, canvas width toggling, and splitControl visibility
stage.init({{
  width: 1080, height: 1920, fps: 60, total_frames: 120,
  has_video: true, has_ref: true, has_live_scene: true,
  live_scene_url: '/api/scene/01.html',
  scenes: [
    {{ name: 'Hook', url: '/api/scene/01.html' }},
    {{ name: 'CTA', url: '/api/scene/02.html' }},
  ],
  mode_default: 'live',
}});
assert.equal(sceneSelect.classList.contains('hidden'), false);
assert.equal(liveFrame.classList.contains('is-inactive'), false);
assert.equal(stageCanvas.classList.contains('hidden'), true);

// Test pending seek before liveFrame.onload & ready resolve
const liveSeekCalls = [];
let resolveReady;
const readyPromise = new Promise((res) => {{ resolveReady = res; }});
stage.seekTime(1.25);
assert.equal(liveSeekCalls.length, 0);
liveFrame.contentWindow = {{
  kinearc: {{
    totalDuration: 4.0,
    ready: readyPromise,
    seek(t) {{ liveSeekCalls.push(t); }},
  }},
}};
liveFrame.onload();
await Promise.resolve();
assert.equal(liveSeekCalls.length, 0); // Still waiting for .ready
resolveReady();
await new Promise((r) => setTimeout(r, 5));
assert.deepEqual(liveSeekCalls, [1.25]);

// Fallback renderAt(t) when kinearc.seek is absent + error safety
const fallbackCalls = [];
liveFrame.contentWindow = {{
  renderAt(t) {{
    fallbackCalls.push(t);
    if (t > 2) throw new Error('scene error');
  }},
}};
stage.setScene('/api/scene/02.html');
assert.equal(stage.getState().pendingLiveSeek, null);
stage.seekTime(0.75);
liveFrame.onload();
await new Promise((r) => setTimeout(r, 5));
assert.deepEqual(fallbackCalls, [0.75]);
stage.seekTime(3.0); // Must not throw

// 3. MP4 rapid scrub AbortController + ImageBitmap cleanup
stage.setMode('clone');
assert.equal(liveFrame.classList.contains('is-inactive'), true);
assert.equal(stageCanvas.classList.contains('hidden'), false);
assert.equal(stageCanvas.width, 1080);
assert.equal(splitControl.classList.contains('hidden'), true);

const p1 = stage.seekTime(0, 1);
const p2 = stage.seekTime(0, 2);
const p3 = stage.seekTime(0, 3);
await Promise.all([p1, p2, p3]);
assert.ok(abortedCount >= 2, `Expected >=2 aborted requests, got ${{abortedCount}}`);
assert.ok(createdBitmaps.every((b) => b.closed), 'All clone bitmaps must close after draw/abort');

// Split mode keeps only current frame for interactive split slider, closes on next scrub & destroy
stage.setMode('split');
assert.equal(splitControl.classList.contains('hidden'), false);
await stage.seekTime(0, 5);
const beforeScrubCount = createdBitmaps.length;
stage.setSplitRatio(30);
assert.equal(createdBitmaps.length, beforeScrubCount); // Zero extra fetches during split drag
await stage.seekTime(0, 6);
const openAfterScrub = createdBitmaps.filter((b) => !b.closed);
assert.equal(openAfterScrub.length, 2); // Only current frame's clone + ref held

stage.setMode('sbs');
assert.equal(stageCanvas.width, 2160);
await stage.seekTime(0, 7);
assert.ok(createdBitmaps.every((b) => b.closed), 'All bitmaps closed in sbs mode after draw');

// 4. Safe zones (9:16 exact proportions + labels, 16:9, 1:1, thirds, none)
stage.setMode('clone');
stage.setSafeZone('9:16');
const findRects = (node, out = []) => {{
  if (!node) return out;
  if (node.tagName === 'RECT' && typeof node.getAttribute === 'function') out.push(node);
  for (const c of node.children || []) findRects(c, out);
  return out;
}};
const rects916 = findRects(safeZoneOverlay);
const core916 = rects916.find((r) => r.getAttribute('stroke') === '#ff5d7a');
assert.ok(core916, '9:16 safe core rect missing');
assert.equal(Number(core916.getAttribute('x')), 72);
assert.equal(Number(core916.getAttribute('y')), 220);
assert.equal(Number(core916.getAttribute('width')), 858);
assert.equal(Number(core916.getAttribute('height')), 1340);

const safeSvgJson = JSON.stringify(safeZoneOverlay.children);
for (const label of ['TOP UI', 'ACTIONS', 'CAPTION / CTA', 'SAFE AREA']) {{
  assert.ok(safeSvgJson.includes(label), `9:16 safe zone missing label ${{label}}`);
}}
stage.setSafeZone('16:9');
assert.ok(JSON.stringify(safeZoneOverlay.children).includes('ACTION SAFE 5%'));
stage.setSafeZone('1:1');
assert.ok(JSON.stringify(safeZoneOverlay.children).includes('1:1 CROP'));
stage.setSafeZone('thirds');
assert.ok(safeZoneOverlay.children[0].children.length >= 4);
stage.setSafeZone('none');
assert.equal(safeZoneOverlay.children.length, 0);

// 4b. Diff mode + Onion mode + toFrameCoords in SBS mode
stage.setMode('diff');
await stage.seekTime(0, 4);
assert.ok(fetchLog.some((u) => u.includes('/api/frame?idx=4&kind=diff')));
assert.ok(createdBitmaps.every((b) => b.closed), 'Diff bitmap must close after draw');

stage.setMode('onion');
stage.setSplitRatio(35);
assert.equal(splitControlLabel.textContent, 'Mix');
assert.equal(splitValue.textContent, '35%');
await stage.seekTime(0, 4);

stage.setMode('sbs');
// Right pane (CLONE) maps back to single-frame coords [0..1079]
const [fxR, fyR] = stage.toFrameCoords(600, 300);
assert.ok(fxR >= 0 && fxR < 1080 && fyR >= 0 && fyR < 1920);
btnLoupe.dispatchEvent({{ type: 'click' }});
assert.equal(stage.isLoupeEnabled(), true);
btnLoupe.dispatchEvent({{ type: 'click' }});
assert.equal(stage.isLoupeEnabled(), false);

// 5. Annotations hook + Loupe toggle + Clean destroy
stage.setMode('clone');
let lastOverlayArgs = null;
stage.setAnnotationsDrawer((info) => {{ lastOverlayArgs = info; }});
assert.equal(lastOverlayArgs.width, 1080);
assert.equal(lastOverlayArgs.xOffset, 0);
stage.setMode('sbs');
assert.equal(lastOverlayArgs.xOffset, 1080);

stage.setLoupe(true);
assert.equal(stage.isLoupeEnabled(), true);
assert.equal(btnLoupe.classList.contains('active'), true);
overlayCanvas.dispatchEvent({{ type: 'pointermove', clientX: 120, clientY: 180 }});
assert.equal(loupeLens.classList.contains('hidden'), false);
stage.setLoupe(false);
assert.equal(loupeLens.classList.contains('hidden'), true);

stage.destroy();
assert.ok(createdBitmaps.every((b) => b.closed), 'destroy() closes all bitmaps');
btnLoupe.dispatchEvent({{ type: 'click' }});
assert.equal(stage.isLoupeEnabled(), false, 'destroy() removes #btnLoupe click listener');
console.log('STAGE_JS_BEHAVIOR_OK');
"""

    run_proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", test_script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert run_proc.returncode == 0, f"Node behavioral check failed:\nSTDOUT:\n{run_proc.stdout}\nSTDERR:\n{run_proc.stderr}"
    assert "STAGE_JS_BEHAVIOR_OK" in run_proc.stdout


def test_optional_headless_browser_dom_smoke(tmp_path: Path) -> None:
    """Verify index.html + styles.css + stage.js load cleanly in headless Chromium when installed."""
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    browser = next((p for p in candidates if p.is_file()), None)
    if browser is None:
        pytest.skip("No local Chrome/Edge binary found for optional headless DOM smoke check")

    import kinearc_ui

    scene_dir = tmp_path / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    scene_html = scene_dir / "01.html"
    scene_html.write_text(
        "<!doctype html><html><body><script>window.kinearc={total:1,ready:Promise.resolve(),seek(){}};</script></body></html>",
        encoding="utf-8",
    )
    state = kinearc_ui.UiState(scene_path=str(scene_html), out_dir=str(tmp_path / ".kinearc_analysis"))

    profile_dir = tmp_path / "browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    with _running_server(state) as (base_url, _port):
        proc = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={profile_dir}",
                "--virtual-time-budget=1500",
                "--dump-dom",
                base_url,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        dom = proc.stdout
        assert "<title>kinearc</title>" in dom
        assert 'id="stageWrap"' in dom
        assert 'id="rightDrawer"' in dom
        assert 'id="timelineDock"' in dom
