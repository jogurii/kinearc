/**
 * timeline.js — Transport, Frame Stepping, Keyboard Shortcuts, Waveform & Markers for kinearc
 */

function clamp(val, min, max) {
  return Math.min(max, Math.max(min, val));
}

export function toFiniteNumber(val) {
  if (typeof val === "number") {
    return Number.isFinite(val) ? val : null;
  }
  if (typeof val === "string") {
    if (val.trim() === "") return null;
    const n = Number(val);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export function formatTimecode(sec) {
  const n = toFiniteNumber(sec);
  const safe = n !== null ? Math.max(0, n) : 0;
  const totalCentis = Math.max(0, Math.round(safe * 100));
  const centis = totalCentis % 100;
  const totalSecs = Math.floor(totalCentis / 100);
  const secs = totalSecs % 60;
  const mins = Math.floor(totalSecs / 60);
  const mm = String(mins).padStart(2, "0");
  const ss = String(secs).padStart(2, "0");
  const cc = String(centis).padStart(2, "0");
  return `${mm}:${ss}.${cc}`;
}

export function formatTimecodeReadout(currentSec, durationSec, frameIdx) {
  const fNum = toFiniteNumber(frameIdx);
  const f = fNum !== null ? Math.max(0, Math.round(fNum)) : 0;
  return `${formatTimecode(currentSec)} / ${formatTimecode(durationSec)} · f${f}`;
}

export function shouldIgnoreShortcutTarget(target) {
  if (!target) return false;
  const tag = typeof target.tagName === "string" ? target.tagName.toUpperCase() : "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    return true;
  }
  if (target.isContentEditable) {
    return true;
  }
  if (typeof target.getAttribute === "function" && target.getAttribute("contenteditable") === "true") {
    return true;
  }
  return false;
}

export function computeMarkerPercent({ frame = null, timeSec = null, totalFrames = 0, durationSec = 0, fps = 30 } = {}) {
  const tf = toFiniteNumber(totalFrames) ?? 0;
  const dur = toFiniteNumber(durationSec) ?? 0;
  const fpsNum = toFiniteNumber(fps);
  const rate = fpsNum !== null && fpsNum > 0 ? fpsNum : 30;

  const f = toFiniteNumber(frame);
  if (f !== null) {
    if (tf > 1) {
      return clamp((f / (tf - 1)) * 100, 0, 100);
    }
    if (dur > 0) {
      return clamp(((f / rate) / dur) * 100, 0, 100);
    }
    return 0;
  }

  const t = toFiniteNumber(timeSec);
  if (t !== null) {
    if (dur > 0) {
      return clamp((t / dur) * 100, 0, 100);
    }
    if (tf > 1) {
      return clamp(((t * rate) / (tf - 1)) * 100, 0, 100);
    }
    return 0;
  }

  return 0;
}

export function computeLoopStatus(info = {}) {
  const cloneNum = toFiniteNumber(info?.clone_loop_mae);
  const sourceNum = toFiniteNumber(info?.source_loop_mae);
  const hasClone = cloneNum !== null;
  const hasSource = sourceNum !== null;

  if (!hasClone && !hasSource) {
    return { present: false, clean: true, mae: null, label: "" };
  }

  const primary = hasClone ? cloneNum : sourceNum;
  const clean = primary <= 6.0;
  const prefix = hasClone ? "Loop MAE" : "Source Loop MAE";
  const label = `${prefix} ${primary.toFixed(2)} (${clean ? "clean" : "warn"})`;
  return { present: true, clean, mae: primary, label };
}

function pathBasename(filePath) {
  if (!filePath) return "sfx";
  const parts = String(filePath).replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : "sfx";
}

export function buildMarkerDescriptors(info = {}) {
  const totalFrames = toFiniteNumber(info?.totalFrames ?? info?.total_frames) ?? 0;
  const fpsVal = toFiniteNumber(info?.fps);
  const fps = fpsVal !== null && fpsVal > 0 ? fpsVal : 30;
  const rawDur = toFiniteNumber(info?.duration_sec ?? info?.durationSec);
  const durationSec = rawDur !== null && rawDur > 0 ? rawDur : (totalFrames > 0 ? totalFrames / fps : 0);

  const markers = [];

  const cuts = Array.isArray(info?.scene_cuts) ? info.scene_cuts : [];
  cuts.forEach((cut, idx) => {
    if (!cut || typeof cut !== "object") return;
    const rawAfter = toFiniteNumber(cut.after_frame);
    const rawBefore = toFiniteNumber(cut.before_frame);
    const afterF = rawAfter !== null ? rawAfter : (rawBefore !== null ? rawBefore + 1 : null);
    const rawTime = toFiniteNumber(cut.timestamp_sec);
    const tSec = rawTime !== null ? rawTime : (afterF !== null ? afterF / fps : null);
    const frame = afterF !== null ? Math.max(0, Math.round(afterF)) : Math.max(0, Math.round((tSec ?? 0) * fps));
    const pct = computeMarkerPercent({ frame: afterF, timeSec: tSec, totalFrames, durationSec, fps });
    const deltaVal = toFiniteNumber(cut.delta_mae);
    const delta = deltaVal !== null ? ` · ΔMAE ${deltaVal.toFixed(1)}` : "";
    const timeLabel = tSec !== null ? ` (${tSec.toFixed(2)}s)` : "";
    markers.push({
      kind: "cut",
      index: idx,
      frame,
      timeSec: tSec !== null ? tSec : frame / fps,
      pct,
      tooltip: `Cut @ f${frame}${timeLabel}${delta}`,
    });
  });

  const worstRaw = Array.isArray(info?.worst_frames) ? info.worst_frames : [];
  const worstSorted = [...worstRaw]
    .filter((w) => w && typeof w === "object" && toFiniteNumber(w.frame) !== null)
    .sort((a, b) => {
      const ra = toFiniteNumber(a.rank) ?? Infinity;
      const rb = toFiniteNumber(b.rank) ?? Infinity;
      if (ra !== rb) return ra - rb;
      return (toFiniteNumber(b.mae) ?? 0) - (toFiniteNumber(a.mae) ?? 0);
    })
    .slice(0, 5);

  worstSorted.forEach((item, idx) => {
    const frame = Math.max(0, Math.round(toFiniteNumber(item.frame)));
    const rawTime = toFiniteNumber(item.timestamp_sec);
    const tSec = rawTime !== null ? rawTime : frame / fps;
    const mae = toFiniteNumber(item.mae) ?? 0;
    const rank = toFiniteNumber(item.rank) ?? idx + 1;
    const pct = computeMarkerPercent({ frame, timeSec: tSec, totalFrames, durationSec, fps });
    markers.push({
      kind: "worst",
      rank,
      frame,
      timeSec: tSec,
      mae,
      pct,
      tooltip: `MAE ${mae.toFixed(2)} @ f${frame}`,
    });
  });

  const cues = Array.isArray(info?.sfx_cues) ? info.sfx_cues : [];
  cues.forEach((cue, idx) => {
    if (!cue || typeof cue !== "object") return;
    const rawTime = toFiniteNumber(cue.time ?? cue.time_sec);
    const tSec = rawTime !== null ? Math.max(0, rawTime) : 0;
    const frame = Math.max(0, Math.round(tSec * fps));
    const base = pathBasename(cue.file);
    const pct = computeMarkerPercent({ timeSec: tSec, totalFrames, durationSec, fps });
    markers.push({
      kind: "sfx",
      index: idx,
      file: base,
      frame,
      timeSec: tSec,
      pct,
      tooltip: `${base} @ ${tSec.toFixed(2)}s`,
    });
  });

  return markers;
}

function resolveElements(overrides = {}) {
  const byId = (id) => (typeof document !== "undefined" ? document.getElementById(id) : null);
  return {
    btnPlay: overrides.btnPlay ?? byId("btnPlay"),
    btnPrev1: overrides.btnPrev1 ?? byId("btnPrev1"),
    btnNext1: overrides.btnNext1 ?? byId("btnNext1"),
    btnPrev10: overrides.btnPrev10 ?? byId("btnPrev10"),
    btnNext10: overrides.btnNext10 ?? byId("btnNext10"),
    scrubber: overrides.scrubber ?? byId("scrubber"),
    playheadLine: overrides.playheadLine ?? byId("playheadLine"),
    timecodeReadout: overrides.timecodeReadout ?? byId("timecodeReadout"),
    loopStatusPill: overrides.loopStatusPill ?? byId("loopStatusPill"),
    timelineTrack: overrides.timelineTrack ?? byId("timelineTrack"),
    waveformCanvas: overrides.waveformCanvas ?? byId("waveformCanvas"),
    markersLayer: overrides.markersLayer ?? byId("markersLayer"),
  };
}

export function createTimeline({ stage, info = {}, onSeek = null, onToast = null, elements = {} } = {}) {
  const els = resolveElements(elements);
  const abortCtrl = typeof AbortController !== "undefined" ? new AbortController() : null;
  const sig = abortCtrl ? abortCtrl.signal : undefined;

  const state = {
    playing: false,
    currentFrame: 0,
    currentTimeSec: 0,
    fps: 30,
    totalFrames: 0,
    durationSec: 0,
  };

  let currentInfo = info || {};
  let peaksData = [];
  let waveformAbort = null;
  let rafId = null;
  let lastTickMs = 0;
  let mp4SeekPending = false;
  let mp4SeekToken = 0;
  let mp4DispatchedFrame = 0;
  let trackResizeObserver = null;
  let destroyed = false;

  function getMaxFrame() {
    return state.totalFrames > 0 ? state.totalFrames - 1 : 0;
  }

  function updateReadoutAndPlayhead() {
    const pct = computeMarkerPercent({
      frame: state.totalFrames > 1 ? state.currentFrame : null,
      timeSec: state.currentTimeSec,
      totalFrames: state.totalFrames,
      durationSec: state.durationSec,
      fps: state.fps,
    });

    if (els.scrubber) {
      els.scrubber.min = "0";
      els.scrubber.max = String(getMaxFrame());
      els.scrubber.value = String(state.currentFrame);
    }
    if (els.playheadLine && els.playheadLine.style) {
      els.playheadLine.style.left = `${pct.toFixed(3)}%`;
    }
    if (els.timecodeReadout) {
      els.timecodeReadout.textContent = formatTimecodeReadout(
        state.currentTimeSec,
        state.durationSec,
        state.currentFrame
      );
    }
  }

  function updatePlayButtonUI() {
    if (!els.btnPlay) return;
    els.btnPlay.textContent = state.playing ? "Pause" : "Play";
    els.btnPlay.classList?.toggle("active", state.playing);
    els.btnPlay.setAttribute?.("aria-pressed", state.playing ? "true" : "false");
  }

  function updateLoopPill(sourceInfo) {
    const pill = els.loopStatusPill;
    if (!pill) return;
    const status = computeLoopStatus(sourceInfo);
    if (!status.present) {
      pill.classList.add("hidden");
      pill.classList.remove("clean", "warn");
      pill.textContent = "";
      return;
    }
    pill.classList.remove("hidden");
    pill.classList.toggle("clean", status.clean);
    pill.classList.toggle("warn", !status.clean);
    pill.textContent = status.label;
  }

  function renderMarkers() {
    const layer = els.markersLayer;
    if (!layer) return;
    if (typeof layer.replaceChildren === "function") {
      layer.replaceChildren();
    } else {
      layer.innerHTML = "";
    }

    const doc = layer.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!doc) return;

    const mergedInfo = {
      ...currentInfo,
      fps: state.fps,
      totalFrames: state.totalFrames,
      durationSec: state.durationSec,
    };
    const descriptors = buildMarkerDescriptors(mergedInfo);

    for (const m of descriptors) {
      const btn = doc.createElement("button");
      btn.type = "button";
      btn.className = `timeline-marker marker-${m.kind}`;
      if (btn.style) {
        btn.style.left = `${m.pct.toFixed(3)}%`;
      }
      btn.title = m.tooltip;
      btn.setAttribute?.("aria-label", m.tooltip);
      btn.dataset.markerKind = m.kind;
      btn.dataset.frame = String(m.frame);
      btn.dataset.time = String(m.timeSec);

      btn.addEventListener("click", (evt) => {
        evt.stopPropagation?.();
        pause({ syncStage: false });
        if (m.kind === "sfx") {
          seekToTime(m.timeSec, m.frame);
        } else {
          seekToFrame(m.frame);
        }
      });

      layer.appendChild(btn);
    }
  }

  function drawWaveform() {
    const canvas = els.waveformCanvas;
    if (!canvas || typeof canvas.getContext !== "function") return;
    const host = els.timelineTrack || canvas;
    const rect = typeof host.getBoundingClientRect === "function" ? host.getBoundingClientRect() : null;
    const cssW = Math.max(1, Math.round(rect?.width || canvas.clientWidth || 600));
    const cssH = Math.max(1, Math.round(rect?.height || canvas.clientHeight || 58));
    const dpr = typeof window !== "undefined" ? clamp(window.devicePixelRatio || 1, 1, 2) : 1;

    const targetW = Math.round(cssW * dpr);
    const targetH = Math.round(cssH * dpr);
    if (canvas.width !== targetW) canvas.width = targetW;
    if (canvas.height !== targetH) canvas.height = targetH;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, targetW, targetH);

    // Subtle center baseline
    const midY = targetH / 2;
    ctx.fillStyle = "rgba(139, 147, 173, 0.16)";
    ctx.fillRect(0, midY - Math.max(1, dpr * 0.5), targetW, Math.max(1, dpr));

    if (!Array.isArray(peaksData) || peaksData.length === 0) return;

    const count = peaksData.length;
    const step = targetW / count;
    const barW = Math.max(1, step * 0.68);
    const maxAmpH = targetH * 0.82;

    ctx.fillStyle = "rgba(108, 140, 255, 0.42)";
    for (let i = 0; i < count; i++) {
      const peak = clamp(Number(peaksData[i]) || 0, 0, 1);
      const h = Math.max(peak > 0.005 ? 2 * dpr : 0, peak * maxAmpH);
      if (h <= 0) continue;
      const x = i * step + (step - barW) * 0.5;
      ctx.fillRect(x, midY - h * 0.5, barW, h);
    }
  }

  async function refreshWaveform(sourceInfo = currentInfo) {
    if (typeof fetch !== "function") return;
    if (waveformAbort) {
      try {
        waveformAbort.abort();
      } catch (_err) {
        // Ignore abort cleanup
      }
      waveformAbort = null;
    }

    const candidates = [];
    const hasAudioMeta = Boolean(sourceInfo?.audio && typeof sourceInfo.audio === "object");
    const audioMeta = hasAudioMeta ? sourceInfo.audio : {};
    if (hasAudioMeta) {
      if (audioMeta.voice) candidates.push("voice");
      if (audioMeta.bgm) candidates.push("bgm");
      if (audioMeta.video || (audioMeta.video === undefined && sourceInfo?.has_video)) {
        candidates.push("video");
      }
    } else {
      if (sourceInfo?.has_video) {
        candidates.push("video");
      } else if (sourceInfo?.has_video !== false) {
        candidates.push("voice", "bgm", "video");
      }
    }

    peaksData = [];
    if (candidates.length === 0) {
      if (!destroyed) {
        drawWaveform();
      }
      return;
    }

    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    waveformAbort = controller;
    const signal = controller ? controller.signal : undefined;

    try {
      for (const track of candidates) {
        if (destroyed || signal?.aborted) return;
        try {
          const res = await fetch(`/api/audio-peaks?track=${encodeURIComponent(track)}&bins=600`, {
            signal,
            cache: "no-store",
          });
          if (!res.ok) continue;
          const payload = await res.json();
          if (Array.isArray(payload?.bins) && payload.bins.length > 0) {
            peaksData = payload.bins;
            break;
          }
        } catch (err) {
          if (err?.name === "AbortError") return;
        }
      }
    } finally {
      if (waveformAbort === controller) {
        waveformAbort = null;
      }
    }
    if (!destroyed) {
      drawWaveform();
    }
  }

  function dispatchMp4PlaybackSeek(targetTime, targetFrame, token) {
    if (destroyed || !state.playing || token !== mp4SeekToken) return;
    const stageState = stage && typeof stage.getState === "function" ? stage.getState() : {};
    if (stageState.mode === "live") return;
    if (!stage || typeof stage.seekTime !== "function") return;

    mp4SeekPending = true;
    mp4DispatchedFrame = targetFrame;
    let seekPromise;
    try {
      seekPromise = Promise.resolve(stage.seekTime(targetTime, targetFrame));
    } catch (err) {
      seekPromise = Promise.reject(err);
    }
    seekPromise
      .catch(() => {})
      .finally(() => {
        if (token !== mp4SeekToken) return;
        mp4SeekPending = false;
        if (destroyed || !state.playing) return;
        const latestStageState = stage && typeof stage.getState === "function" ? stage.getState() : {};
        if (latestStageState.mode === "live") return;
        if (state.currentFrame !== mp4DispatchedFrame) {
          dispatchMp4PlaybackSeek(state.currentTimeSec, state.currentFrame, token);
        }
      });
  }

  function commitSeek(resolvedTime, resolvedFrame, { notifyStage = true } = {}) {
    state.currentTimeSec = resolvedTime;
    state.currentFrame = resolvedFrame;
    updateReadoutAndPlayhead();

    if (notifyStage && stage && typeof stage.seekTime === "function") {
      mp4SeekToken += 1;
      mp4SeekPending = false;
      mp4DispatchedFrame = resolvedFrame;
      try {
        Promise.resolve(stage.seekTime(resolvedTime, resolvedFrame)).catch(() => {});
      } catch (_err) {}
    }
    if (typeof onSeek === "function") {
      onSeek({ frame: resolvedFrame, timeSec: resolvedTime });
    }
  }

  function seekToFrame(frameIdx) {
    const fps = state.fps > 0 ? state.fps : 30;
    const maxFrame = getMaxFrame();
    const clampedFrame = state.totalFrames > 0 ? clamp(Math.round(frameIdx), 0, maxFrame) : Math.max(0, Math.round(frameIdx || 0));
    const tSec = state.durationSec > 0 ? clamp(clampedFrame / fps, 0, state.durationSec) : clampedFrame / fps;
    commitSeek(tSec, clampedFrame);
  }

  function seekToTime(tSec, frameOverride = null) {
    const fps = state.fps > 0 ? state.fps : 30;
    const maxFrame = getMaxFrame();
    const rawTimeVal = toFiniteNumber(tSec);
    const rawTime = rawTimeVal !== null ? Math.max(0, rawTimeVal) : 0;
    const clampedTime = state.durationSec > 0 ? clamp(rawTime, 0, state.durationSec) : rawTime;
    const ovFrameVal = toFiniteNumber(frameOverride);
    const computedFrame = ovFrameVal !== null
      ? Math.round(ovFrameVal)
      : Math.round(clampedTime * fps);
    const clampedFrame = state.totalFrames > 0 ? clamp(computedFrame, 0, maxFrame) : Math.max(0, computedFrame);
    commitSeek(clampedTime, clampedFrame);
  }

  function stepFrames(delta) {
    pause({ syncStage: false });
    seekToFrame(state.currentFrame + delta);
  }

  function getEffectiveDuration() {
    if (state.durationSec > 0) return state.durationSec;
    if (state.totalFrames > 0 && state.fps > 0) return state.totalFrames / state.fps;
    return 0;
  }

  function tickPlayback(nowMs) {
    if (!state.playing || destroyed) return;

    const dt = lastTickMs > 0 ? clamp((nowMs - lastTickMs) / 1000, 0, 0.1) : 0;
    lastTickMs = nowMs;

    const dur = getEffectiveDuration();
    if (dur <= 0) {
      pause({ syncStage: false });
      return;
    }

    let nextTime = state.currentTimeSec + dt;
    if (nextTime >= dur) {
      nextTime = nextTime % dur;
    }

    const fps = state.fps > 0 ? state.fps : 30;
    const maxFrame = getMaxFrame();
    const nextFrame = state.totalFrames > 0 ? clamp(Math.floor(nextTime * fps), 0, maxFrame) : Math.max(0, Math.floor(nextTime * fps));
    const stageState = stage && typeof stage.getState === "function" ? stage.getState() : {};
    const isLiveMode = stageState.mode === "live";
    const isCachedMp4 = !isLiveMode && typeof stage?.hasCachedFrame === "function" && stage.hasCachedFrame(nextFrame);

    if (isLiveMode || isCachedMp4) {
      commitSeek(nextTime, nextFrame, { notifyStage: true });
    } else {
      const frameChanged = nextFrame !== state.currentFrame;
      commitSeek(nextTime, nextFrame, { notifyStage: false });
      if (!mp4SeekPending && (frameChanged || nextFrame !== mp4DispatchedFrame)) {
        dispatchMp4PlaybackSeek(nextTime, nextFrame, mp4SeekToken);
      }
    }

    rafId = typeof requestAnimationFrame === "function"
      ? requestAnimationFrame(tickPlayback)
      : setTimeout(() => tickPlayback(performance.now()), 16);
  }

  function play() {
    if (state.playing || destroyed) return;
    if (getEffectiveDuration() <= 0) {
      if (typeof onToast === "function") {
        onToast("No playable timeline duration available yet.", "info");
      }
      return;
    }
    state.playing = true;
    stage?.setPlaying?.(true);
    updatePlayButtonUI();
    lastTickMs = typeof performance !== "undefined" ? performance.now() : Date.now();
    rafId = typeof requestAnimationFrame === "function"
      ? requestAnimationFrame(tickPlayback)
      : setTimeout(() => tickPlayback(Date.now()), 16);
  }

  function pause({ syncStage = true } = {}) {
    const wasMp4Pending = mp4SeekPending;
    mp4SeekToken += 1;
    mp4SeekPending = false;
    if (!state.playing && rafId === null) return;
    state.playing = false;
    stage?.setPlaying?.(false);
    if (rafId !== null) {
      if (typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(rafId);
      } else {
        clearTimeout(rafId);
      }
      rafId = null;
    }
    updatePlayButtonUI();
    if (syncStage && !destroyed && wasMp4Pending && state.currentFrame !== mp4DispatchedFrame) {
      const stageState = stage && typeof stage.getState === "function" ? stage.getState() : {};
      if (stageState.mode !== "live" && stage && typeof stage.seekTime === "function") {
        mp4DispatchedFrame = state.currentFrame;
        try {
          Promise.resolve(stage.seekTime(state.currentTimeSec, state.currentFrame)).catch(() => {});
        } catch (_err) {}
      }
    }
  }

  function togglePlay() {
    if (state.playing) {
      pause();
    } else {
      play();
    }
  }

  function updateTiming(timing = {}) {
    const fps = toFiniteNumber(timing.fps);
    if (fps !== null && fps > 0) state.fps = fps;

    const totalFrames = toFiniteNumber(timing.totalFrames ?? timing.total_frames);
    if (totalFrames !== null && totalFrames >= 0) {
      state.totalFrames = Math.round(totalFrames);
    }

    const dur = toFiniteNumber(timing.durationSec ?? timing.duration_sec);
    if (dur !== null && dur >= 0) {
      state.durationSec = dur;
    } else if ((totalFrames !== null || state.durationSec <= 0) && state.totalFrames > 0 && state.fps > 0) {
      state.durationSec = state.totalFrames / state.fps;
    }

    if (state.totalFrames <= 0 && state.durationSec > 0 && state.fps > 0) {
      state.totalFrames = Math.max(1, Math.round(state.durationSec * state.fps));
    }

    const maxFrame = getMaxFrame();
    state.currentFrame = state.totalFrames > 0 ? clamp(state.currentFrame, 0, maxFrame) : 0;
    state.currentTimeSec = state.durationSec > 0 ? clamp(state.currentTimeSec, 0, state.durationSec) : 0;

    updateReadoutAndPlayhead();
    renderMarkers();
  }

  function setInfo(nextInfo = {}, { reloadWaveform = true } = {}) {
    currentInfo = nextInfo || {};
    const stageSt = stage && typeof stage.getState === "function" ? stage.getState() : {};
    const infoFps = toFiniteNumber(currentInfo.fps);
    const stageFps = toFiniteNumber(stageSt.fps);
    const fps = infoFps !== null && infoFps > 0 ? infoFps : (stageFps !== null && stageFps > 0 ? stageFps : 30);
    const totalFrames = toFiniteNumber(currentInfo.totalFrames ?? currentInfo.total_frames ?? stageSt.totalFrames) ?? 0;
    const rawDur = toFiniteNumber(currentInfo.duration_sec ?? currentInfo.durationSec ?? stageSt.durationSec);
    const durationSec = rawDur !== null && rawDur > 0 ? rawDur : (totalFrames > 0 ? totalFrames / fps : 0);

    updateTiming({ fps, totalFrames, durationSec });
    updateLoopPill(currentInfo);
    if (reloadWaveform) {
      refreshWaveform(currentInfo);
    }
  }

  function destroy() {
    destroyed = true;
    pause({ syncStage: false });
    if (waveformAbort) {
      try {
        waveformAbort.abort();
      } catch (_err) {}
      waveformAbort = null;
    }
    if (trackResizeObserver && typeof trackResizeObserver.disconnect === "function") {
      trackResizeObserver.disconnect();
      trackResizeObserver = null;
    }
    if (abortCtrl) {
      abortCtrl.abort();
    }
  }

  // ---------- Event Wiring ----------
  const addEvt = (el, type, handler) => {
    if (!el || typeof el.addEventListener !== "function") return;
    el.addEventListener(type, handler, sig ? { signal: sig } : undefined);
  };

  addEvt(els.btnPlay, "click", () => togglePlay());
  addEvt(els.btnPrev1, "click", () => stepFrames(-1));
  addEvt(els.btnNext1, "click", () => stepFrames(1));
  addEvt(els.btnPrev10, "click", () => stepFrames(-10));
  addEvt(els.btnNext10, "click", () => stepFrames(10));

  addEvt(els.scrubber, "input", () => {
    pause({ syncStage: false });
    const val = toFiniteNumber(els.scrubber?.value);
    if (val !== null) {
      seekToFrame(val);
    }
  });
  addEvt(els.scrubber, "pointerup", () => {
    els.scrubber?.blur?.();
  });

  if (typeof window !== "undefined") {
    addEvt(window, "kinearc:modechange", () => {
      mp4SeekToken += 1;
      mp4SeekPending = false;
      mp4DispatchedFrame = state.currentFrame;
    });
    addEvt(window, "keydown", (evt) => {
      if (evt.ctrlKey || evt.metaKey || evt.altKey) return;
      if (shouldIgnoreShortcutTarget(evt.target)) return;

      if (evt.code === "Space" || evt.key === " ") {
        evt.preventDefault?.();
        togglePlay();
      } else if (evt.key === "ArrowLeft") {
        evt.preventDefault?.();
        stepFrames(evt.shiftKey ? -10 : -1);
      } else if (evt.key === "ArrowRight") {
        evt.preventDefault?.();
        stepFrames(evt.shiftKey ? 10 : 1);
      }
    });
    addEvt(window, "resize", () => drawWaveform());
  }

  if (typeof ResizeObserver === "function" && els.timelineTrack) {
    trackResizeObserver = new ResizeObserver(() => drawWaveform());
    trackResizeObserver.observe(els.timelineTrack);
  }

  updatePlayButtonUI();
  const hasInitialInfo = Boolean(info && typeof info === "object" && Object.keys(info).length > 0);
  setInfo(currentInfo, { reloadWaveform: hasInitialInfo });

  return {
    play,
    pause,
    togglePlay,
    stepFrames,
    seekToFrame,
    seekToTime,
    updateTiming,
    setInfo,
    refreshWaveform: () => refreshWaveform(currentInfo),
    drawWaveform,
    getState: () => ({ ...state }),
    destroy,
  };
}
