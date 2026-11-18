/**
 * stage.js — Modular Dual-Viewport Stage Controller for kinearc
 *
 * Manages:
 *  - Aspect-locked stage fitting (#stageWrap inside #stagePane) across 9:16, 16:9, 1:1, and 2W x H sbs
 *  - Live HTML scene iframe driving via window.kinearc.seek(t) / window.renderAt(t)
 *  - MP4 inspection modes (clone, sbs, split, onion, diff) with AbortController fetch cancellation
 *    and immediate/explicit ImageBitmap cleanup
 *  - SVG platform safe-zone overlays (9:16, 16:9, 1:1, thirds, none)
 *  - Interactive 2x optical pixel loupe (#loupeLens + #loupeCanvas)
 *  - Overlay canvas hook for annotations.js (setAnnotationsDrawer)
 */

const VALID_MODES = new Set(["live", "clone", "sbs", "split", "onion", "diff"]);
const VALID_SAFE_ZONES = new Set(["none", "9:16", "16:9", "1:1", "thirds"]);
const SVG_NS = "http://www.w3.org/2000/svg";
const LOUPE_SIZE = 180;

const wrapInstances = typeof WeakMap !== "undefined" ? new WeakMap() : null;

function clamp(val, min, max) {
  return Math.min(max, Math.max(min, val));
}

function closeBitmap(bmp) {
  if (bmp && typeof bmp.close === "function") {
    try {
      bmp.close();
    } catch (_err) {
      // Ignore already-closed bitmaps
    }
  }
}

function resolveElements(overrides = {}) {
  const byId = (id) => (typeof document !== "undefined" ? document.getElementById(id) : null);
  return {
    stagePane: overrides.stagePane ?? byId("stagePane"),
    stageWrap: overrides.stageWrap ?? byId("stageWrap"),
    liveFrame: overrides.liveFrame ?? byId("liveFrame"),
    stageCanvas: overrides.stageCanvas ?? byId("stageCanvas"),
    safeZoneOverlay: overrides.safeZoneOverlay ?? byId("safeZoneOverlay"),
    overlayCanvas: overrides.overlayCanvas ?? byId("overlayCanvas"),
    loupeLens: overrides.loupeLens ?? byId("loupeLens"),
    loupeCanvas: overrides.loupeCanvas ?? byId("loupeCanvas"),
    loupeBadge: overrides.loupeBadge ?? byId("loupeBadge"),
    stageEmpty: overrides.stageEmpty ?? byId("stageEmpty"),
    stageEmptyTitle: overrides.stageEmptyTitle ?? byId("stageEmptyTitle"),
    stageEmptyDesc: overrides.stageEmptyDesc ?? byId("stageEmptyDesc"),
    metaBadge: overrides.metaBadge ?? byId("metaBadge"),
    sceneSelect: overrides.sceneSelect ?? byId("sceneSelect"),
    modeTabs: overrides.modeTabs ?? byId("modeTabs"),
    splitControl: overrides.splitControl ?? byId("splitControl"),
    splitControlLabel: overrides.splitControlLabel ?? byId("splitControlLabel"),
    splitSlider: overrides.splitSlider ?? byId("splitSlider"),
    splitValue: overrides.splitValue ?? byId("splitValue"),
    safeZoneSelect: overrides.safeZoneSelect ?? byId("safeZoneSelect"),
    btnLoupe: overrides.btnLoupe ?? byId("btnLoupe"),
  };
}

function createSvgEl(doc, tag, attrs = {}, text = null) {
  const el = doc.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    el.setAttribute(k, String(v));
  }
  if (text !== null) {
    el.textContent = String(text);
  }
  return el;
}

function formatFpsLabel(fps) {
  const rounded = Math.round(fps * 100) / 100;
  return Number.isInteger(rounded) ? `${rounded}` : rounded.toFixed(1);
}

/**
 * Create a kinearc stage controller bound to DOM elements (defaults to standard IDs).
 */
export function createStage(elements = {}) {
  const els = resolveElements(elements);

  if (wrapInstances && els.stageWrap && wrapInstances.has(els.stageWrap)) {
    try {
      wrapInstances.get(els.stageWrap).destroy();
    } catch (_err) {
      // Ignore cleanup failures from stale instances
    }
  }

  const listenerAbort = typeof AbortController !== "undefined" ? new AbortController() : null;
  const listenerSignal = listenerAbort ? listenerAbort.signal : undefined;

  const state = {
    width: 1920,
    height: 1080,
    fps: 30,
    totalFrames: 0,
    durationSec: 0,
    hasVideo: false,
    hasRef: false,
    hasLive: false,
    scenes: [],
    liveSceneUrl: null,
    mode: "clone",
    splitRatio: 50,
    safeZone: "none",
    loupeEnabled: false,
    currentTimeSec: 0,
    currentFrameIdx: 0,
  };

  const fitMetrics = {
    fitW: 0,
    fitH: 0,
    dispW: 1920,
    dispH: 1080,
    scale: 1,
  };

  let liveFrameLoaded = false;
  let liveFrameReady = false;
  let pendingLiveSeek = null;
  let liveLoadToken = 0;
  let liveSeekToken = 0;

  let activeFetchController = null;
  let fetchSeq = 0;

  // Single-frame bitmap store used solely for interactive Split/Onion slider scrubbing
  let heldBitmaps = {
    frameIdx: -1,
    clone: null,
    ref: null,
  };

  const MAX_FRAME_CACHE = 240;
  const MAX_PREFETCH_CONCURRENCY = 4;
  let frameCacheEnabled = false;
  let isPlaying = false;
  const frameCache = new Map();
  const inflightPrefetch = new Set();
  let prefetchAbort = null;
  let prefetchEpoch = 0;

  let annotationsDrawer = null;
  let resizeObserver = null;
  let destroyed = false;

  const pointer = {
    active: false,
    relX: 0,
    relY: 0,
  };

  function emitEvent(name, detail) {
    if (typeof CustomEvent !== "function") return;
    const evt = new CustomEvent(name, { detail });
    if (els.stageWrap && typeof els.stageWrap.dispatchEvent === "function") {
      els.stageWrap.dispatchEvent(evt);
    }
    if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      window.dispatchEvent(new CustomEvent(name, { detail }));
    }
  }

  function isBitmapInCache(bmp) {
    if (!bmp) return false;
    for (const entry of frameCache.values()) {
      if (entry.clone === bmp || entry.ref === bmp || entry.diff === bmp) {
        return true;
      }
    }
    return false;
  }

  function clearHeldBitmaps() {
    if (!isBitmapInCache(heldBitmaps.clone)) closeBitmap(heldBitmaps.clone);
    if (!isBitmapInCache(heldBitmaps.ref)) closeBitmap(heldBitmaps.ref);
    heldBitmaps.clone = null;
    heldBitmaps.ref = null;
    heldBitmaps.frameIdx = -1;
  }

  function abortPrefetch() {
    prefetchEpoch += 1;
    inflightPrefetch.clear();
    if (prefetchAbort) {
      try {
        prefetchAbort.abort();
      } catch (_err) {
        // Ignore abort errors
      }
      prefetchAbort = null;
    }
  }

  function clearFrameCache() {
    abortPrefetch();
    for (const entry of frameCache.values()) {
      if (entry.clone !== heldBitmaps.clone) closeBitmap(entry.clone);
      if (entry.ref !== heldBitmaps.ref) closeBitmap(entry.ref);
      closeBitmap(entry.diff);
    }
    frameCache.clear();
  }

  function getOrCreateCacheEntry(idx) {
    if (frameCache.has(idx)) {
      const existing = frameCache.get(idx);
      frameCache.delete(idx);
      frameCache.set(idx, existing);
      return existing;
    }
    const created = { clone: null, ref: null, diff: null };
    frameCache.set(idx, created);
    while (frameCache.size > MAX_FRAME_CACHE) {
      const oldestKey = frameCache.keys().next().value;
      if (oldestKey === undefined) break;
      const evicted = frameCache.get(oldestKey);
      frameCache.delete(oldestKey);
      if (evicted) {
        if (evicted.clone !== heldBitmaps.clone) closeBitmap(evicted.clone);
        if (evicted.ref !== heldBitmaps.ref) closeBitmap(evicted.ref);
        closeBitmap(evicted.diff);
      }
    }
    return created;
  }

  function hasCachedFrame(frameIdx, targetMode = state.mode) {
    if (!(frameCacheEnabled || isPlaying) || !state.hasVideo || targetMode === "live") {
      return false;
    }
    const idx = state.totalFrames > 0 ? clamp(Math.round(frameIdx), 0, state.totalFrames - 1) : Math.max(0, Math.round(frameIdx || 0));
    const entry = frameCache.get(idx);
    if (!entry) return false;
    if (targetMode === "diff" && state.hasRef) {
      return Boolean(entry.diff);
    }
    const needRef = state.hasRef && (targetMode === "sbs" || targetMode === "split" || targetMode === "onion");
    return Boolean(entry.clone && (!needRef || entry.ref));
  }

  function abortInFlightFetch() {
    if (activeFetchController) {
      try {
        activeFetchController.abort();
      } catch (_err) {
        // Ignore abort errors
      }
      activeFetchController = null;
    }
  }

  function getDisplayDimensions(targetMode = state.mode) {
    const dispW = targetMode === "sbs" ? state.width * 2 : state.width;
    const dispH = state.height;
    return { dispW: Math.max(1, dispW), dispH: Math.max(1, dispH) };
  }

  function getCanvasContext2D(canvas) {
    if (!canvas || typeof canvas.getContext !== "function") return null;
    return canvas.getContext("2d");
  }

  function updateEmptyBanner() {
    if (!els.stageEmpty) return;
    const missingForMode =
      (state.mode === "live" && !state.hasLive) ||
      (state.mode !== "live" && !state.hasVideo);
    els.stageEmpty.classList.toggle("hidden", !missingForMode);
    if (missingForMode && els.stageEmptyTitle && els.stageEmptyDesc) {
      if (state.mode === "live") {
        els.stageEmptyTitle.textContent = "No live scene loaded";
        els.stageEmptyDesc.textContent = "Provide --scene or a kinearc.project.json manifest with scenes.";
      } else {
        els.stageEmptyTitle.textContent = state.hasLive ? "No rendered MP4 loaded" : "No active viewport source";
        els.stageEmptyDesc.textContent = state.hasLive
          ? "Switch to Live mode above to scrub the active HTML scene."
          : "Launch kinearc_ui.py with an MP4 render, --scene HTML file, or kinearc.project.json.";
      }
    }
  }

  function redrawOverlay() {
    const overlay = els.overlayCanvas;
    if (!overlay) return;
    const ctx = getCanvasContext2D(overlay);
    const { dispW, dispH } = getDisplayDimensions();
    if (ctx) {
      ctx.clearRect(0, 0, overlay.width || dispW, overlay.height || dispH);
    }
    if (typeof annotationsDrawer === "function") {
      try {
        annotationsDrawer({
          ctx,
          canvas: overlay,
          width: state.width,
          height: state.height,
          dispWidth: dispW,
          dispHeight: dispH,
          mode: state.mode,
          xOffset: state.mode === "sbs" ? state.width : 0,
          frameIdx: state.currentFrameIdx,
          timeSec: state.currentTimeSec,
        });
      } catch (_err) {
        // Keep stage rendering resilient if annotation callback throws
      }
    }
  }

  function fitStage() {
    const { dispW, dispH } = getDisplayDimensions();
    fitMetrics.dispW = dispW;
    fitMetrics.dispH = dispH;

    const pane = els.stagePane;
    const wrap = els.stageWrap;
    if (!pane || !wrap) return;

    let padX = 0;
    let padY = 0;
    if (typeof getComputedStyle === "function") {
      try {
        const cs = getComputedStyle(pane);
        padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
        padY = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
      } catch (_err) {
        padX = 0;
        padY = 0;
      }
    }

    const rawW = pane.clientWidth || (typeof pane.getBoundingClientRect === "function" ? pane.getBoundingClientRect().width : 0);
    const rawH = pane.clientHeight || (typeof pane.getBoundingClientRect === "function" ? pane.getBoundingClientRect().height : 0);
    const availW = Math.max(0, rawW - padX);
    const availH = Math.max(0, rawH - padY);
    if (availW <= 0 || availH <= 0) return;

    const scale = Math.min(availW / dispW, availH / dispH);
    const fitW = clamp(Math.floor(dispW * scale), 1, Math.floor(availW));
    const fitH = clamp(Math.floor(dispH * scale), 1, Math.floor(availH));

    fitMetrics.fitW = fitW;
    fitMetrics.fitH = fitH;
    fitMetrics.scale = scale;

    if (wrap.style) {
      wrap.style.width = `${fitW}px`;
      wrap.style.height = `${fitH}px`;
      wrap.style.aspectRatio = `${dispW} / ${dispH}`;
    }

    if (els.liveFrame && els.liveFrame.style) {
      const sx = state.mode === "sbs" ? fitH / Math.max(1, state.height) : fitW / Math.max(1, state.width);
      const sy = fitH / Math.max(1, state.height);
      els.liveFrame.style.width = `${state.width}px`;
      els.liveFrame.style.height = `${state.height}px`;
      els.liveFrame.style.transform = `scale(${sx}, ${sy})`;
      els.liveFrame.style.transformOrigin = "top left";
    }

    redrawOverlay();
    if (state.loupeEnabled && pointer.active) {
      updateLoupeAt(pointer.relX, pointer.relY);
    }
  }

  function syncCanvasAndSvgDimensions() {
    const { dispW, dispH } = getDisplayDimensions();
    if (els.stageCanvas) {
      if (els.stageCanvas.width !== dispW) els.stageCanvas.width = dispW;
      if (els.stageCanvas.height !== dispH) els.stageCanvas.height = dispH;
    }
    if (els.overlayCanvas) {
      if (els.overlayCanvas.width !== dispW) els.overlayCanvas.width = dispW;
      if (els.overlayCanvas.height !== dispH) els.overlayCanvas.height = dispH;
    }
    if (els.safeZoneOverlay) {
      els.safeZoneOverlay.setAttribute("viewBox", `0 0 ${dispW} ${dispH}`);
      els.safeZoneOverlay.setAttribute("preserveAspectRatio", "none");
    }
  }

  function renderSafeZone() {
    const svg = els.safeZoneOverlay;
    if (!svg) return;

    const { dispW, dispH } = getDisplayDimensions();
    svg.setAttribute("viewBox", `0 0 ${dispW} ${dispH}`);
    svg.setAttribute("preserveAspectRatio", "none");
    if (typeof svg.replaceChildren === "function") {
      svg.replaceChildren();
    } else {
      svg.innerHTML = "";
    }

    if (state.safeZone === "none") return;

    const doc = svg.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!doc || typeof doc.createElementNS !== "function") return;

    const W = Math.max(1, state.width);
    const H = Math.max(1, state.height);
    const xOffsets = state.mode === "sbs" ? [0, W] : [0];
    const strokeUnit = Math.max(1.5, Math.min(W, H) * 0.0022);
    const fontSize = Math.max(11, Math.round(Math.min(W, H) * 0.022));
    const dashLong = `${Math.round(strokeUnit * 5)} ${Math.round(strokeUnit * 3)}`;

    const addLabel = (parent, x, y, text, opts = {}) => {
      const anchor = opts.anchor || "middle";
      const fill = opts.fill || "#eceff7";
      const rotate = opts.rotate ? ` rotate(${opts.rotate} ${x} ${y})` : "";
      const txt = createSvgEl(
        doc,
        "text",
        {
          x,
          y,
          fill,
          "font-size": opts.fontSize || fontSize,
          "font-weight": "700",
          "font-family": 'ui-monospace, "SFMono-Regular", Menlo, monospace',
          "letter-spacing": "0.06em",
          "text-anchor": anchor,
          "dominant-baseline": "middle",
          "paint-order": "stroke",
          stroke: "rgba(11, 13, 19, 0.88)",
          "stroke-width": Math.max(2, strokeUnit * 1.6),
          "stroke-linejoin": "round",
          ...(rotate ? { transform: rotate.trim() } : {}),
        },
        text
      );
      parent.appendChild(txt);
    };

    for (const xOff of xOffsets) {
      const g = createSvgEl(doc, "g", { "data-pane-offset": xOff });

      if (state.safeZone === "9:16") {
        const targetAspect = 9 / 16;
        let fw = W;
        let fh = H;
        if (W / H > targetAspect) {
          fh = H;
          fw = H * targetAspect;
        } else {
          fw = W;
          fh = W / targetAspect;
        }
        const fx = xOff + (W - fw) / 2;
        const fy = (H - fh) / 2;

        // Exact 1080x1920 UI safe box proportions: x [72..930], y [220..1560]
        const left = fw * (72 / 1080);
        const right = fw * (150 / 1080);
        const top = fh * (220 / 1920);
        const bottom = fh * (360 / 1920);

        const sx = fx + left;
        const sy = fy + top;
        const sw = Math.max(1, fw - left - right);
        const sh = Math.max(1, fh - top - bottom);

        // Dim sidebars if canvas is wider/taller than 9:16
        if (fw < W - 0.5 || fh < H - 0.5) {
          const cropMask = `M ${xOff} 0 H ${xOff + W} V ${H} H ${xOff} Z M ${fx} ${fy} V ${fy + fh} H ${fx + fw} V ${fy} Z`;
          g.appendChild(
            createSvgEl(doc, "path", {
              d: cropMask,
              fill: "rgba(11, 13, 19, 0.45)",
              "fill-rule": "evenodd",
            })
          );
          g.appendChild(
            createSvgEl(doc, "rect", {
              x: fx,
              y: fy,
              width: fw,
              height: fh,
              fill: "none",
              stroke: "rgba(108, 140, 255, 0.78)",
              "stroke-width": strokeUnit,
              "stroke-dasharray": dashLong,
            })
          );
        }

        // Translucent danger perimeter tint around safe core box
        const hazardMask = `M ${fx} ${fy} H ${fx + fw} V ${fy + fh} H ${fx} Z M ${sx} ${sy} V ${sy + sh} H ${sx + sw} V ${sy} Z`;
        g.appendChild(
          createSvgEl(doc, "path", {
            d: hazardMask,
            fill: "rgba(255, 93, 122, 0.12)",
            "fill-rule": "evenodd",
          })
        );

        g.appendChild(
          createSvgEl(doc, "rect", {
            x: sx,
            y: sy,
            width: sw,
            height: sh,
            fill: "none",
            stroke: "#ff5d7a",
            "stroke-width": strokeUnit * 1.15,
            "stroke-dasharray": dashLong,
          })
        );

        const labelSize = Math.max(10, Math.round(fw * 0.023));
        addLabel(g, fx + fw / 2, fy + top * 0.52, "TOP UI", {
          fill: "#ffb2c0",
          fontSize: labelSize,
        });
        addLabel(g, sx + sw + right * 0.5, sy + sh * 0.5, "ACTIONS", {
          fill: "#ffb2c0",
          fontSize: labelSize,
          rotate: -90,
        });
        addLabel(g, fx + fw / 2, sy + sh + bottom * 0.52, "CAPTION / CTA", {
          fill: "#ffb2c0",
          fontSize: labelSize,
        });
        addLabel(g, sx + Math.max(10, fw * 0.018), sy + Math.max(14, fh * 0.018), "SAFE AREA", {
          anchor: "start",
          fill: "#3ad29f",
          fontSize: Math.max(10, Math.round(labelSize * 0.92)),
        });
      } else if (state.safeZone === "16:9") {
        const targetAspect = 16 / 9;
        let fw = W;
        let fh = H;
        if (W / H > targetAspect) {
          fh = H;
          fw = H * targetAspect;
        } else {
          fw = W;
          fh = W / targetAspect;
        }
        const fx = xOff + (W - fw) / 2;
        const fy = (H - fh) / 2;

        if (fw < W - 0.5 || fh < H - 0.5) {
          const cropMask = `M ${xOff} 0 H ${xOff + W} V ${H} H ${xOff} Z M ${fx} ${fy} V ${fy + fh} H ${fx + fw} V ${fy} Z`;
          g.appendChild(
            createSvgEl(doc, "path", {
              d: cropMask,
              fill: "rgba(11, 13, 19, 0.45)",
              "fill-rule": "evenodd",
            })
          );
          g.appendChild(
            createSvgEl(doc, "rect", {
              x: fx,
              y: fy,
              width: fw,
              height: fh,
              fill: "none",
              stroke: "rgba(236, 239, 247, 0.55)",
              "stroke-width": strokeUnit,
            })
          );
        }

        const ax = fx + fw * 0.05;
        const ay = fy + fh * 0.05;
        const aw = fw * 0.9;
        const ah = fh * 0.9;

        const tx = fx + fw * 0.1;
        const ty = fy + fh * 0.1;
        const tw = fw * 0.8;
        const th = fh * 0.8;

        const outerMarginMask = `M ${fx} ${fy} H ${fx + fw} V ${fy + fh} H ${fx} Z M ${ax} ${ay} V ${ay + ah} H ${ax + aw} V ${ay} Z`;
        g.appendChild(
          createSvgEl(doc, "path", {
            d: outerMarginMask,
            fill: "rgba(108, 140, 255, 0.09)",
            "fill-rule": "evenodd",
          })
        );

        g.appendChild(
          createSvgEl(doc, "rect", {
            x: ax,
            y: ay,
            width: aw,
            height: ah,
            fill: "none",
            stroke: "#6c8cff",
            "stroke-width": strokeUnit,
            "stroke-dasharray": dashLong,
          })
        );
        g.appendChild(
          createSvgEl(doc, "rect", {
            x: tx,
            y: ty,
            width: tw,
            height: th,
            fill: "none",
            stroke: "#3ad29f",
            "stroke-width": strokeUnit,
            "stroke-dasharray": `${Math.round(strokeUnit * 3)} ${Math.round(strokeUnit * 3)}`,
          })
        );

        const labelSize = Math.max(10, Math.round(Math.min(fw, fh) * 0.022));
        addLabel(g, ax + 10, ay + labelSize * 0.8, "ACTION SAFE 5%", {
          anchor: "start",
          fill: "#b7c8ff",
          fontSize: labelSize,
        });
        addLabel(g, tx + 10, ty + labelSize * 0.8, "TITLE SAFE 10%", {
          anchor: "start",
          fill: "#3ad29f",
          fontSize: labelSize,
        });
      } else if (state.safeZone === "1:1") {
        const size = Math.min(W, H);
        const fx = xOff + (W - size) / 2;
        const fy = (H - size) / 2;
        const sx = fx + size * 0.05;
        const sy = fy + size * 0.05;
        const sw = size * 0.9;
        const sh = size * 0.9;

        if (size < W - 0.5 || size < H - 0.5) {
          const cropMask = `M ${xOff} 0 H ${xOff + W} V ${H} H ${xOff} Z M ${fx} ${fy} V ${fy + size} H ${fx + size} V ${fy} Z`;
          g.appendChild(
            createSvgEl(doc, "path", {
              d: cropMask,
              fill: "rgba(11, 13, 19, 0.45)",
              "fill-rule": "evenodd",
            })
          );
        }

        g.appendChild(
          createSvgEl(doc, "rect", {
            x: fx,
            y: fy,
            width: size,
            height: size,
            fill: "none",
            stroke: "#6c8cff",
            "stroke-width": strokeUnit,
            "stroke-dasharray": dashLong,
          })
        );
        g.appendChild(
          createSvgEl(doc, "rect", {
            x: sx,
            y: sy,
            width: sw,
            height: sh,
            fill: "none",
            stroke: "#3ad29f",
            "stroke-width": strokeUnit,
            "stroke-dasharray": `${Math.round(strokeUnit * 3)} ${Math.round(strokeUnit * 3)}`,
          })
        );

        const labelSize = Math.max(10, Math.round(size * 0.022));
        addLabel(g, fx + size / 2, fy + size * 0.025, "1:1 CROP", {
          fill: "#b7c8ff",
          fontSize: labelSize,
        });
        addLabel(g, sx + 10, sy + labelSize * 0.85, "SAFE 5%", {
          anchor: "start",
          fill: "#3ad29f",
          fontSize: labelSize,
        });
      } else if (state.safeZone === "thirds") {
        const xs = [xOff + W / 3, xOff + (2 * W) / 3];
        const ys = [H / 3, (2 * H) / 3];
        const hairline = Math.max(1, strokeUnit * 0.7);
        for (const x of xs) {
          g.appendChild(
            createSvgEl(doc, "line", {
              x1: x,
              y1: 0,
              x2: x,
              y2: H,
              stroke: "rgba(11, 13, 19, 0.55)",
              "stroke-width": hairline * 2.2,
            })
          );
          g.appendChild(
            createSvgEl(doc, "line", {
              x1: x,
              y1: 0,
              x2: x,
              y2: H,
              stroke: "rgba(236, 239, 247, 0.52)",
              "stroke-width": hairline,
            })
          );
        }
        for (const y of ys) {
          g.appendChild(
            createSvgEl(doc, "line", {
              x1: xOff,
              y1: y,
              x2: xOff + W,
              y2: y,
              stroke: "rgba(11, 13, 19, 0.55)",
              "stroke-width": hairline * 2.2,
            })
          );
          g.appendChild(
            createSvgEl(doc, "line", {
              x1: xOff,
              y1: y,
              x2: xOff + W,
              y2: y,
              stroke: "rgba(236, 239, 247, 0.52)",
              "stroke-width": hairline,
            })
          );
        }
        const tick = Math.max(6, Math.round(Math.min(W, H) * 0.015));
        for (const x of xs) {
          for (const y of ys) {
            g.appendChild(
              createSvgEl(doc, "circle", {
                cx: x,
                cy: y,
                r: tick * 0.45,
                fill: "none",
                stroke: "rgba(108, 140, 255, 0.85)",
                "stroke-width": hairline * 1.4,
              })
            );
          }
        }
      }

      svg.appendChild(g);
    }
  }

  function drawCanvasBadge(ctx, x, y, text, color) {
    const scale = Math.max(0.7, Math.min(2.2, state.width / 1080));
    const padX = Math.round(10 * scale);
    const h = Math.round(24 * scale);
    const fontPx = Math.round(12 * scale);
    ctx.save();
    ctx.font = `700 ${fontPx}px ui-monospace, "SFMono-Regular", Menlo, monospace`;
    const textW = typeof ctx.measureText === "function" ? ctx.measureText(text).width : text.length * fontPx * 0.62;
    const boxW = Math.round(textW + padX * 2);
    ctx.fillStyle = "rgba(11, 13, 19, 0.82)";
    ctx.fillRect(x, y, boxW, h);
    ctx.strokeStyle = "#262b3d";
    ctx.lineWidth = Math.max(1, scale);
    ctx.strokeRect(x, y, boxW, h);
    ctx.fillStyle = color;
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + padX, y + h / 2);
    ctx.restore();
  }

  function renderBitmapsToStage(cloneBmp, refBmp, diffBmp = null) {
    const canvas = els.stageCanvas;
    if (!canvas) return;
    const ctx = getCanvasContext2D(canvas);
    if (!ctx) return;

    const W = Math.max(1, state.width);
    const H = Math.max(1, state.height);
    const { dispW, dispH } = getDisplayDimensions();
    ctx.clearRect(0, 0, dispW, dispH);

    if (state.mode === "diff") {
      if (diffBmp) {
        ctx.drawImage(diffBmp, 0, 0, W, H);
        drawCanvasBadge(ctx, 12, 12, "4x DIFF (MAE)", "#ffb454");
      } else if (cloneBmp) {
        ctx.drawImage(cloneBmp, 0, 0, W, H);
      }
    } else if (state.mode === "sbs") {
      if (refBmp) {
        ctx.drawImage(refBmp, 0, 0, W, H);
      } else {
        ctx.fillStyle = "#0b0d13";
        ctx.fillRect(0, 0, W, H);
        drawCanvasBadge(ctx, 12, 12, "NO REF", "#8b93ad");
      }
      if (cloneBmp) {
        ctx.drawImage(cloneBmp, W, 0, W, H);
      }
      ctx.fillStyle = "#262b3d";
      ctx.fillRect(W - 1, 0, 2, H);
      if (refBmp) drawCanvasBadge(ctx, 12, 12, "ORIGINAL", "#3ad29f");
      drawCanvasBadge(ctx, W + 12, 12, "CLONE", "#6c8cff");
    } else if (state.mode === "split" && refBmp && cloneBmp) {
      const splitX = Math.round((clamp(state.splitRatio, 0, 100) / 100) * W);
      ctx.drawImage(refBmp, 0, 0, W, H);
      ctx.save();
      ctx.beginPath();
      ctx.rect(splitX, 0, Math.max(0, W - splitX), H);
      ctx.clip();
      ctx.drawImage(cloneBmp, 0, 0, W, H);
      ctx.restore();

      const lineW = Math.max(2, Math.round(W * 0.002));
      ctx.fillStyle = "rgba(11, 13, 19, 0.72)";
      ctx.fillRect(splitX - lineW, 0, lineW * 2, H);
      ctx.fillStyle = "#eceff7";
      ctx.fillRect(splitX - Math.max(1, lineW * 0.5), 0, Math.max(1, lineW), H);
    } else if (state.mode === "onion" && refBmp && cloneBmp) {
      const alpha = clamp(state.splitRatio, 0, 100) / 100;
      ctx.drawImage(refBmp, 0, 0, W, H);
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.drawImage(cloneBmp, 0, 0, W, H);
      ctx.restore();
    } else if (cloneBmp) {
      ctx.drawImage(cloneBmp, 0, 0, W, H);
    }

    redrawOverlay();
    if (state.loupeEnabled && pointer.active) {
      updateLoupeAt(pointer.relX, pointer.relY);
    }
  }

  function syncSceneDurationFromWindow(win) {
    if (!win) return;
    let rawTotal = null;
    let rawFps = null;
    try {
      rawTotal = win.kinearc?.totalDuration ?? win.kinearc?.total ?? win.TOTAL;
      rawFps = win.kinearc?.fps ?? win.FPS;
    } catch (_err) {
      rawTotal = null;
      rawFps = null;
    }
    const fpsVal = Number(rawFps);
    const dur = Number(rawTotal);
    let changed = false;
    if (!state.hasVideo && Number.isFinite(fpsVal) && fpsVal > 0 && Math.abs(state.fps - fpsVal) > 0.001) {
      state.fps = fpsVal;
      changed = true;
    }
    if (Number.isFinite(dur) && dur > 0) {
      if (state.durationSec <= 0 || (!state.hasVideo && Math.abs(state.durationSec - dur) > 0.001)) {
        state.durationSec = dur;
        changed = true;
      }
      if (state.totalFrames <= 0 || !state.hasVideo) {
        state.totalFrames = Math.max(1, Math.round(state.durationSec * state.fps));
        changed = true;
      }
    }
    if (changed) {
      updateMetaBadge();
      emitEvent("kinearc:sceneready", {
        durationSec: state.durationSec,
        totalFrames: state.totalFrames,
        fps: state.fps,
        url: state.liveSceneUrl,
      });
    }
  }

  async function applyLiveSeek(tSec) {
    pendingLiveSeek = tSec;
    const frame = els.liveFrame;
    if (!frame || !liveFrameLoaded) return;

    const loadTok = liveLoadToken;
    const seekTok = ++liveSeekToken;
    let win = null;
    try {
      win = frame.contentWindow;
    } catch (_err) {
      return;
    }
    if (!win) return;

    if (!liveFrameReady) {
      try {
        const readyPromise = win.kinearc?.ready ?? win.ready;
        if (readyPromise && typeof readyPromise.then === "function") {
          await readyPromise;
        }
      } catch (_err) {
        // Scene ready rejected; proceed to attempt deterministic seek safely
      }
      if (destroyed || loadTok !== liveLoadToken) return;
      liveFrameReady = true;
      syncSceneDurationFromWindow(win);
      if (seekTok !== liveSeekToken) return;
    }

    const targetT = Number.isFinite(pendingLiveSeek) ? pendingLiveSeek : 0;
    try {
      if (typeof win.kinearc?.seek === "function") {
        win.kinearc.seek(targetT);
      } else if (typeof win.renderAt === "function") {
        win.renderAt(targetT);
      }
    } catch (_err) {
      // Protect host workbench from cross-frame or scene runtime errors
    }
  }

  function loadLiveScene(url) {
    if (!url || !els.liveFrame) return;
    state.liveSceneUrl = url;
    liveLoadToken += 1;
    const token = liveLoadToken;
    liveFrameLoaded = false;
    liveFrameReady = false;
    pendingLiveSeek = null;

    const frame = els.liveFrame;
    frame.onload = () => {
      if (destroyed || token !== liveLoadToken) return;
      liveFrameLoaded = true;
      const targetT = Number.isFinite(pendingLiveSeek) ? pendingLiveSeek : state.currentTimeSec;
      applyLiveSeek(targetT);
    };
    frame.src = url;
  }

  async function fetchFrameBitmap(url, signal, createdList) {
    const fetchFn = typeof fetch === "function" ? fetch : null;
    const decodeFn = typeof createImageBitmap === "function" ? createImageBitmap : null;
    if (!fetchFn || !decodeFn) return null;

    const res = await fetchFn(url, { signal, cache: "no-store" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} fetching ${url}`);
    }
    const blob = await res.blob();
    if (signal.aborted) return null;

    const bmp = await decodeFn(blob);
    if (signal.aborted) {
      closeBitmap(bmp);
      return null;
    }
    createdList.push(bmp);
    return bmp;
  }

  function schedulePrefetch(anchorIdx = state.currentFrameIdx) {
    if (destroyed || !(frameCacheEnabled || isPlaying) || !state.hasVideo || state.totalFrames <= 1) {
      return;
    }
    if (!prefetchAbort) {
      prefetchAbort = typeof AbortController !== "undefined" ? new AbortController() : { signal: { aborted: false }, abort() {} };
    }
    const signal = prefetchAbort.signal;
    const epoch = prefetchEpoch;
    const total = Math.min(state.totalFrames, 180);
    const preferDiffFirst = state.mode === "diff" && state.hasRef;
    const phases = state.hasRef
      ? (preferDiffFirst ? ["diff", "pair"] : ["pair", "diff"])
      : ["clone"];

    for (const phase of phases) {
      if (inflightPrefetch.size >= MAX_PREFETCH_CONCURRENCY) break;
      const isDiffPhase = phase === "diff";
      const needRef = phase === "pair";

      for (let offset = 0; offset < total; offset++) {
        if (inflightPrefetch.size >= MAX_PREFETCH_CONCURRENCY) break;
        const idx = (anchorIdx + offset) % state.totalFrames;
        const existing = frameCache.get(idx);
        const alreadyCached = isDiffPhase
          ? Boolean(existing?.diff)
          : Boolean(existing?.clone && (!needRef || existing?.ref));
        if (alreadyCached) continue;

        const key = `${phase}:${idx}`;
        if (inflightPrefetch.has(key)) continue;

        inflightPrefetch.add(key);
        const created = [];

        (async () => {
          try {
            if (isDiffPhase) {
              const diffBmp = await fetchFrameBitmap(`/api/frame?idx=${idx}&kind=diff`, signal, created);
              if (destroyed || signal.aborted || epoch !== prefetchEpoch || !diffBmp) {
                for (const b of created) closeBitmap(b);
                return;
              }
              const entry = getOrCreateCacheEntry(idx);
              if (entry.diff && entry.diff !== diffBmp) closeBitmap(entry.diff);
              entry.diff = diffBmp;
            } else {
              const cur = frameCache.get(idx);
              const [cloneBmp, refBmp] = await Promise.all([
                cur?.clone ? Promise.resolve(cur.clone) : fetchFrameBitmap(`/api/frame?idx=${idx}&kind=clone`, signal, created),
                needRef
                  ? (cur?.ref ? Promise.resolve(cur.ref) : fetchFrameBitmap(`/api/frame?idx=${idx}&kind=ref`, signal, created))
                  : Promise.resolve(null),
              ]);
              if (destroyed || signal.aborted || epoch !== prefetchEpoch || !cloneBmp) {
                for (const b of created) closeBitmap(b);
                return;
              }
              const entry = getOrCreateCacheEntry(idx);
              if (entry.clone && entry.clone !== cloneBmp && entry.clone !== heldBitmaps.clone) closeBitmap(entry.clone);
              entry.clone = cloneBmp;
              if (refBmp) {
                if (entry.ref && entry.ref !== refBmp && entry.ref !== heldBitmaps.ref) closeBitmap(entry.ref);
                entry.ref = refBmp;
              }
            }
          } catch (_err) {
            for (const b of created) closeBitmap(b);
          } finally {
            inflightPrefetch.delete(key);
            if (!destroyed && !signal.aborted && epoch === prefetchEpoch) {
              schedulePrefetch(state.currentFrameIdx);
            }
          }
        })();
      }
    }
  }

  async function renderMp4Frame(frameIdx) {
    if (!state.hasVideo) {
      clearHeldBitmaps();
      const ctx = getCanvasContext2D(els.stageCanvas);
      if (ctx) {
        const { dispW, dispH } = getDisplayDimensions();
        ctx.clearRect(0, 0, dispW, dispH);
      }
      redrawOverlay();
      return;
    }

    const targetIdx = state.totalFrames > 0 ? clamp(frameIdx, 0, state.totalFrames - 1) : Math.max(0, frameIdx);
    const keepHeldForInteractiveMix = state.mode === "split" || state.mode === "onion";
    const useCache = frameCacheEnabled || isPlaying;

    if (useCache && hasCachedFrame(targetIdx, state.mode)) {
      abortInFlightFetch();
      const entry = getOrCreateCacheEntry(targetIdx);
      if (state.mode === "diff" && state.hasRef) {
        clearHeldBitmaps();
        renderBitmapsToStage(null, null, entry.diff);
      } else {
        clearHeldBitmaps();
        renderBitmapsToStage(entry.clone, entry.ref);
        if (keepHeldForInteractiveMix) {
          heldBitmaps.frameIdx = targetIdx;
          heldBitmaps.clone = entry.clone;
          heldBitmaps.ref = entry.ref;
        }
      }
      schedulePrefetch(targetIdx);
      return;
    }

    // Fast path: reuse single cached frame bitmaps when switching between split/onion or adjusting ratio on same frame
    if (
      keepHeldForInteractiveMix &&
      heldBitmaps.frameIdx === targetIdx &&
      heldBitmaps.clone &&
      (!state.hasRef || heldBitmaps.ref)
    ) {
      abortInFlightFetch();
      renderBitmapsToStage(heldBitmaps.clone, heldBitmaps.ref);
      return;
    }

    abortInFlightFetch();
    if (useCache) {
      schedulePrefetch(targetIdx);
    }
    const controller = typeof AbortController !== "undefined" ? new AbortController() : { signal: { aborted: false }, abort() {} };
    activeFetchController = controller;
    const signal = controller.signal;
    const seq = ++fetchSeq;
    const created = [];

    try {
      if (state.mode === "diff" && state.hasRef) {
        const diffBmp = await fetchFrameBitmap(`/api/frame?idx=${targetIdx}&kind=diff`, signal, created);
        if (destroyed || signal.aborted || seq !== fetchSeq) {
          for (const b of created) closeBitmap(b);
          return;
        }
        clearHeldBitmaps();
        renderBitmapsToStage(null, null, diffBmp);
        if (useCache && diffBmp) {
          const entry = getOrCreateCacheEntry(targetIdx);
          if (entry.diff && entry.diff !== diffBmp) closeBitmap(entry.diff);
          entry.diff = diffBmp;
          schedulePrefetch(targetIdx);
        } else {
          closeBitmap(diffBmp);
        }
        return;
      }

      const needRef = state.hasRef && (state.mode === "sbs" || state.mode === "split" || state.mode === "onion");
      const cachedPartial = useCache ? frameCache.get(targetIdx) : null;
      const [cloneBmp, refBmp] = await Promise.all([
        cachedPartial?.clone
          ? Promise.resolve(cachedPartial.clone)
          : fetchFrameBitmap(`/api/frame?idx=${targetIdx}&kind=clone`, signal, created),
        needRef
          ? (cachedPartial?.ref
              ? Promise.resolve(cachedPartial.ref)
              : fetchFrameBitmap(`/api/frame?idx=${targetIdx}&kind=ref`, signal, created))
          : Promise.resolve(cachedPartial?.ref || null),
      ]);

      if (destroyed || signal.aborted || seq !== fetchSeq || !cloneBmp) {
        for (const b of created) closeBitmap(b);
        return;
      }

      clearHeldBitmaps();
      renderBitmapsToStage(cloneBmp, refBmp);

      if (useCache) {
        const entry = getOrCreateCacheEntry(targetIdx);
        if (entry.clone && entry.clone !== cloneBmp) closeBitmap(entry.clone);
        entry.clone = cloneBmp;
        if (refBmp) {
          if (entry.ref && entry.ref !== refBmp) closeBitmap(entry.ref);
          entry.ref = refBmp;
        }
        if (keepHeldForInteractiveMix) {
          heldBitmaps.frameIdx = targetIdx;
          heldBitmaps.clone = cloneBmp;
          heldBitmaps.ref = refBmp;
        }
        schedulePrefetch(targetIdx);
      } else if (keepHeldForInteractiveMix) {
        heldBitmaps.frameIdx = targetIdx;
        heldBitmaps.clone = cloneBmp;
        heldBitmaps.ref = refBmp;
      } else {
        closeBitmap(cloneBmp);
        closeBitmap(refBmp);
      }
    } catch (err) {
      for (const b of created) closeBitmap(b);
      if (err?.name === "AbortError" || signal.aborted) {
        return;
      }
    } finally {
      if (activeFetchController === controller) {
        activeFetchController = null;
      }
    }
  }

  function updateMetaBadge() {
    if (!els.metaBadge) return;
    const dims = `${state.width}×${state.height} · ${formatFpsLabel(state.fps)}fps`;
    els.metaBadge.textContent = state.totalFrames > 0 ? `${dims} · ${state.totalFrames}f` : dims;
  }

  function updateModeButtonsUI() {
    if (!els.modeTabs) return;
    const buttons = els.modeTabs.querySelectorAll("[data-mode]");
    for (const btn of buttons) {
      const m = btn.dataset?.mode || btn.getAttribute?.("data-mode");
      const allowed =
        (m === "live" && state.hasLive) ||
        (m === "clone" && state.hasVideo) ||
        ((m === "sbs" || m === "split" || m === "onion" || m === "diff") && state.hasVideo && state.hasRef);
      btn.disabled = !allowed;
      const isActive = m === state.mode;
      btn.classList?.toggle("active", isActive);
      btn.setAttribute?.("aria-selected", isActive ? "true" : "false");
    }
  }

  function updateSplitControlUI() {
    const show = state.mode === "split" || state.mode === "onion";
    if (els.splitControl) {
      els.splitControl.classList.toggle("hidden", !show);
    }
    if (els.splitControlLabel) {
      els.splitControlLabel.textContent = state.mode === "onion" ? "Mix" : "Split";
    }
    if (els.splitSlider) {
      els.splitSlider.value = String(Math.round(state.splitRatio));
    }
    if (els.splitValue) {
      els.splitValue.textContent = `${Math.round(state.splitRatio)}%`;
    }
  }

  function updateLoupeAt(relX, relY) {
    const lens = els.loupeLens;
    const lCanvas = els.loupeCanvas;
    if (!lens || !lCanvas || !state.loupeEnabled || !pointer.active) return;

    const { fitW, fitH, dispW, dispH } = fitMetrics;
    if (fitW <= 0 || fitH <= 0) return;

    const clampedX = clamp(relX, 0, fitW);
    const clampedY = clamp(relY, 0, fitH);

    if (lens.style) {
      lens.style.left = `${Math.round(clampedX - LOUPE_SIZE / 2)}px`;
      lens.style.top = `${Math.round(clampedY - LOUPE_SIZE / 2)}px`;
    }
    lens.classList.remove("hidden");

    const dpr = typeof window !== "undefined" ? clamp(window.devicePixelRatio || 1, 1, 2) : 1;
    const bufSize = Math.round(LOUPE_SIZE * dpr);
    if (lCanvas.width !== bufSize) lCanvas.width = bufSize;
    if (lCanvas.height !== bufSize) lCanvas.height = bufSize;

    const lCtx = getCanvasContext2D(lCanvas);
    if (!lCtx) return;

    lCtx.save();
    lCtx.fillStyle = "#0b0d13";
    lCtx.fillRect(0, 0, bufSize, bufSize);

    if (state.mode === "live") {
      if (els.loupeBadge) els.loupeBadge.textContent = "LIVE";
      lCtx.fillStyle = "#8b93ad";
      lCtx.font = `600 ${Math.round(11 * dpr)}px system-ui, sans-serif`;
      lCtx.textAlign = "center";
      lCtx.textBaseline = "middle";
      lCtx.fillText("Live iframe active", bufSize / 2, bufSize / 2 - 8 * dpr);
      lCtx.fillStyle = "#6c8cff";
      lCtx.fillText("2× pixel loupe: MP4", bufSize / 2, bufSize / 2 + 10 * dpr);
      lCtx.restore();
      return;
    }

    if (els.loupeBadge) els.loupeBadge.textContent = "2×";
    const sCanvas = els.stageCanvas;
    if (!sCanvas) {
      lCtx.restore();
      return;
    }

    const srcCx = (clampedX / fitW) * dispW;
    const srcCy = (clampedY / fitH) * dispH;
    const srcSpanW = (LOUPE_SIZE / 2) * (dispW / fitW);
    const srcSpanH = (LOUPE_SIZE / 2) * (dispH / fitH);

    const sx = srcCx - srcSpanW / 2;
    const sy = srcCy - srcSpanH / 2;
    const cx0 = Math.max(0, sx);
    const cy0 = Math.max(0, sy);
    const cx1 = Math.min(dispW, sx + srcSpanW);
    const cy1 = Math.min(dispH, sy + srcSpanH);

    if (cx1 > cx0 && cy1 > cy0) {
      const dx = ((cx0 - sx) / srcSpanW) * bufSize;
      const dy = ((cy0 - sy) / srcSpanH) * bufSize;
      const dw = ((cx1 - cx0) / srcSpanW) * bufSize;
      const dh = ((cy1 - cy0) / srcSpanH) * bufSize;
      lCtx.imageSmoothingEnabled = srcSpanW >= bufSize;
      lCtx.drawImage(sCanvas, cx0, cy0, cx1 - cx0, cy1 - cy0, dx, dy, dw, dh);
    }
    lCtx.restore();
  }

  function hideLoupeLens() {
    if (els.loupeLens) {
      els.loupeLens.classList.add("hidden");
    }
  }

  // ---------- Public API Methods ----------

  function init(info = {}) {
    clearHeldBitmaps();
    clearFrameCache();
    state.width = Number(info.width) > 0 ? Number(info.width) : 1920;
    state.height = Number(info.height) > 0 ? Number(info.height) : 1080;
    state.fps = Number(info.fps) > 0 ? Number(info.fps) : 30;
    state.totalFrames = Math.max(0, Number(info.totalFrames ?? info.total_frames ?? 0) || 0);
    const rawDur = Number(info.duration_sec ?? info.durationSec ?? 0);
    state.durationSec = Number.isFinite(rawDur) && rawDur > 0
      ? rawDur
      : (state.totalFrames > 0 && state.fps > 0 ? state.totalFrames / state.fps : 0);

    state.hasVideo = Boolean(info.has_video ?? info.hasVideo);
    state.hasRef = Boolean(info.has_ref ?? info.hasRef);
    state.scenes = Array.isArray(info.scenes) ? info.scenes : [];
    const firstSceneUrl = state.scenes[0]?.url || null;
    const sceneUrl = info.live_scene_url || firstSceneUrl || null;
    state.hasLive = Boolean(info.has_live_scene ?? info.hasLive ?? sceneUrl);

    if (els.sceneSelect) {
      if (typeof els.sceneSelect.replaceChildren === "function") {
        els.sceneSelect.replaceChildren();
      } else {
        els.sceneSelect.innerHTML = "";
      }
      if (state.scenes.length > 1) {
        const doc = els.sceneSelect.ownerDocument || (typeof document !== "undefined" ? document : null);
        if (doc) {
          for (const sc of state.scenes) {
            const opt = doc.createElement("option");
            opt.value = sc.url || "";
            opt.textContent = sc.name || sc.path || sc.url || "Scene";
            els.sceneSelect.appendChild(opt);
          }
        }
        if (sceneUrl) els.sceneSelect.value = sceneUrl;
        els.sceneSelect.classList.remove("hidden");
      } else {
        els.sceneSelect.classList.add("hidden");
      }
    }

    updateMetaBadge();
    updateModeButtonsUI();

    if (state.hasLive && sceneUrl) {
      loadLiveScene(sceneUrl);
    }

    let defaultMode = VALID_MODES.has(info.mode_default) ? info.mode_default : (state.hasLive && !state.hasVideo ? "live" : "clone");
    if (defaultMode === "live" && !state.hasLive && state.hasVideo) defaultMode = "clone";
    if (defaultMode !== "live" && !state.hasVideo && state.hasLive) defaultMode = "live";
    if ((defaultMode === "sbs" || defaultMode === "split" || defaultMode === "onion" || defaultMode === "diff") && !state.hasRef) {
      defaultMode = state.hasVideo ? "clone" : "live";
    }

    setMode(defaultMode, { seek: false });
    setSafeZone(state.safeZone);
    fitStage();

    if (state.hasVideo || state.hasLive) {
      seekTime(0, 0);
      if ((frameCacheEnabled || isPlaying) && state.hasVideo) {
        schedulePrefetch(0);
      }
    } else {
      updateEmptyBanner();
    }
  }

  function setMode(mode, opts = {}) {
    if (!VALID_MODES.has(mode)) return;
    if (mode !== state.mode) {
      abortInFlightFetch();
      if (mode === "live" || (mode !== "split" && mode !== "onion")) {
        clearHeldBitmaps();
      }
    }
    state.mode = mode;

    const isLive = mode === "live";
    if (els.liveFrame) {
      els.liveFrame.classList.remove("hidden");
      els.liveFrame.classList.toggle("is-inactive", !isLive);
      els.liveFrame.setAttribute?.("aria-hidden", isLive ? "false" : "true");
      if (isLive) {
        els.liveFrame.removeAttribute?.("tabindex");
      } else {
        els.liveFrame.setAttribute?.("tabindex", "-1");
      }
    }
    if (els.stageCanvas) {
      els.stageCanvas.classList.toggle("hidden", isLive);
      els.stageCanvas.setAttribute?.("aria-hidden", isLive ? "true" : "false");
    }

    syncCanvasAndSvgDimensions();
    renderSafeZone();
    updateModeButtonsUI();
    updateSplitControlUI();
    updateEmptyBanner();
    fitStage();

    emitEvent("kinearc:modechange", { mode: state.mode });

    if (opts.seek !== false && (state.hasVideo || state.hasLive)) {
      seekTime(state.currentTimeSec, state.currentFrameIdx);
    } else if (state.loupeEnabled && pointer.active) {
      updateLoupeAt(pointer.relX, pointer.relY);
    }
    if ((frameCacheEnabled || isPlaying) && state.hasVideo) {
      schedulePrefetch(state.currentFrameIdx);
    }
  }

  function seekTime(tSec, frameIdx) {
    const fps = state.fps > 0 ? state.fps : 30;
    const maxFrame = state.totalFrames > 0 ? state.totalFrames - 1 : 0;

    let resolvedFrame;
    if (typeof frameIdx === "number" && Number.isFinite(frameIdx)) {
      resolvedFrame = state.totalFrames > 0 ? clamp(Math.round(frameIdx), 0, maxFrame) : Math.max(0, Math.round(frameIdx));
    } else if (typeof tSec === "number" && Number.isFinite(tSec)) {
      const f = Math.round(Math.max(0, tSec) * fps);
      resolvedFrame = state.totalFrames > 0 ? clamp(f, 0, maxFrame) : Math.max(0, f);
    } else {
      resolvedFrame = state.currentFrameIdx;
    }

    let resolvedTime;
    if (typeof tSec === "number" && Number.isFinite(tSec)) {
      resolvedTime = state.durationSec > 0 ? clamp(tSec, 0, state.durationSec) : Math.max(0, tSec);
    } else {
      resolvedTime = resolvedFrame / fps;
    }

    state.currentTimeSec = resolvedTime;
    state.currentFrameIdx = resolvedFrame;

    if (state.mode === "live") {
      applyLiveSeek(resolvedTime);
      redrawOverlay();
      if (state.loupeEnabled && pointer.active) {
        updateLoupeAt(pointer.relX, pointer.relY);
      }
      return Promise.resolve();
    }

    return renderMp4Frame(resolvedFrame);
  }

  function setSplitRatio(pct) {
    const num = Number(pct);
    state.splitRatio = Number.isFinite(num) ? clamp(num, 0, 100) : 50;
    updateSplitControlUI();
    emitEvent("kinearc:split", { ratio: state.splitRatio });

    if (state.mode === "split" || state.mode === "onion") {
      if (
        heldBitmaps.frameIdx === state.currentFrameIdx &&
        heldBitmaps.clone
      ) {
        renderBitmapsToStage(heldBitmaps.clone, heldBitmaps.ref);
      } else if ((frameCacheEnabled || isPlaying) && hasCachedFrame(state.currentFrameIdx, state.mode)) {
        const entry = frameCache.get(state.currentFrameIdx);
        if (entry?.clone) {
          renderBitmapsToStage(entry.clone, entry.ref);
        }
      }
    }
  }

  function enableFrameCache(enabled = true) {
    frameCacheEnabled = Boolean(enabled);
    if (!frameCacheEnabled && !isPlaying) {
      clearFrameCache();
    } else if (frameCacheEnabled && state.hasVideo) {
      schedulePrefetch(state.currentFrameIdx);
    }
  }

  function setPlaying(playing) {
    isPlaying = Boolean(playing);
    if (isPlaying && state.hasVideo) {
      schedulePrefetch(state.currentFrameIdx);
    }
  }

  function setSafeZone(ratio) {
    state.safeZone = VALID_SAFE_ZONES.has(ratio) ? ratio : "none";
    if (els.safeZoneSelect) {
      els.safeZoneSelect.value = state.safeZone;
    }
    renderSafeZone();
    emitEvent("kinearc:safezone", { safeZone: state.safeZone });
  }

  function setLoupe(enabled) {
    state.loupeEnabled = Boolean(enabled);
    if (els.btnLoupe) {
      els.btnLoupe.classList.toggle("active", state.loupeEnabled);
      els.btnLoupe.setAttribute("aria-pressed", state.loupeEnabled ? "true" : "false");
    }
    if (els.stageWrap) {
      els.stageWrap.classList.toggle("loupe-active", state.loupeEnabled);
    }
    if (!state.loupeEnabled) {
      hideLoupeLens();
    } else if (pointer.active) {
      updateLoupeAt(pointer.relX, pointer.relY);
    }
    emitEvent("kinearc:loupe", { enabled: state.loupeEnabled });
  }

  function setAnnotationsDrawer(fn) {
    annotationsDrawer = typeof fn === "function" ? fn : null;
    redrawOverlay();
  }

  function setScene(sceneUrl) {
    if (!sceneUrl) return;
    if (els.sceneSelect && els.sceneSelect.value !== sceneUrl) {
      els.sceneSelect.value = sceneUrl;
    }
    state.hasLive = true;
    loadLiveScene(sceneUrl);
    updateModeButtonsUI();
    updateEmptyBanner();
  }

  function toFrameCoords(clientX, clientY) {
    const target = els.overlayCanvas || els.stageWrap;
    if (!target || typeof target.getBoundingClientRect !== "function") {
      return [0, 0];
    }
    const rect = target.getBoundingClientRect();
    if (!rect.width || !rect.height) return [0, 0];

    const { dispW, dispH } = getDisplayDimensions();
    let px = Math.round(((clientX - rect.left) / rect.width) * dispW);
    let py = Math.round(((clientY - rect.top) / rect.height) * dispH);
    if (state.mode === "sbs" && px >= state.width) {
      px -= state.width;
    }
    return [clamp(px, 0, Math.max(0, state.width - 1)), clamp(py, 0, Math.max(0, state.height - 1))];
  }

  function getState() {
    const { dispW, dispH } = getDisplayDimensions();
    return {
      ...state,
      dispWidth: dispW,
      dispHeight: dispH,
      fitWidth: fitMetrics.fitW,
      fitHeight: fitMetrics.fitH,
      liveFrameLoaded,
      liveFrameReady,
      pendingLiveSeek,
    };
  }

  function destroy() {
    destroyed = true;
    isPlaying = false;
    pendingLiveSeek = null;
    abortInFlightFetch();
    clearHeldBitmaps();
    clearFrameCache();
    if (resizeObserver && typeof resizeObserver.disconnect === "function") {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
    if (listenerAbort) {
      listenerAbort.abort();
    }
    if (els.liveFrame) {
      els.liveFrame.onload = null;
    }
    if (wrapInstances && els.stageWrap && wrapInstances.get(els.stageWrap) === api) {
      wrapInstances.delete(els.stageWrap);
    }
  }

  // ---------- Event Wiring ----------

  const addEvt = (el, type, handler) => {
    if (!el || typeof el.addEventListener !== "function") return;
    el.addEventListener(type, handler, listenerSignal ? { signal: listenerSignal } : undefined);
  };

  if (els.modeTabs) {
    addEvt(els.modeTabs, "click", (evt) => {
      const btn = evt.target?.closest ? evt.target.closest("[data-mode]") : null;
      if (!btn || btn.disabled) return;
      const mode = btn.dataset?.mode || btn.getAttribute?.("data-mode");
      if (mode) setMode(mode);
    });
  }

  if (els.safeZoneSelect) {
    addEvt(els.safeZoneSelect, "change", () => {
      setSafeZone(els.safeZoneSelect.value);
    });
  }

  if (els.splitSlider) {
    addEvt(els.splitSlider, "input", () => {
      setSplitRatio(els.splitSlider.value);
    });
  }

  if (els.sceneSelect) {
    addEvt(els.sceneSelect, "change", () => {
      setScene(els.sceneSelect.value);
    });
  }

  if (els.btnLoupe) {
    addEvt(els.btnLoupe, "click", () => {
      setLoupe(!state.loupeEnabled);
    });
  }

  const pointerHost = els.overlayCanvas || els.stageWrap;
  if (pointerHost) {
    addEvt(pointerHost, "pointermove", (evt) => {
      const rectTarget = els.stageWrap || pointerHost;
      if (typeof rectTarget.getBoundingClientRect !== "function") return;
      const rect = rectTarget.getBoundingClientRect();
      pointer.active = true;
      pointer.relX = evt.clientX - rect.left;
      pointer.relY = evt.clientY - rect.top;
      if (state.loupeEnabled) {
        updateLoupeAt(pointer.relX, pointer.relY);
      }
    });

    addEvt(pointerHost, "pointerleave", () => {
      pointer.active = false;
      hideLoupeLens();
    });
  }

  if (typeof ResizeObserver === "function" && els.stagePane) {
    resizeObserver = new ResizeObserver(() => fitStage());
    resizeObserver.observe(els.stagePane);
  }
  if (typeof window !== "undefined") {
    addEvt(window, "resize", () => fitStage());
    addEvt(window, "pagehide", () => {
      abortInFlightFetch();
      clearHeldBitmaps();
      clearFrameCache();
    });
  }

  const api = {
    init,
    setMode,
    seekTime,
    setSplitRatio,
    enableFrameCache,
    setPlaying,
    hasCachedFrame,
    setSafeZone,
    setLoupe,
    isLoupeEnabled: () => state.loupeEnabled,
    setAnnotationsDrawer,
    setScene,
    fitStage,
    redrawOverlay,
    toFrameCoords,
    getState,
    destroy,
  };

  if (wrapInstances && els.stageWrap) {
    wrapInstances.set(els.stageWrap, api);
  }
  if (typeof window !== "undefined") {
    window.__kinearcStage = api;
  }
  return api;
}

const defaultStage = typeof document !== "undefined" ? createStage() : null;
if (typeof window !== "undefined" && defaultStage) {
  window.__kinearcStage = defaultStage;
}
