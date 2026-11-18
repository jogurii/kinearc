/**
 * annotations.js — Stage Click/Box Pinning, Overlay Drawing & Notes CRUD for kinearc
 */

import { toFiniteNumber, shouldIgnoreShortcutTarget, computeMarkerPercent } from "./timeline.js";

function clamp(val, min, max) {
  return Math.min(max, Math.max(min, val));
}

export function normalizeBox(p0, p1) {
  const x0 = Math.round(Math.min(toFiniteNumber(p0?.[0]) ?? 0, toFiniteNumber(p1?.[0]) ?? 0));
  const y0 = Math.round(Math.min(toFiniteNumber(p0?.[1]) ?? 0, toFiniteNumber(p1?.[1]) ?? 0));
  const x1 = Math.round(Math.max(toFiniteNumber(p0?.[0]) ?? 0, toFiniteNumber(p1?.[0]) ?? 0));
  const y1 = Math.round(Math.max(toFiniteNumber(p0?.[1]) ?? 0, toFiniteNumber(p1?.[1]) ?? 0));
  return [x0, y0, x1, y1];
}

export function formatSelectionTarget({
  frame = 0,
  timeSec = 0,
  endFrame = null,
  endTimeSec = null,
  bbox = null,
  point = null,
} = {}) {
  const fNum = toFiniteNumber(frame);
  const tNum = toFiniteNumber(timeSec);
  const efNum = toFiniteNumber(endFrame);
  const etNum = toFiniteNumber(endTimeSec);
  const f = fNum !== null ? Math.max(0, Math.round(fNum)) : 0;
  const t = tNum !== null ? Math.max(0, tNum).toFixed(2) : "0.00";
  const hasRange = efNum !== null && Math.round(efNum) > f;
  const ef = hasRange ? Math.round(efNum) : f;
  const et = etNum !== null ? Math.max(0, etNum).toFixed(2) : t;
  const prefix = hasRange ? `Range f${f}–f${ef} (${t}s–${et}s)` : `Frame f${f} (${t}s)`;

  if (Array.isArray(bbox) && bbox.length === 4) {
    return `${prefix} · Box [${bbox.join(", ")}]`;
  }
  if (Array.isArray(point) && point.length === 2) {
    return `${prefix} · Point (${point[0]}, ${point[1]})`;
  }
  return `${prefix} · ${hasRange ? "Clip range" : "Full frame"}`;
}

export function buildRevisionPrompt({ outDir = "", notes = [] } = {}) {
  const cleanDir = typeof outDir === "string" && outDir.trim()
    ? outDir.trim().replace(/[\\/]+$/, "")
    : ".kinearc_analysis";
  const selectionPath = `${cleanDir}/selection.json`;
  const allNotes = Array.isArray(notes) ? notes : [];
  const openNotes = allNotes.filter((n) => n && n.status !== "done");

  const lines = [
    `Apply the ${openNotes.length} open kinearc visual revision note(s) saved in \`${selectionPath}\`:`,
    "",
  ];

  if (openNotes.length === 0) {
    lines.push(
      allNotes.length > 0
        ? `All ${allNotes.length} recorded note(s) are marked done. Re-audit frames if further adjustments are needed.`
        : "No open notes are currently pinned. Inspect frames in kinearc or add revision pins first."
    );
  } else {
    for (const n of openNotes) {
      const fNum = Math.max(0, Math.round(toFiniteNumber(n.frame) ?? 0));
      const efNum = toFiniteNumber(n.end_frame);
      const hasRange = efNum !== null && Math.round(efNum) > fNum;
      const tNum = toFiniteNumber(n.time_sec);
      const tVal = tNum !== null ? tNum.toFixed(2) : "0.00";
      const etNum = toFiniteNumber(n.end_time_sec);
      const etVal = etNum !== null ? etNum.toFixed(2) : tVal;
      const timeLoc = hasRange
        ? `f${fNum}–f${Math.round(efNum)} (${tVal}s–${etVal}s)`
        : `f${fNum} (${tVal}s)`;
      let targetDesc = hasRange ? "Clip range" : "Full frame";
      if (Array.isArray(n.bbox) && n.bbox.length === 4) {
        targetDesc = `Box [${n.bbox.join(", ")}]`;
      } else if (Array.isArray(n.point) && n.point.length === 2) {
        targetDesc = `Point (${n.point[0]}, ${n.point[1]})`;
      }
      const imgNote = n.image ? ` · snapshot: ${cleanDir}/${String(n.image).replace(/^\/+/, "")}` : "";
      const body = String(n.text || "").trim() || "(see snapshot)";
      lines.push(`- Note #${n.id} @ ${timeLoc} · ${targetDesc}${imgNote}: ${body}`);
    }
  }

  return lines.join("\n");
}

function drawBadge(ctx, x, y, text, color, scale) {
  const padX = Math.round(7 * scale);
  const h = Math.round(20 * scale);
  const fontPx = Math.max(10, Math.round(11 * scale));
  ctx.save();
  ctx.font = `700 ${fontPx}px ui-monospace, "SFMono-Regular", Menlo, monospace`;
  const textW = typeof ctx.measureText === "function" ? ctx.measureText(text).width : String(text).length * fontPx * 0.62;
  const boxW = Math.round(textW + padX * 2);
  ctx.fillStyle = "rgba(11, 13, 19, 0.88)";
  ctx.fillRect(x, y, boxW, h);
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1, Math.round(scale));
  ctx.strokeRect(x, y, boxW, h);
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + padX, y + h / 2);
  ctx.restore();
}

function drawAnnotationMarker(ctx, { bbox, point, xOffset = 0, width = 1080, height = 1920, color, label }) {
  const refW = Math.max(1, toFiniteNumber(width) ?? 1080);
  const refH = Math.max(1, toFiniteNumber(height) ?? 1920);
  const scale = clamp(refW / 1080, 0.65, 2.2);
  const lineW = Math.max(2, Math.round(3 * scale));
  const badgeH = Math.round(20 * scale);

  ctx.save();
  if (Array.isArray(bbox) && bbox.length === 4) {
    const nums = bbox.map(toFiniteNumber);
    if (nums.some((v) => v === null)) {
      ctx.restore();
      return;
    }
    const [x0, y0, x1, y1] = nums;
    const rx = xOffset + x0;
    const rw = Math.max(2, x1 - x0);
    const rh = Math.max(2, y1 - y0);

    ctx.fillStyle = color;
    ctx.globalAlpha = 0.14;
    ctx.fillRect(rx, y0, rw, rh);

    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    ctx.lineWidth = lineW;
    ctx.strokeRect(rx, y0, rw, rh);

    const badgeY = y0 >= badgeH + 4 ? y0 - badgeH - 3 : clamp(y0 + 3, 0, Math.max(0, refH - badgeH));
    drawBadge(ctx, rx, badgeY, label, color, scale);
  } else if (Array.isArray(point) && point.length === 2) {
    const pxRaw = toFiniteNumber(point[0]);
    const pyRaw = toFiniteNumber(point[1]);
    if (pxRaw === null || pyRaw === null) {
      ctx.restore();
      return;
    }
    const px = xOffset + pxRaw;
    const py = pyRaw;
    const radius = Math.max(10, Math.round(18 * scale));

    ctx.strokeStyle = color;
    ctx.lineWidth = lineW;
    if (typeof ctx.beginPath === "function" && typeof ctx.arc === "function") {
      ctx.beginPath();
      ctx.arc(px, py, radius, 0, Math.PI * 2);
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(px, py, Math.max(2.5, radius * 0.2), 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    } else {
      ctx.strokeRect(px - radius, py - radius, radius * 2, radius * 2);
    }

    const badgeX = clamp(px + radius + 5, xOffset + 2, xOffset + Math.max(2, refW - 60 * scale));
    const badgeY = clamp(py - badgeH / 2, 2, Math.max(2, refH - badgeH - 2));
    drawBadge(ctx, badgeX, badgeY, label, color, scale);
  }
  ctx.restore();
}

async function copyToClipboard(text) {
  if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_err) {
      // Fallback to textarea execCommand below
    }
  }
  if (typeof document === "undefined" || !document.body) return false;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = typeof document.execCommand === "function" ? Boolean(document.execCommand("copy")) : false;
  } catch (_err) {
    ok = false;
  } finally {
    ta.remove();
  }
  return ok;
}

function resolveElements(overrides = {}) {
  const byId = (id) => (typeof document !== "undefined" ? document.getElementById(id) : null);
  return {
    overlayCanvas: overrides.overlayCanvas ?? byId("overlayCanvas"),
    selectionTarget: overrides.selectionTarget ?? byId("selectionTarget"),
    btnClearSel: overrides.btnClearSel ?? byId("btnClearSel"),
    noteInput: overrides.noteInput ?? byId("noteInput"),
    btnSaveNote: overrides.btnSaveNote ?? byId("btnSaveNote"),
    btnCopyRevision: overrides.btnCopyRevision ?? byId("btnCopyRevision"),
    btnCopyPrompt: overrides.btnCopyPrompt ?? byId("btnCopyPrompt"),
    notesList: overrides.notesList ?? byId("notesList"),
    btnSetIn: overrides.btnSetIn ?? byId("btnSetIn"),
    btnSetOut: overrides.btnSetOut ?? byId("btnSetOut"),
    rangePill: overrides.rangePill ?? byId("rangePill"),
    rangeSelectionBar: overrides.rangeSelectionBar ?? byId("rangeSelectionBar"),
    timelineTrack: overrides.timelineTrack ?? byId("timelineTrack"),
    markersLayer: overrides.markersLayer ?? byId("markersLayer"),
  };
}

export function createAnnotations({
  stage,
  timeline = null,
  info = {},
  getCurrentFrame = null,
  onSeek = null,
  onPause = null,
  onToast = null,
  elements = {},
} = {}) {
  const els = resolveElements(elements);
  const abortCtrl = typeof AbortController !== "undefined" ? new AbortController() : null;
  const sig = abortCtrl ? abortCtrl.signal : undefined;

  let currentInfo = info || {};
  let notes = [];
  let activePoint = null;
  let activeBox = null;
  let activeRange = null;
  let frameContext = { frame: 0, timeSec: 0 };

  let dragging = false;
  let startClientX = 0;
  let startClientY = 0;
  let startFramePt = [0, 0];

  let rangeDragging = false;
  let rangeStartAnchorFrame = 0;

  function getTimelineMetrics() {
    const tlSt = timeline && typeof timeline.getState === "function" ? timeline.getState() : {};
    const st = stage && typeof stage.getState === "function" ? stage.getState() : {};
    const fpsVal = toFiniteNumber(tlSt.fps ?? st.fps ?? currentInfo?.fps);
    const fps = fpsVal !== null && fpsVal > 0 ? fpsVal : 30;
    const tfVal = toFiniteNumber(tlSt.totalFrames ?? st.totalFrames ?? currentInfo?.total_frames ?? currentInfo?.totalFrames);
    const totalFrames = tfVal !== null && tfVal > 0 ? Math.round(tfVal) : 0;
    const durVal = toFiniteNumber(tlSt.durationSec ?? st.durationSec ?? currentInfo?.duration_sec ?? currentInfo?.durationSec);
    const durationSec = durVal !== null && durVal > 0 ? durVal : (totalFrames > 0 ? totalFrames / fps : 0);
    const maxFrame = totalFrames > 0 ? totalFrames - 1 : 0;
    return { fps, totalFrames, durationSec, maxFrame };
  }

  function resolveFrameAndTime() {
    if (typeof getCurrentFrame === "function") {
      const res = getCurrentFrame();
      const resNum = toFiniteNumber(res);
      if (resNum !== null) {
        const { fps } = getTimelineMetrics();
        const st = stage && typeof stage.getState === "function" ? stage.getState() : {};
        const stT = toFiniteNumber(st.currentTimeSec);
        return {
          frame: Math.max(0, Math.round(resNum)),
          timeSec: stT !== null ? Math.max(0, stT) : Math.max(0, resNum / fps),
        };
      }
      if (res && typeof res === "object") {
        const f = toFiniteNumber(res.currentFrame ?? res.frame ?? frameContext.frame);
        const t = toFiniteNumber(res.currentTimeSec ?? res.timeSec ?? frameContext.timeSec);
        return {
          frame: f !== null ? Math.max(0, Math.round(f)) : 0,
          timeSec: t !== null ? Math.max(0, t) : 0,
        };
      }
    }
    const st = stage && typeof stage.getState === "function" ? stage.getState() : {};
    const stF = toFiniteNumber(st.currentFrameIdx);
    const stT = toFiniteNumber(st.currentTimeSec);
    return {
      frame: stF !== null ? Math.max(0, Math.round(stF)) : frameContext.frame,
      timeSec: stT !== null ? Math.max(0, stT) : frameContext.timeSec,
    };
  }

  function updateRangeTimelineUI() {
    const bar = els.rangeSelectionBar;
    const pill = els.rangePill;
    const { fps, totalFrames, durationSec } = getTimelineMetrics();

    if (!activeRange || activeRange.endFrame <= activeRange.startFrame) {
      if (bar) bar.classList.add("hidden");
      if (pill) {
        pill.classList.add("hidden");
        pill.textContent = "";
      }
    } else {
      const leftPct = computeMarkerPercent({
        frame: activeRange.startFrame,
        timeSec: activeRange.startTimeSec,
        totalFrames,
        durationSec,
        fps,
      });
      const rightPct = computeMarkerPercent({
        frame: activeRange.endFrame,
        timeSec: activeRange.endTimeSec,
        totalFrames,
        durationSec,
        fps,
      });
      if (bar) {
        bar.classList.remove("hidden");
        if (bar.style) {
          bar.style.left = `${leftPct.toFixed(3)}%`;
          bar.style.width = `${Math.max(0.8, rightPct - leftPct).toFixed(3)}%`;
        }
      }
      if (pill) {
        pill.classList.remove("hidden");
        pill.textContent = `Clip f${activeRange.startFrame}–f${activeRange.endFrame} ×`;
      }
    }

    renderTimelineNoteRanges();
  }

  function renderTimelineNoteRanges() {
    const layer = els.markersLayer;
    if (!layer) return;
    const doc = layer.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!doc) return;

    // Remove previously rendered note-range bars without touching cut/worst/sfx markers
    const existingChildren = Array.from(layer.children || []);
    const kept = existingChildren.filter((c) => !c?.className || !String(c.className).includes("timeline-note-range"));
    if (kept.length !== existingChildren.length) {
      if (typeof layer.replaceChildren === "function") {
        layer.replaceChildren(...kept);
      } else if (Array.isArray(layer.children)) {
        layer.children = kept;
      }
    }

    const { fps, totalFrames, durationSec } = getTimelineMetrics();
    for (const n of notes) {
      if (!n) continue;
      const startF = toFiniteNumber(n.frame);
      const endF = toFiniteNumber(n.end_frame);
      if (startF === null || endF === null || Math.round(endF) <= Math.round(startF)) continue;

      const sFrame = Math.max(0, Math.round(startF));
      const eFrame = Math.max(sFrame + 1, Math.round(endF));
      const leftPct = computeMarkerPercent({ frame: sFrame, totalFrames, durationSec, fps });
      const rightPct = computeMarkerPercent({ frame: eFrame, totalFrames, durationSec, fps });

      const span = doc.createElement("button");
      span.type = "button";
      span.className = `timeline-note-range${n.status === "done" ? " done" : ""}`;
      if (span.style) {
        span.style.left = `${leftPct.toFixed(3)}%`;
        span.style.width = `${Math.max(1.0, rightPct - leftPct).toFixed(3)}%`;
      }
      const label = `#${n.id} · f${sFrame}–f${eFrame}${n.text ? `: ${n.text}` : ""} (right-click to delete)`;
      span.title = label;
      span.setAttribute?.("aria-label", label);
      span.dataset.noteId = String(n.id);

      span.addEventListener("click", (evt) => {
        evt.stopPropagation?.();
        if (typeof onPause === "function") {
          onPause();
        } else {
          timeline?.pause?.();
        }
        if (typeof onSeek === "function") {
          onSeek(sFrame);
        } else {
          stage?.seekTime?.(null, sFrame);
        }
      });

      span.addEventListener("contextmenu", (evt) => {
        evt.preventDefault?.();
        evt.stopPropagation?.();
        deleteNote(n.id);
      });

      layer.appendChild(span);
    }
  }

  function setRange(startFrame, endFrame) {
    const { fps, maxFrame } = getTimelineMetrics();
    const sRaw = toFiniteNumber(startFrame);
    const eRaw = toFiniteNumber(endFrame);
    if (sRaw === null || eRaw === null) {
      activeRange = null;
      updateRangeTimelineUI();
      updateSelectionReadout();
      stage?.redrawOverlay?.();
      return;
    }
    const f0 = maxFrame > 0 ? clamp(Math.round(Math.min(sRaw, eRaw)), 0, maxFrame) : Math.max(0, Math.round(Math.min(sRaw, eRaw)));
    const f1 = maxFrame > 0 ? clamp(Math.round(Math.max(sRaw, eRaw)), 0, maxFrame) : Math.max(0, Math.round(Math.max(sRaw, eRaw)));
    if (f1 <= f0) {
      activeRange = null;
    } else {
      activeRange = {
        startFrame: f0,
        endFrame: f1,
        startTimeSec: Number((f0 / fps).toFixed(3)),
        endTimeSec: Number((f1 / fps).toFixed(3)),
      };
    }
    updateRangeTimelineUI();
    updateSelectionReadout();
    stage?.redrawOverlay?.();
  }

  function setInPoint() {
    const { frame } = resolveFrameAndTime();
    const { fps, maxFrame } = getTimelineMetrics();
    const spanDefault = Math.max(1, Math.round(fps * 0.25));
    const currentOut = activeRange ? activeRange.endFrame : null;
    const nextOut = currentOut !== null && currentOut > frame
      ? currentOut
      : (maxFrame > 0 ? Math.min(maxFrame, frame + spanDefault) : frame + spanDefault);
    if (nextOut <= frame && frame > 0) {
      setRange(Math.max(0, frame - spanDefault), frame);
    } else {
      setRange(frame, Math.max(frame + 1, nextOut));
    }
    if (typeof onToast === "function" && activeRange) {
      onToast(`Clip range In set: f${activeRange.startFrame}–f${activeRange.endFrame}`, "info");
    }
  }

  function setOutPoint() {
    const { frame } = resolveFrameAndTime();
    const { fps } = getTimelineMetrics();
    const spanDefault = Math.max(1, Math.round(fps * 0.25));
    const currentIn = activeRange ? activeRange.startFrame : null;
    const nextIn = currentIn !== null && currentIn < frame
      ? currentIn
      : Math.max(0, frame - spanDefault);
    if (frame <= nextIn) {
      setRange(frame, frame + spanDefault);
    } else {
      setRange(nextIn, frame);
    }
    if (typeof onToast === "function" && activeRange) {
      onToast(`Clip range Out set: f${activeRange.startFrame}–f${activeRange.endFrame}`, "info");
    }
  }

  function updateSelectionReadout() {
    if (!els.selectionTarget) return;
    const { frame, timeSec } = resolveFrameAndTime();
    const useRange = activeRange && activeRange.endFrame > activeRange.startFrame;
    els.selectionTarget.textContent = formatSelectionTarget({
      frame: useRange ? activeRange.startFrame : frame,
      timeSec: useRange ? activeRange.startTimeSec : timeSec,
      endFrame: useRange ? activeRange.endFrame : null,
      endTimeSec: useRange ? activeRange.endTimeSec : null,
      bbox: activeBox,
      point: activePoint,
    });
  }

  function clearSelection() {
    activePoint = null;
    activeBox = null;
    activeRange = null;
    updateRangeTimelineUI();
    updateSelectionReadout();
    stage?.redrawOverlay?.();
  }

  function isNoteVisibleAtFrame(n, targetFrame) {
    if (!n) return false;
    const noteFrameNum = toFiniteNumber(n.frame);
    if (noteFrameNum === null) return false;
    const sFrame = Math.round(noteFrameNum);
    const endFrameNum = toFiniteNumber(n.end_frame);
    const eFrame = endFrameNum !== null && Math.round(endFrameNum) > sFrame ? Math.round(endFrameNum) : sFrame;
    return targetFrame >= sFrame && targetFrame <= eFrame;
  }

  function drawOverlay({ ctx, frameIdx, xOffset = 0, width = 1080, height = 1920 } = {}) {
    if (!ctx) return;
    const refW = Math.max(1, toFiniteNumber(width) ?? 1080);
    const scale = clamp(refW / 1080, 0.65, 2.2);
    const targetNum = toFiniteNumber(frameIdx);
    if (targetNum !== null) {
      const targetFrame = Math.round(targetNum);
      let clipBadgeOffset = 0;
      for (const n of notes) {
        if (!isNoteVisibleAtFrame(n, targetFrame)) continue;
        const sFrame = Math.round(toFiniteNumber(n.frame) ?? 0);
        const efNum = toFiniteNumber(n.end_frame);
        const hasRange = efNum !== null && Math.round(efNum) > sFrame;
        const color = n.status === "done" ? "#3ad29f" : "#ffb454";
        const label = hasRange ? `#${n.id} · f${sFrame}–f${Math.round(efNum)}` : `#${n.id}`;
        if ((Array.isArray(n.bbox) && n.bbox.length === 4) || (Array.isArray(n.point) && n.point.length === 2)) {
          drawAnnotationMarker(ctx, {
            bbox: n.bbox,
            point: n.point,
            xOffset,
            width,
            height,
            color,
            label,
          });
        } else if (hasRange) {
          const badgeY = Math.round(14 * scale + clipBadgeOffset * 26 * scale);
          clipBadgeOffset += 1;
          const shortText = n.text ? ` · ${String(n.text).slice(0, 28)}` : "";
          drawBadge(ctx, xOffset + Math.round(14 * scale), badgeY, `CLIP ${label}${shortText}`, color, scale);
        }
      }
    }

    if (activeBox || activePoint) {
      const rangeSuffix = activeRange && activeRange.endFrame > activeRange.startFrame
        ? ` · f${activeRange.startFrame}–f${activeRange.endFrame}`
        : "";
      drawAnnotationMarker(ctx, {
        bbox: activeBox,
        point: activePoint,
        xOffset,
        width,
        height,
        color: "#ff5d7a",
        label: `NEW${rangeSuffix}`,
      });
    } else if (activeRange && activeRange.endFrame > activeRange.startFrame) {
      drawBadge(
        ctx,
        xOffset + Math.round(14 * scale),
        Math.round(14 * scale),
        `NEW CLIP f${activeRange.startFrame}–f${activeRange.endFrame}`,
        "#ff5d7a",
        scale
      );
    }
  }

  function renderNotesList() {
    const list = els.notesList;
    if (!list) return;
    if (typeof list.replaceChildren === "function") {
      list.replaceChildren();
    } else {
      list.innerHTML = "";
    }

    const doc = list.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!doc) return;

    if (!Array.isArray(notes) || notes.length === 0) {
      const empty = doc.createElement("div");
      empty.className = "empty-hint";
      empty.textContent = "No revision notes yet. Click or drag on the stage to pin a spot.";
      list.appendChild(empty);
      return;
    }

    for (const n of notes) {
      const card = doc.createElement("div");
      card.className = `note-card${n.status === "done" ? " done" : ""}`;
      card.dataset.noteId = String(n.id);

      const top = doc.createElement("div");
      top.className = "note-top";
      const meta = doc.createElement("span");
      meta.className = "tabular";
      const fNum = Math.max(0, Math.round(toFiniteNumber(n.frame) ?? 0));
      const efNum = toFiniteNumber(n.end_frame);
      const hasRange = efNum !== null && Math.round(efNum) > fNum;
      const tNum = toFiniteNumber(n.time_sec);
      const tVal = tNum !== null ? tNum.toFixed(2) : "0.00";
      const etNum = toFiniteNumber(n.end_time_sec);
      const etVal = etNum !== null ? etNum.toFixed(2) : tVal;
      meta.textContent = hasRange
        ? `#${n.id} · f${fNum}–f${Math.round(efNum)} (${tVal}s–${etVal}s)`
        : `#${n.id} · f${fNum} (${tVal}s)`;
      const statusBadge = doc.createElement("span");
      statusBadge.className = `note-status ${n.status === "done" ? "done" : "open"}`;
      statusBadge.textContent = n.status === "done" ? "Done" : "Open";
      top.appendChild(meta);
      top.appendChild(statusBadge);
      card.appendChild(top);

      if (n.image) {
        const img = doc.createElement("img");
        img.className = "note-thumb";
        img.src = `/${String(n.image).replace(/^\/+/, "")}`;
        img.alt = `Note #${n.id} snapshot`;
        img.loading = "lazy";
        card.appendChild(img);
      }

      if (Array.isArray(n.bbox) && n.bbox.length === 4) {
        const coord = doc.createElement("div");
        coord.className = "note-coord tabular";
        coord.textContent = hasRange
          ? `Clip f${fNum}–f${Math.round(efNum)} · Box [${n.bbox.join(", ")}]`
          : `Box [${n.bbox.join(", ")}]`;
        card.appendChild(coord);
      } else if (Array.isArray(n.point) && n.point.length === 2) {
        const coord = doc.createElement("div");
        coord.className = "note-coord tabular";
        coord.textContent = hasRange
          ? `Clip f${fNum}–f${Math.round(efNum)} · Point (${n.point[0]}, ${n.point[1]})`
          : `Point (${n.point[0]}, ${n.point[1]})`;
        card.appendChild(coord);
      } else if (hasRange) {
        const coord = doc.createElement("div");
        coord.className = "note-coord tabular";
        coord.textContent = `Clip range f${fNum}–f${Math.round(efNum)} (${tVal}s–${etVal}s)`;
        card.appendChild(coord);
      }

      const txt = doc.createElement("div");
      txt.className = "note-text";
      txt.textContent = n.text || "(No text)";
      card.appendChild(txt);

      const actions = doc.createElement("div");
      actions.className = "note-actions";

      const btnToggle = doc.createElement("button");
      btnToggle.type = "button";
      btnToggle.className = "ghost-btn";
      btnToggle.textContent = n.status === "done" ? "Reopen" : "Done";
      btnToggle.addEventListener("click", (evt) => {
        evt.stopPropagation?.();
        toggleNoteStatus(n);
      });

      const btnDelete = doc.createElement("button");
      btnDelete.type = "button";
      btnDelete.className = "ghost-btn danger";
      btnDelete.textContent = "Delete";
      btnDelete.addEventListener("click", (evt) => {
        evt.stopPropagation?.();
        deleteNote(n.id);
      });

      actions.appendChild(btnToggle);
      actions.appendChild(btnDelete);
      card.appendChild(actions);

      card.addEventListener("click", () => {
        const targetFrame = Math.max(0, Math.round(toFiniteNumber(n.frame) ?? 0));
        if (typeof onPause === "function") {
          onPause();
        } else {
          timeline?.pause?.();
        }
        if (typeof onSeek === "function") {
          onSeek(targetFrame);
        } else {
          stage?.seekTime?.(null, targetFrame);
        }
      });

      list.appendChild(card);
    }
  }

  async function loadNotes() {
    if (typeof fetch !== "function") return [];
    try {
      const res = await fetch("/api/notes", { cache: "no-store" });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      notes = Array.isArray(data) ? data : [];
      renderNotesList();
      renderTimelineNoteRanges();
      stage?.redrawOverlay?.();
      return notes;
    } catch (err) {
      if (typeof onToast === "function") {
        onToast(`Failed to load notes: ${err.message}`, "error");
      }
      return notes;
    }
  }

  async function saveNote() {
    const rawText = els.noteInput ? String(els.noteInput.value || "").trim() : "";
    const useRange = Boolean(activeRange && activeRange.endFrame > activeRange.startFrame);
    if (!rawText && !activeBox && !activePoint && !useRange) {
      if (typeof onToast === "function") {
        onToast("Type a revision note, pin a spot on stage, or set an [ In / Out ] clip range first.", "error");
      }
      els.noteInput?.focus?.();
      return null;
    }

    const { frame, timeSec } = resolveFrameAndTime();
    const targetFrame = useRange ? activeRange.startFrame : frame;
    const targetTimeSec = useRange ? activeRange.startTimeSec : timeSec;
    const payloadBody = {
      frame: targetFrame,
      time_sec: targetTimeSec,
      bbox: activeBox,
      point: activePoint,
      text: rawText,
    };
    if (useRange) {
      payloadBody.end_frame = activeRange.endFrame;
      payloadBody.end_time_sec = activeRange.endTimeSec;
    }

    if (els.btnSaveNote) els.btnSaveNote.disabled = true;
    try {
      const res = await fetch("/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadBody),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload.error || `HTTP ${res.status}`);
      }

      const savedRangeLabel = useRange ? `f${activeRange.startFrame}–f${activeRange.endFrame}` : `f${targetFrame}`;
      activeBox = null;
      activePoint = null;
      activeRange = null;
      if (els.noteInput) els.noteInput.value = "";
      updateRangeTimelineUI();
      updateSelectionReadout();
      await loadNotes();
      if (typeof onToast === "function") {
        onToast(`Saved note #${payload.id} @ ${savedRangeLabel}`, "ok");
      }
      return payload;
    } catch (err) {
      if (typeof onToast === "function") {
        onToast(`Save note failed: ${err.message}`, "error");
      }
      return null;
    } finally {
      if (els.btnSaveNote) els.btnSaveNote.disabled = false;
    }
  }

  async function toggleNoteStatus(note) {
    if (!note) return;
    const nextStatus = note.status === "done" ? "open" : "done";
    try {
      const res = await fetch(`/api/notes/${note.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload.error || `HTTP ${res.status}`);
      }
      await loadNotes();
      if (typeof onToast === "function") {
        onToast(`Note #${note.id} marked ${nextStatus}`, "ok");
      }
    } catch (err) {
      if (typeof onToast === "function") {
        onToast(`Update note failed: ${err.message}`, "error");
      }
    }
  }

  async function deleteNote(noteId) {
    try {
      const res = await fetch(`/api/notes/${noteId}`, { method: "DELETE" });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload.error || `HTTP ${res.status}`);
      }
      await loadNotes();
      if (typeof onToast === "function") {
        onToast(`Deleted note #${noteId}`, "ok");
      }
    } catch (err) {
      if (typeof onToast === "function") {
        onToast(`Delete note failed: ${err.message}`, "error");
      }
    }
  }

  async function copyRevisionPrompt() {
    const prompt = buildRevisionPrompt({
      outDir: currentInfo?.out_dir || "",
      notes,
    });
    const openCount = notes.filter((n) => n && n.status !== "done").length;
    const copied = await copyToClipboard(prompt);
    if (typeof onToast === "function") {
      if (copied) {
        onToast(`Copied AI prompt (${openCount} open note(s))`, "ok");
      } else {
        onToast("Clipboard unavailable — unable to copy prompt.", "error");
      }
    }
    return prompt;
  }

  function setFrameContext(pos = {}) {
    const fVal = toFiniteNumber(pos.frame);
    if (fVal !== null) {
      frameContext.frame = Math.max(0, Math.round(fVal));
    }
    const tVal = toFiniteNumber(pos.timeSec);
    if (tVal !== null) {
      frameContext.timeSec = Math.max(0, tVal);
    }
    updateSelectionReadout();
  }

  function setInfo(nextInfo = {}) {
    currentInfo = nextInfo || {};
    updateRangeTimelineUI();
    updateSelectionReadout();
  }

  function destroy() {
    if (abortCtrl) {
      abortCtrl.abort();
    }
    stage?.setAnnotationsDrawer?.(null);
  }

  function findHitNoteAtPoint(fx, fy, targetFrame) {
    const st = stage && typeof stage.getState === "function" ? stage.getState() : {};
    const refW = Math.max(1, toFiniteNumber(st.width) ?? 1080);
    const scale = clamp(refW / 1080, 0.65, 2.2);
    const hitRadius = Math.max(20, Math.round(28 * scale));
    const pad = Math.round(12 * scale);

    let clipBadgeOffset = 0;
    const candidates = [];
    for (const n of notes) {
      if (!isNoteVisibleAtFrame(n, targetFrame)) continue;
      const sFrame = Math.round(toFiniteNumber(n.frame) ?? 0);
      const efNum = toFiniteNumber(n.end_frame);
      const hasRange = efNum !== null && Math.round(efNum) > sFrame;
      let badgeBox = null;
      if (!(Array.isArray(n.bbox) && n.bbox.length === 4) && !(Array.isArray(n.point) && n.point.length === 2) && hasRange) {
        const by = Math.round(14 * scale + clipBadgeOffset * 26 * scale);
        clipBadgeOffset += 1;
        badgeBox = [Math.round(14 * scale), by, Math.round(320 * scale), by + Math.round(24 * scale)];
      }
      candidates.push({ note: n, badgeBox });
    }

    for (let i = candidates.length - 1; i >= 0; i--) {
      const { note: n, badgeBox } = candidates[i];
      if (Array.isArray(n.bbox) && n.bbox.length === 4) {
        const [x0, y0, x1, y1] = n.bbox.map((v) => toFiniteNumber(v) ?? 0);
        if (fx >= x0 - pad && fx <= x1 + pad && fy >= y0 - Math.round(24 * scale) && fy <= y1 + pad) {
          return n;
        }
      } else if (Array.isArray(n.point) && n.point.length === 2) {
        const px = toFiniteNumber(n.point[0]) ?? 0;
        const py = toFiniteNumber(n.point[1]) ?? 0;
        if (Math.hypot(fx - px, fy - py) <= hitRadius) {
          return n;
        }
      } else if (badgeBox) {
        const [bx0, by0, bx1, by1] = badgeBox;
        if (fx >= bx0 - pad && fx <= bx1 + pad && fy >= by0 - pad && fy <= by1 + pad) {
          return n;
        }
      }
    }
    return null;
  }

  function handleStageRightClick(evt) {
    evt.preventDefault?.();
    evt.stopPropagation?.();
    dragging = false;

    const [fx, fy] = stage?.toFrameCoords ? stage.toFrameCoords(evt.clientX, evt.clientY) : [0, 0];
    const st = stage && typeof stage.getState === "function" ? stage.getState() : {};
    const refW = Math.max(1, toFiniteNumber(st.width) ?? 1080);
    const scale = clamp(refW / 1080, 0.65, 2.2);
    const hitRadius = Math.max(20, Math.round(28 * scale));
    const pad = Math.round(12 * scale);

    if (Array.isArray(activeBox) && activeBox.length === 4) {
      const [x0, y0, x1, y1] = activeBox;
      if (fx >= x0 - pad && fx <= x1 + pad && fy >= y0 - Math.round(24 * scale) && fy <= y1 + pad) {
        activeBox = null;
        updateSelectionReadout();
        stage?.redrawOverlay?.();
        if (typeof onToast === "function") onToast("Cleared draft box selection", "info");
        return;
      }
    }
    if (Array.isArray(activePoint) && activePoint.length === 2) {
      if (Math.hypot(fx - activePoint[0], fy - activePoint[1]) <= hitRadius) {
        activePoint = null;
        updateSelectionReadout();
        stage?.redrawOverlay?.();
        if (typeof onToast === "function") onToast("Cleared draft point selection", "info");
        return;
      }
    }

    const { frame } = resolveFrameAndTime();
    const hitNote = findHitNoteAtPoint(fx, fy, frame);
    if (hitNote) {
      deleteNote(hitNote.id);
      return;
    }

    if (activeBox || activePoint) {
      activeBox = null;
      activePoint = null;
      updateSelectionReadout();
      stage?.redrawOverlay?.();
      if (typeof onToast === "function") onToast("Cleared draft selection", "info");
    }
  }

  // ---------- Event Wiring ----------
  const addEvt = (el, type, handler) => {
    if (!el || typeof el.addEventListener !== "function") return;
    el.addEventListener(type, handler, sig ? { signal: sig } : undefined);
  };

  if (els.overlayCanvas) {
    addEvt(els.overlayCanvas, "contextmenu", (evt) => {
      handleStageRightClick(evt);
    });

    addEvt(els.overlayCanvas, "pointerdown", (evt) => {
      if (evt.button === 2) {
        evt.preventDefault?.();
        return;
      }
      if (evt.button !== undefined && evt.button !== 0) return;
      dragging = true;
      startClientX = evt.clientX;
      startClientY = evt.clientY;
      startFramePt = stage?.toFrameCoords ? stage.toFrameCoords(evt.clientX, evt.clientY) : [0, 0];
      try {
        els.overlayCanvas.setPointerCapture?.(evt.pointerId);
      } catch (_err) {}
    });

    addEvt(els.overlayCanvas, "pointermove", (evt) => {
      if (!dragging) return;
      const dist = Math.hypot(evt.clientX - startClientX, evt.clientY - startClientY);
      if (dist >= 6) {
        const endPt = stage?.toFrameCoords ? stage.toFrameCoords(evt.clientX, evt.clientY) : startFramePt;
        activePoint = null;
        activeBox = normalizeBox(startFramePt, endPt);
        updateSelectionReadout();
        stage?.redrawOverlay?.();
      }
    });

    const finishPointer = (evt) => {
      if (!dragging) return;
      dragging = false;
      try {
        els.overlayCanvas.releasePointerCapture?.(evt.pointerId);
      } catch (_err) {}
      const endPt = stage?.toFrameCoords ? stage.toFrameCoords(evt.clientX, evt.clientY) : startFramePt;
      const dist = Math.hypot(evt.clientX - startClientX, evt.clientY - startClientY);
      if (dist < 6) {
        activeBox = null;
        activePoint = endPt;
      } else {
        activePoint = null;
        activeBox = normalizeBox(startFramePt, endPt);
      }
      updateSelectionReadout();
      stage?.redrawOverlay?.();
    };

    addEvt(els.overlayCanvas, "pointerup", finishPointer);
    addEvt(els.overlayCanvas, "pointercancel", () => {
      dragging = false;
    });
  }

  function clientXToTimelineFrame(clientX) {
    const track = els.timelineTrack;
    if (!track || typeof track.getBoundingClientRect !== "function") return 0;
    const rect = track.getBoundingClientRect();
    if (!rect || !rect.width) return 0;
    const { maxFrame } = getTimelineMetrics();
    const ratio = clamp((clientX - rect.left) / rect.width, 0, 1);
    return Math.round(ratio * maxFrame);
  }

  if (els.timelineTrack) {
    addEvt(els.timelineTrack, "contextmenu", (evt) => {
      if (activeRange) {
        evt.preventDefault?.();
        activeRange = null;
        updateRangeTimelineUI();
        updateSelectionReadout();
        stage?.redrawOverlay?.();
        if (typeof onToast === "function") onToast("Cleared clip range selection", "info");
      }
    });

    addEvt(els.timelineTrack, "pointerdown", (evt) => {
      if (!evt.shiftKey || (evt.button !== undefined && evt.button !== 0)) return;
      evt.preventDefault?.();
      evt.stopPropagation?.();
      rangeDragging = true;
      rangeStartAnchorFrame = clientXToTimelineFrame(evt.clientX);
      setRange(rangeStartAnchorFrame, rangeStartAnchorFrame + 1);
    });

    addEvt(els.timelineTrack, "pointermove", (evt) => {
      if (!rangeDragging) return;
      const curF = clientXToTimelineFrame(evt.clientX);
      if (curF !== rangeStartAnchorFrame) {
        setRange(rangeStartAnchorFrame, curF);
      }
    });

    const endRangeDrag = () => {
      rangeDragging = false;
    };
    addEvt(els.timelineTrack, "pointerup", endRangeDrag);
    addEvt(els.timelineTrack, "pointercancel", endRangeDrag);
  }

  addEvt(els.btnSetIn, "click", () => setInPoint());
  addEvt(els.btnSetOut, "click", () => setOutPoint());
  addEvt(els.rangePill, "click", () => {
    activeRange = null;
    updateRangeTimelineUI();
    updateSelectionReadout();
    stage?.redrawOverlay?.();
  });
  addEvt(els.rangePill, "contextmenu", (evt) => {
    evt.preventDefault?.();
    activeRange = null;
    updateRangeTimelineUI();
    updateSelectionReadout();
    stage?.redrawOverlay?.();
  });

  if (typeof window !== "undefined") {
    addEvt(window, "keydown", (evt) => {
      if (evt.ctrlKey || evt.metaKey || evt.altKey) return;
      if (shouldIgnoreShortcutTarget(evt.target)) return;
      if (evt.key === "i" || evt.key === "I") {
        evt.preventDefault?.();
        setInPoint();
      } else if (evt.key === "o" || evt.key === "O") {
        evt.preventDefault?.();
        setOutPoint();
      }
    });
  }

  addEvt(els.btnSaveNote, "click", () => saveNote());
  addEvt(els.btnClearSel, "click", () => clearSelection());
  addEvt(els.btnCopyRevision, "click", () => copyRevisionPrompt());
  addEvt(els.btnCopyPrompt, "click", () => copyRevisionPrompt());

  stage?.setAnnotationsDrawer?.(drawOverlay);
  updateSelectionReadout();
  loadNotes();

  return {
    loadNotes,
    saveNote,
    deleteNote,
    clearSelection,
    setRange,
    setInPoint,
    setOutPoint,
    copyRevisionPrompt,
    setFrameContext,
    setInfo,
    getNotes: () => [...notes],
    getSelection: () => ({
      point: activePoint,
      bbox: activeBox,
      range: activeRange ? { ...activeRange } : null,
    }),
    destroy,
  };
}
