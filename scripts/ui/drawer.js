/**
 * drawer.js — Collapsible Inspector Drawer, QA Tab, Audio Mixing & Export Presets for kinearc
 */

import { toFiniteNumber } from "./timeline.js";

function pathBasename(filePath) {
  if (!filePath) return "";
  const parts = String(filePath).replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : "";
}

export function summarizeQaState(info = {}) {
  const safeInfo = info && typeof info === "object" ? info : {};
  const overallMae = toFiniteNumber(safeInfo.overall_mae);
  const psnrDb = toFiniteNumber(safeInfo.overall_psnr_db);
  const cloneLoopMae = toFiniteNumber(safeInfo.clone_loop_mae);
  const sourceLoopMae = toFiniteNumber(safeInfo.source_loop_mae);

  const hasOverallMae = overallMae !== null;
  const hasPsnr = psnrDb !== null;
  const hasCloneLoop = cloneLoopMae !== null;
  const hasSourceLoop = sourceLoopMae !== null;

  const worstRaw = Array.isArray(safeInfo.worst_frames) ? safeInfo.worst_frames : [];
  const worstFrames = [...worstRaw]
    .filter((w) => w && typeof w === "object" && toFiniteNumber(w.frame) !== null)
    .sort((a, b) => {
      const ra = toFiniteNumber(a.rank) ?? Infinity;
      const rb = toFiniteNumber(b.rank) ?? Infinity;
      if (ra !== rb) return ra - rb;
      return (toFiniteNumber(b.mae) ?? 0) - (toFiniteNumber(a.mae) ?? 0);
    })
    .slice(0, 5)
    .map((w, idx) => ({
      rank: toFiniteNumber(w.rank) ?? idx + 1,
      frame: Math.max(0, Math.round(toFiniteNumber(w.frame))),
      timestampSec: toFiniteNumber(w.timestamp_sec),
      mae: toFiniteNumber(w.mae) ?? 0,
    }));

  const cutsRaw = Array.isArray(safeInfo.scene_cuts) ? safeInfo.scene_cuts : [];
  const sceneCuts = cutsRaw
    .filter((c) => c && typeof c === "object")
    .map((c, idx) => {
      const rawBefore = toFiniteNumber(c.before_frame);
      const beforeF = rawBefore !== null ? Math.round(rawBefore) : null;
      const rawAfter = toFiniteNumber(c.after_frame);
      const afterF = rawAfter !== null
        ? Math.round(rawAfter)
        : (beforeF !== null ? beforeF + 1 : 0);
      const rawCutIdx = toFiniteNumber(c.cut_index);
      const base = pathBasename(c.pair_image);
      return {
        cutIndex: rawCutIdx !== null ? Math.round(rawCutIdx) : idx,
        beforeFrame: beforeF,
        afterFrame: Math.max(0, afterF),
        timestampSec: toFiniteNumber(c.timestamp_sec),
        deltaMae: toFiniteNumber(c.delta_mae),
        thumbUrl: base ? `/cuts/${encodeURIComponent(base)}` : "",
        thumbName: base,
      };
    });

  const hasQaMetrics = hasOverallMae || hasPsnr || hasCloneLoop || hasSourceLoop || worstFrames.length > 0;

  let loopKnown = false;
  let loopClean = true;
  let loopBadgeText = "Loop Seam: Not audited";
  if (hasCloneLoop || hasSourceLoop) {
    loopKnown = true;
    const primary = hasCloneLoop ? cloneLoopMae : sourceLoopMae;
    loopClean = primary <= 6.0;
    const tag = hasCloneLoop ? "Clone Loop" : "Source Loop";
    loopBadgeText = loopClean
      ? `${tag}: ${primary.toFixed(3)} MAE (Clean ≤ 6.0)`
      : `${tag}: ${primary.toFixed(3)} MAE (Seam Jump > 6.0)`;
  }

  return {
    hasQaMetrics,
    overallMaeLabel: hasOverallMae ? overallMae.toFixed(2) : "—",
    psnrLabel: hasPsnr ? `${psnrDb.toFixed(2)} dB` : "—",
    loopMaeLabel: hasCloneLoop
      ? cloneLoopMae.toFixed(3)
      : (hasSourceLoop ? `${sourceLoopMae.toFixed(3)} (src)` : "—"),
    loopKnown,
    loopClean,
    loopBadgeText,
    worstFrames,
    sceneCuts,
  };
}

export function buildExportPresetHint(preset, info = {}, currentFrame = 0) {
  const safeInfo = info && typeof info === "object" ? info : {};
  const rawFps = toFiniteNumber(safeInfo.fps);
  const fps = rawFps !== null && rawFps > 0 ? Math.round(rawFps) : 60;
  const rawW = toFiniteNumber(safeInfo.width);
  const w = rawW !== null && rawW > 0 ? rawW : 1920;
  const rawH = toFiniteNumber(safeInfo.height);
  const h = rawH !== null && rawH > 0 ? rawH : 1080;
  const isVertical = h > w;
  const safeFrame = Math.max(0, Math.round(toFiniteNumber(currentFrame) ?? 0));
  const tSec = (safeFrame / fps).toFixed(2);
  const outDir = typeof safeInfo.out_dir === "string" && safeInfo.out_dir.trim()
    ? safeInfo.out_dir.trim()
    : ".kinearc_analysis";

  if (preset === "still") {
    return [
      `# Still Frame Audit (f${safeFrame} · t=${tSec}s)`,
      `python scripts/kinearc_cli.py stills --scene scene.html --out_dir ${outDir}/stills --times ${tSec} --scale 1`,
      `# Remotion: npx remotion still MainComp ${outDir}/still_f${safeFrame}.png --frame=${safeFrame}`,
      `# Live HTML: open scene with ?t=${tSec}`,
    ].join("\n");
  }

  if (preset === "4k60") {
    const dims = isVertical ? "2160x3840" : "3840x2160";
    return [
      `# Export 4K 60fps (${dims})`,
      `python scripts/kinearc_cli.py render --project kinearc.project.json --out ${outDir}/render_4k.mp4 --scale 2 --fps 60 --crf 16`,
      `# Remotion: npx remotion render MainComp ${outDir}/render_4k.mp4 --scale=2 --fps=60`,
      `# Motion Canvas: export at scale 2 (${dims} @ 60fps)`,
    ].join("\n");
  }

  const dims1080 = isVertical ? "1080x1920" : "1920x1080";
  return [
    `# Export 1080p 60fps (${dims1080})`,
    `python scripts/kinearc_cli.py render --project kinearc.project.json --out ${outDir}/render_1080p.mp4 --scale 1 --fps 60 --crf 16`,
    `# Remotion: npx remotion render MainComp ${outDir}/render_1080p.mp4 --scale=1 --fps=60`,
    `# Motion Canvas: export at scale 1 (${dims1080} @ 60fps)`,
  ].join("\n");
}

async function copyHintText(text) {
  if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_err) {}
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
    workspace: overrides.workspace ?? byId("workspace"),
    rightDrawer: overrides.rightDrawer ?? byId("rightDrawer"),
    btnToggleDrawer: overrides.btnToggleDrawer ?? byId("btnToggleDrawer"),
    btnTopExport: overrides.btnTopExport ?? byId("btnTopExport"),
    tabNotes: overrides.tabNotes ?? byId("tab-notes"),
    tabQa: overrides.tabQa ?? byId("tab-qa"),
    tabAudio: overrides.tabAudio ?? byId("tab-audio"),
    qaSummary: overrides.qaSummary ?? byId("qaSummary"),
    loopBadge: overrides.loopBadge ?? byId("loopBadge"),
    worstFramesList: overrides.worstFramesList ?? byId("worstFramesList"),
    sceneCutsList: overrides.sceneCutsList ?? byId("sceneCutsList"),
    audioControlsMount: overrides.audioControlsMount ?? byId("audioControlsMount"),
    exportControlsMount: overrides.exportControlsMount ?? byId("exportControlsMount"),
  };
}

export function createDrawer({
  info = {},
  stage = null,
  timeline = null,
  onInfoUpdated = null,
  onStageReload = null,
  onToast = null,
  elements = {},
} = {}) {
  const els = resolveElements(elements);
  const abortCtrl = typeof AbortController !== "undefined" ? new AbortController() : null;
  const sig = abortCtrl ? abortCtrl.signal : undefined;

  let currentInfo = info || {};
  let activeTab = "notes";
  let activeExportPreset = "1080p60";
  let audioUI = null;
  let exportHintEl = null;
  let renderPollTimer = null;
  let activeRenderToken = 0;
  let destroyed = false;

  function clearRenderPollTimer() {
    if (renderPollTimer !== null) {
      clearTimeout(renderPollTimer);
      renderPollTimer = null;
    }
  }

  function jumpToFrame(frameIdx) {
    const f = Math.max(0, Math.round(toFiniteNumber(frameIdx) ?? 0));
    timeline?.pause?.();
    if (timeline && typeof timeline.seekToFrame === "function") {
      timeline.seekToFrame(f);
    } else if (stage && typeof stage.seekTime === "function") {
      stage.seekTime(null, f);
    }
  }

  function isCollapsed() {
    const wsCollapsed = Boolean(els.workspace?.classList?.contains("drawer-collapsed"));
    const drCollapsed = Boolean(els.rightDrawer?.classList?.contains("collapsed"));
    return wsCollapsed || drCollapsed;
  }

  function setDrawerCollapsed(collapsed) {
    const next = Boolean(collapsed);
    els.workspace?.classList?.toggle("drawer-collapsed", next);
    els.rightDrawer?.classList?.toggle("collapsed", next);
    els.btnToggleDrawer?.setAttribute?.("aria-expanded", String(!next));
    els.btnToggleDrawer?.classList?.toggle("active", !next);
    stage?.fitStage?.();
    if (typeof setTimeout === "function") {
      setTimeout(() => stage?.fitStage?.(), 200);
    }
  }

  function setActiveTab(tabName) {
    if (!["notes", "qa", "audio"].includes(tabName)) return;
    activeTab = tabName;

    const tabs = els.rightDrawer?.querySelectorAll ? els.rightDrawer.querySelectorAll(".drawer-tab[data-tab]") : [];
    for (const btn of tabs) {
      const t = btn.dataset?.tab || btn.getAttribute?.("data-tab");
      const isAct = t === tabName;
      btn.classList?.toggle("active", isAct);
      btn.setAttribute?.("aria-selected", isAct ? "true" : "false");
    }

    const panelMap = {
      notes: els.tabNotes,
      qa: els.tabQa,
      audio: els.tabAudio,
    };
    for (const [name, panel] of Object.entries(panelMap)) {
      if (!panel) continue;
      const show = name === tabName;
      panel.hidden = !show;
      panel.classList?.toggle("active", show);
    }
  }

  function renderQaTab() {
    const summary = summarizeQaState(currentInfo);
    const doc = els.qaSummary?.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!doc) return;

    if (els.qaSummary) {
      els.qaSummary.replaceChildren?.();
      if (!summary.hasQaMetrics) {
        const empty = doc.createElement("div");
        empty.className = "qa-row-sub";
        empty.textContent = "No QA report loaded. Run verify_motion_diff.py against a reference clip to inspect MAE, PSNR, and worst frames.";
        els.qaSummary.appendChild(empty);
      } else {
        const grid = doc.createElement("div");
        grid.className = "qa-summary-grid";
        for (const [label, val] of [
          ["Overall MAE", summary.overallMaeLabel],
          ["PSNR", summary.psnrLabel],
          ["Loop Seam MAE", summary.loopMaeLabel],
        ]) {
          const stat = doc.createElement("div");
          stat.className = "qa-stat";
          const lbl = doc.createElement("span");
          lbl.className = "qa-stat-label";
          lbl.textContent = label;
          const valEl = doc.createElement("span");
          valEl.className = "qa-stat-val";
          valEl.textContent = val;
          stat.appendChild(lbl);
          stat.appendChild(valEl);
          grid.appendChild(stat);
        }
        els.qaSummary.appendChild(grid);
      }
    }

    if (els.loopBadge) {
      els.loopBadge.classList.remove("clean", "warn");
      if (summary.loopKnown) {
        els.loopBadge.classList.add(summary.loopClean ? "clean" : "warn");
      }
      els.loopBadge.textContent = summary.loopBadgeText;
    }

    if (els.worstFramesList) {
      els.worstFramesList.replaceChildren?.();
      if (summary.worstFrames.length === 0) {
        const empty = doc.createElement("div");
        empty.className = "empty-hint";
        empty.textContent = "No worst-frame anomalies recorded.";
        els.worstFramesList.appendChild(empty);
      } else {
        for (const item of summary.worstFrames) {
          const card = doc.createElement("div");
          card.className = "qa-item qa-row";

          const left = doc.createElement("div");
          left.className = "qa-row-info";
          const title = doc.createElement("span");
          title.className = "qa-row-title";
          title.textContent = `#${item.rank} · Frame f${item.frame}`;
          const sub = doc.createElement("span");
          sub.className = "qa-row-sub";
          const tPart = item.timestampSec !== null ? ` · ${item.timestampSec.toFixed(2)}s` : "";
          sub.textContent = `MAE ${item.mae.toFixed(2)}${tPart}`;
          left.appendChild(title);
          left.appendChild(sub);

          const btnJump = doc.createElement("button");
          btnJump.type = "button";
          btnJump.className = "ghost-btn";
          btnJump.textContent = "Jump";
          btnJump.addEventListener("click", (evt) => {
            evt.stopPropagation?.();
            jumpToFrame(item.frame);
          });

          card.appendChild(left);
          card.appendChild(btnJump);
          els.worstFramesList.appendChild(card);
        }
      }
    }

    if (els.sceneCutsList) {
      els.sceneCutsList.replaceChildren?.();
      if (summary.sceneCuts.length === 0) {
        const empty = doc.createElement("div");
        empty.className = "empty-hint";
        empty.textContent = "No scene cuts detected.";
        els.sceneCutsList.appendChild(empty);
      } else {
        for (const cut of summary.sceneCuts) {
          const card = doc.createElement("div");
          card.className = "qa-item";

          const row = doc.createElement("div");
          row.className = "qa-row";

          const left = doc.createElement("div");
          left.className = "qa-row-info";
          const title = doc.createElement("span");
          title.className = "qa-row-title";
          const beforeStr = cut.beforeFrame !== null ? `f${cut.beforeFrame}→` : "";
          title.textContent = `Cut #${cut.cutIndex + 1} · ${beforeStr}f${cut.afterFrame}`;
          const sub = doc.createElement("span");
          sub.className = "qa-row-sub";
          const tPart = cut.timestampSec !== null ? `${cut.timestampSec.toFixed(2)}s` : "";
          const maePart = cut.deltaMae !== null ? ` · ΔMAE ${cut.deltaMae.toFixed(1)}` : "";
          sub.textContent = `${tPart}${maePart}` || `Frame ${cut.afterFrame}`;
          left.appendChild(title);
          left.appendChild(sub);

          const btnJump = doc.createElement("button");
          btnJump.type = "button";
          btnJump.className = "ghost-btn";
          btnJump.textContent = "Jump";
          btnJump.addEventListener("click", (evt) => {
            evt.stopPropagation?.();
            jumpToFrame(cut.afterFrame);
          });

          row.appendChild(left);
          row.appendChild(btnJump);
          card.appendChild(row);

          if (cut.thumbUrl) {
            const link = doc.createElement("a");
            link.className = "cut-thumb-link";
            link.href = cut.thumbUrl;
            link.target = "_blank";
            link.rel = "noopener";
            link.title = `Open ${cut.thumbName}`;

            const img = doc.createElement("img");
            img.className = "cut-thumb";
            img.src = cut.thumbUrl;
            img.alt = `Cut #${cut.cutIndex + 1} transition preview`;
            img.loading = "lazy";
            link.appendChild(img);
            card.appendChild(link);
          }

          els.sceneCutsList.appendChild(card);
        }
      }
    }
  }

  function updateAudioChips() {
    if (!audioUI) return;
    const audioMeta = currentInfo?.audio || {};
    audioUI.chipVoice.classList.toggle("ready", Boolean(audioMeta.voice));
    audioUI.chipBgm.classList.toggle("ready", Boolean(audioMeta.bgm));
    audioUI.chipSfx.classList.toggle("ready", Boolean(audioMeta.sfx));
    audioUI.chipVideo.classList.toggle("ready", Boolean(currentInfo?.has_video));
  }

  async function refreshInfoFromServer() {
    if (typeof fetch !== "function") return;
    try {
      const res = await fetch("/api/info", { cache: "no-store" });
      if (!res.ok) return;
      const fresh = await res.json();
      currentInfo = fresh;
      renderQaTab();
      updateAudioChips();
      timeline?.setInfo?.(fresh, { reloadWaveform: true });
      if (typeof onInfoUpdated === "function") {
        onInfoUpdated(fresh);
      }
    } catch (_err) {
      // Keep UI resilient if info refresh fails
    }
  }

  function mountAudioControls() {
    const mount = els.audioControlsMount;
    if (!mount) return;
    mount.replaceChildren?.();
    const doc = mount.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!doc) return;

    const label = doc.createElement("div");
    label.className = "section-label";
    label.textContent = "Audio Finishing";
    mount.appendChild(label);

    const card = doc.createElement("div");
    card.className = "drawer-card";

    const statusRow = doc.createElement("div");
    statusRow.className = "status-row";
    const makeChip = (text) => {
      const s = doc.createElement("span");
      s.className = "status-chip";
      s.textContent = text;
      return s;
    };
    const chipVoice = makeChip("Voice");
    const chipBgm = makeChip("BGM");
    const chipSfx = makeChip("SFX");
    const chipVideo = makeChip("Video");
    statusRow.append(chipVoice, chipBgm, chipSfx, chipVideo);
    card.appendChild(statusRow);

    const makeRangeRow = ({ id, title, min, max, step, value, suffix = "×" }) => {
      const row = doc.createElement("div");
      row.className = "form-row";
      const head = doc.createElement("div");
      head.className = "form-row-head";
      const lbl = doc.createElement("label");
      lbl.htmlFor = id;
      lbl.textContent = title;
      const valSpan = doc.createElement("span");
      valSpan.className = "form-row-val tabular";
      valSpan.textContent = `${Number(value).toFixed(2)}${suffix}`;
      head.append(lbl, valSpan);

      const input = doc.createElement("input");
      input.id = id;
      input.type = "range";
      input.className = "range-input";
      input.min = String(min);
      input.max = String(max);
      input.step = String(step);
      input.value = String(value);
      input.addEventListener("input", () => {
        valSpan.textContent = `${Number(input.value).toFixed(2)}${suffix}`;
      });
      row.append(head, input);
      return { row, input, valSpan };
    };

    const voiceCtrl = makeRangeRow({
      id: "audioVoiceVol",
      title: "Voice Volume",
      min: 0.0,
      max: 2.0,
      step: 0.05,
      value: 1.0,
    });
    const bgmCtrl = makeRangeRow({
      id: "audioBgmVol",
      title: "BGM Duck Volume",
      min: 0.0,
      max: 1.0,
      step: 0.05,
      value: 0.35,
    });
    const videoVolCtrl = makeRangeRow({
      id: "audioVideoVol",
      title: "Video Audio Volume",
      min: 0.0,
      max: 2.0,
      step: 0.05,
      value: 1.0,
    });

    const keepRow = doc.createElement("label");
    keepRow.className = "checkbox-row";
    const keepChk = doc.createElement("input");
    keepChk.id = "audioKeepVideo";
    keepChk.type = "checkbox";
    keepChk.checked = false;
    const keepText = doc.createElement("span");
    keepText.textContent = "Include original video audio";
    keepRow.append(keepChk, keepText);

    const fadeRow = doc.createElement("div");
    fadeRow.className = "form-row-head";
    const fadeLbl = doc.createElement("label");
    fadeLbl.htmlFor = "audioFadeOut";
    fadeLbl.textContent = "BGM Fade-out (s)";
    const fadeInput = doc.createElement("input");
    fadeInput.id = "audioFadeOut";
    fadeInput.type = "number";
    fadeInput.className = "num-input tabular";
    fadeInput.min = "0";
    fadeInput.max = "20";
    fadeInput.step = "0.1";
    fadeInput.value = "1.5";
    fadeRow.append(fadeLbl, fadeInput);

    const actions = doc.createElement("div");
    actions.className = "btn-stack";

    const btnCutPauses = doc.createElement("button");
    btnCutPauses.id = "btnCutPauses";
    btnCutPauses.type = "button";
    btnCutPauses.className = "tool-btn";
    btnCutPauses.textContent = "Trim Pauses (cut-pauses)";

    const btnAudioMix = doc.createElement("button");
    btnAudioMix.id = "btnAudioMix";
    btnAudioMix.type = "button";
    btnAudioMix.className = "accent-btn";
    btnAudioMix.textContent = "Auto-Duck Mix (audio_mix)";

    const resultBox = doc.createElement("div");
    resultBox.id = "audioMixResult";
    resultBox.className = "hint-box hidden";

    const setResult = (msg, linkUrl = null) => {
      resultBox.replaceChildren?.();
      resultBox.classList.remove("hidden");
      const line = doc.createElement("div");
      line.textContent = msg;
      resultBox.appendChild(line);
      if (linkUrl) {
        const a = doc.createElement("a");
        a.className = "hint-link";
        a.href = linkUrl;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = `Open ${linkUrl}`;
        resultBox.appendChild(a);
      }
    };

    btnCutPauses.addEventListener("click", async () => {
      const track = currentInfo?.audio?.voice ? "voice" : (currentInfo?.has_video ? "video" : "voice");
      btnCutPauses.disabled = true;
      const prevLabel = btnCutPauses.textContent;
      btnCutPauses.textContent = "Trimming pauses...";
      try {
        const res = await fetch("/api/audio/cut-pauses", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            track,
            threshold: -32.0,
            min_silence: 0.45,
            pad: 0.08,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.error || `HTTP ${res.status}`);
        }
        const segCount = Array.isArray(data.keep_segments) ? data.keep_segments.length : 0;
        const outLabel = data.out || data.cuts_json || "renders/";
        setResult(`Trimmed (${segCount} keep segments) -> ${outLabel}`, data.url || null);
        onToast?.(`Pause trim complete -> ${outLabel}`, "ok");
        await refreshInfoFromServer();
      } catch (err) {
        setResult(`Error: ${err.message}`);
        onToast?.(`Trim pauses failed: ${err.message}`, "error");
      } finally {
        btnCutPauses.disabled = false;
        btnCutPauses.textContent = prevLabel;
      }
    });

    btnAudioMix.addEventListener("click", async () => {
      btnAudioMix.disabled = true;
      const prevLabel = btnAudioMix.textContent;
      btnAudioMix.textContent = "Mixing audio...";
      try {
        const payload = {
          voice_vol: toFiniteNumber(voiceCtrl.input.value) ?? 1.0,
          bgm_vol: toFiniteNumber(bgmCtrl.input.value) ?? 0.35,
          video_vol: toFiniteNumber(videoVolCtrl.input.value) ?? 1.0,
          fade_out: toFiniteNumber(fadeInput.value) ?? 1.5,
          keep_video_audio: Boolean(keepChk.checked),
        };
        const res = await fetch("/api/audio/mix", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.error || `HTTP ${res.status}`);
        }
        setResult(`Mixed output -> ${data.out}`, data.url || null);
        onToast?.(`Audio mix ready -> ${data.out}`, "ok");
      } catch (err) {
        setResult(`Error: ${err.message}`);
        onToast?.(`Audio mix failed: ${err.message}`, "error");
      } finally {
        btnAudioMix.disabled = false;
        btnAudioMix.textContent = prevLabel;
      }
    });

    actions.append(btnCutPauses, btnAudioMix);
    card.append(voiceCtrl.row, bgmCtrl.row, keepRow, videoVolCtrl.row, fadeRow, actions, resultBox);
    mount.appendChild(card);

    audioUI = { chipVoice, chipBgm, chipSfx, chipVideo };
    updateAudioChips();
  }

  function mountExportControls() {
    const mount = els.exportControlsMount;
    if (!mount) return;
    mount.replaceChildren?.();
    const doc = mount.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!doc) return;

    const label = doc.createElement("div");
    label.className = "section-label";
    label.textContent = "Render & Export";
    mount.appendChild(label);

    const card = doc.createElement("div");
    card.className = "drawer-card";

    const btns = doc.createElement("div");
    btns.className = "btn-stack";

    const renderProgressWrap = doc.createElement("div");
    renderProgressWrap.id = "renderProgressWrap";
    renderProgressWrap.className = "render-progress-wrap";
    renderProgressWrap.classList.add("hidden");

    const renderProgressTrack = doc.createElement("div");
    renderProgressTrack.className = "render-progress";
    const renderProgressBar = doc.createElement("div");
    renderProgressBar.id = "renderProgressBar";
    renderProgressBar.className = "render-progress-bar";
    renderProgressBar.style.width = "0%";
    renderProgressTrack.appendChild(renderProgressBar);

    const renderStatusText = doc.createElement("div");
    renderStatusText.id = "renderStatusText";
    renderStatusText.className = "render-status-text tabular";
    renderProgressWrap.append(renderProgressTrack, renderStatusText);

    const renderResultLinks = doc.createElement("div");
    renderResultLinks.id = "renderResultLinks";
    renderResultLinks.className = "hint-box";
    renderResultLinks.classList.add("hidden");

    const btnOpenRenderedVideo = doc.createElement("button");
    btnOpenRenderedVideo.id = "btnOpenRenderedVideo";
    btnOpenRenderedVideo.type = "button";
    btnOpenRenderedVideo.className = "accent-btn";
    btnOpenRenderedVideo.classList.add("hidden");
    btnOpenRenderedVideo.textContent = "Open in Stage / Diff";

    const hintBox = doc.createElement("div");
    hintBox.id = "exportHintBox";
    hintBox.className = "hint-box";
    hintBox.textContent = buildExportPresetHint(activeExportPreset, currentInfo, 0);
    exportHintEl = hintBox;

    let lastCompletedJobId = null;
    let lastCompletedOut = null;
    const presetBtns = [];

    const setPresetButtonsDisabled = (disabled) => {
      for (const b of presetBtns) {
        b.disabled = Boolean(disabled);
      }
    };

    const setProgressVisual = (pct, text, stateClass = "") => {
      renderProgressWrap.classList.remove("hidden");
      renderProgressBar.classList.remove("done", "error");
      if (stateClass) {
        renderProgressBar.classList.add(stateClass);
      }
      const clamped = Math.min(100, Math.max(0, Number(pct) || 0));
      renderProgressBar.style.width = `${clamped.toFixed(1)}%`;
      renderStatusText.textContent = text;
    };

    const showResultLinks = (job) => {
      renderResultLinks.replaceChildren?.();
      const rawItems = Array.isArray(job?.stills) && job.stills.length > 0
        ? job.stills
        : (job?.url ? [{ url: job.url, out: job.out || job.url }] : []);
      for (const entry of rawItems) {
        const url = typeof entry === "string" ? entry : entry?.url;
        if (typeof url !== "string" || !url.startsWith("/") || /^\/[\/\\]/.test(url)) continue;
        const row = doc.createElement("div");
        const link = doc.createElement("a");
        link.className = "hint-link";
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = `Open ${url}`;
        row.appendChild(link);
        renderResultLinks.appendChild(row);
      }
      if (renderResultLinks.children.length > 0) {
        renderResultLinks.classList.remove("hidden");
      }
    };

    btnOpenRenderedVideo.addEventListener("click", async () => {
      if (destroyed || (!lastCompletedJobId && !lastCompletedOut)) return;
      btnOpenRenderedVideo.disabled = true;
      try {
        const reqBody = lastCompletedJobId ? { job_id: lastCompletedJobId } : { path: lastCompletedOut };
        const res = await fetch("/api/render/load", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody),
        });
        if (destroyed) return;
        const data = await res.json().catch(() => ({}));
        if (destroyed) return;
        if (!res.ok) {
          throw new Error(data.error || `HTTP ${res.status}`);
        }
        if (data.info) {
          setInfo(data.info);
          if (typeof onStageReload === "function") {
            onStageReload(data.info);
          } else {
            stage?.init?.(data.info);
            stage?.setMode?.(data.info.has_ref ? "split" : "clone");
            timeline?.setInfo?.(data.info, { reloadWaveform: true });
            onInfoUpdated?.(data.info);
          }
        }
        onToast?.("Loaded rendered MP4 into stage", "ok");
      } catch (err) {
        if (!destroyed) {
          onToast?.(`Failed to load rendered video: ${err.message}`, "error");
        }
      } finally {
        if (!destroyed) {
          btnOpenRenderedVideo.disabled = false;
        }
      }
    }, sig ? { signal: sig } : undefined);

    const pollRenderJob = async (jobId, mode, token) => {
      if (destroyed || token !== activeRenderToken) return;
      try {
        const res = await fetch(`/api/render/${encodeURIComponent(jobId)}`, { cache: "no-store" });
        if (destroyed || token !== activeRenderToken) return;
        const job = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(job.error || `HTTP ${res.status}`);
        }
        if (job.status === "running") {
          const pct = toFiniteNumber(job.progress) ?? 0;
          const frameNum = toFiniteNumber(job.frame) ?? 0;
          const totalNum = toFiniteNumber(job.total) ?? 0;
          const statusMsg = totalNum > 0
            ? `Rendering frame ${Math.round(frameNum)}/${Math.round(totalNum)} (${Math.round(pct)}%)...`
            : (mode === "stills" ? "Capturing still frame..." : "Starting render engine...");
          setProgressVisual(pct, statusMsg);
          clearRenderPollTimer();
          renderPollTimer = setTimeout(() => {
            pollRenderJob(jobId, mode, token);
          }, 250);
          return;
        }
        setPresetButtonsDisabled(false);
        if (job.status === "done") {
          const outLabel = job.out || job.url || "renders/";
          if (mode === "stills") {
            setProgressVisual(100, `Still captured -> ${outLabel}`, "done");
            showResultLinks(job);
            onToast?.(`Still captured -> ${outLabel}`, "ok");
          } else {
            lastCompletedJobId = jobId;
            lastCompletedOut = job.out || null;
            setProgressVisual(100, `Render complete -> ${outLabel}`, "done");
            btnOpenRenderedVideo.classList.remove("hidden");
            onToast?.(`Render complete -> ${outLabel}`, "ok");
          }
          return;
        }
        const errMsg = job.error || "Render failed";
        setProgressVisual(0, `Error: ${errMsg}`, "error");
        onToast?.(`Render failed: ${errMsg}`, "error");
      } catch (err) {
        if (destroyed || token !== activeRenderToken) return;
        setPresetButtonsDisabled(false);
        setProgressVisual(0, `Error: ${err.message}`, "error");
        onToast?.(`Render status error: ${err.message}`, "error");
      }
    };

    const presets = [
      { id: "btnExportStill", preset: "still", label: "Render Still" },
      { id: "btnExport1080", preset: "1080p60", label: "Export 1080p 60fps" },
      { id: "btnExport4K", preset: "4k60", label: "Export 4K 60fps" },
    ];

    for (const item of presets) {
      const btn = doc.createElement("button");
      btn.id = item.id;
      btn.type = "button";
      btn.className = "tool-btn";
      btn.dataset.exportPreset = item.preset;
      btn.textContent = item.label;
      presetBtns.push(btn);
      btn.addEventListener("click", async () => {
        activeExportPreset = item.preset;
        const tlState = timeline?.getState?.() || {};
        const stState = stage?.getState?.() || {};
        const curFrame = toFiniteNumber(tlState.currentFrame ?? stState.currentFrameIdx) ?? 0;
        const hint = buildExportPresetHint(activeExportPreset, currentInfo, curFrame);
        hintBox.textContent = hint;

        const canRenderLive = Boolean(currentInfo?.has_live_scene && currentInfo?.has_render_engine !== false);
        if (!canRenderLive) {
          const copied = await copyHintText(hint);
          const msg = copied
            ? "CLI render hint copied (load --scene or --project for one-click render)"
            : "CLI render hint updated (load --scene or --project for one-click render)";
          onToast?.(msg, "info");
          return;
        }

        const fpsVal = toFiniteNumber(tlState.fps ?? currentInfo?.fps);
        const fps = fpsVal !== null && fpsVal > 0 ? fpsVal : 60;
        const curTime = toFiniteNumber(tlState.currentTimeSec ?? stState.currentTimeSec) ?? (curFrame / fps);

        let reqPayload;
        if (item.preset === "still") {
          reqPayload = { mode: "stills", scale: 1, times: [Number(curTime.toFixed(3))] };
        } else if (item.preset === "4k60") {
          reqPayload = { mode: "mp4", scale: 2, fps: 60, crf: 16 };
        } else {
          reqPayload = { mode: "mp4", scale: 1, fps: 60, crf: 16 };
        }

        activeRenderToken += 1;
        const token = activeRenderToken;
        clearRenderPollTimer();
        lastCompletedJobId = null;
        lastCompletedOut = null;
        btnOpenRenderedVideo.classList.add("hidden");
        renderResultLinks.classList.add("hidden");
        renderResultLinks.replaceChildren?.();
        setPresetButtonsDisabled(true);
        setProgressVisual(0, item.preset === "still" ? "Capturing still frame..." : "Starting render engine...");

        try {
          const res = await fetch("/api/render", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqPayload),
          });
          if (destroyed || token !== activeRenderToken) return;
          const data = await res.json().catch(() => ({}));
          if (!res.ok || !data.job_id) {
            throw new Error(data.error || `HTTP ${res.status}`);
          }
          clearRenderPollTimer();
          renderPollTimer = setTimeout(() => {
            pollRenderJob(data.job_id, reqPayload.mode, token);
          }, 250);
        } catch (err) {
          if (destroyed || token !== activeRenderToken) return;
          setPresetButtonsDisabled(false);
          setProgressVisual(0, `Error: ${err.message}`, "error");
          onToast?.(`Render failed: ${err.message}`, "error");
        }
      }, sig ? { signal: sig } : undefined);
      btns.appendChild(btn);
    }

    card.append(btns, renderProgressWrap, renderResultLinks, btnOpenRenderedVideo, hintBox);
    mount.appendChild(card);
  }

  function setInfo(nextInfo = {}) {
    currentInfo = nextInfo || {};
    renderQaTab();
    updateAudioChips();
    if (exportHintEl) {
      const curFrame = timeline?.getState?.().currentFrame ?? 0;
      exportHintEl.textContent = buildExportPresetHint(activeExportPreset, currentInfo, curFrame);
    }
  }

  function destroy() {
    destroyed = true;
    activeRenderToken += 1;
    clearRenderPollTimer();
    if (abortCtrl) {
      abortCtrl.abort();
    }
  }

  // ---------- Event Wiring ----------
  const addEvt = (el, type, handler) => {
    if (!el || typeof el.addEventListener !== "function") return;
    el.addEventListener(type, handler, sig ? { signal: sig } : undefined);
  };

  addEvt(els.btnToggleDrawer, "click", () => {
    setDrawerCollapsed(!isCollapsed());
  });

  addEvt(els.btnTopExport, "click", () => {
    if (isCollapsed()) {
      setDrawerCollapsed(false);
    }
    setActiveTab("audio");
  });

  if (els.rightDrawer?.querySelectorAll) {
    const tabBtns = els.rightDrawer.querySelectorAll(".drawer-tab[data-tab]");
    for (const btn of tabBtns) {
      addEvt(btn, "click", () => {
        const targetTab = btn.dataset?.tab || btn.getAttribute?.("data-tab");
        if (targetTab) setActiveTab(targetTab);
      });
    }
  }

  renderQaTab();
  mountAudioControls();
  mountExportControls();
  setActiveTab(activeTab);
  const initiallyCollapsed = isCollapsed();
  els.btnToggleDrawer?.setAttribute?.("aria-expanded", String(!initiallyCollapsed));
  els.btnToggleDrawer?.classList?.toggle("active", !initiallyCollapsed);

  return {
    setActiveTab,
    setDrawerCollapsed,
    setInfo,
    refreshInfoFromServer,
    getActiveTab: () => activeTab,
    isCollapsed,
    destroy,
  };
}
