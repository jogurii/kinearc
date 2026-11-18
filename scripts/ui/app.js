/**
 * app.js — Bootstrap & Cross-Module Wiring for kinearc Web UI
 */

import { createTimeline } from "./timeline.js";
import { createAnnotations } from "./annotations.js";
import { createDrawer } from "./drawer.js";

function createToastManager(containerEl) {
  return function showToast(message, kind = "info") {
    if (!containerEl || typeof document === "undefined") return;
    while (containerEl.children.length >= 4) {
      containerEl.firstElementChild?.remove?.();
    }
    const toast = document.createElement("div");
    toast.className = "toast";
    if (kind === "ok") {
      toast.classList.add("ok");
    } else if (kind === "error") {
      toast.classList.add("error");
    }
    toast.textContent = String(message ?? "");
    containerEl.appendChild(toast);

    setTimeout(() => {
      toast.remove?.();
    }, 4200);
  };
}

async function waitForStage(timeoutMs = 3000) {
  if (typeof window === "undefined") return null;
  if (window.__kinearcStage) return window.__kinearcStage;

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 16));
    if (window.__kinearcStage) return window.__kinearcStage;
  }
  return null;
}

export async function bootstrap() {
  if (typeof document === "undefined" || typeof window === "undefined") return null;
  if (window.__kinearcApp) return window.__kinearcApp;

  const toastContainer = document.getElementById("toastContainer");
  const showToast = createToastManager(toastContainer);

  const stage = await waitForStage();
  if (!stage) {
    showToast("kinearc stage controller failed to initialize.", "error");
    return null;
  }

  let currentInfo = {};
  try {
    const res = await fetch("/api/info", { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} loading /api/info`);
    }
    currentInfo = await res.json();
  } catch (err) {
    showToast(`Failed to connect to kinearc server: ${err.message}`, "error");
    return null;
  }

  let annotations = null;
  let drawer = null;

  stage.enableFrameCache?.(true);
  stage.init(currentInfo);

  const timeline = createTimeline({
    stage,
    info: currentInfo,
    onSeek: (pos) => {
      annotations?.setFrameContext(pos);
    },
    onToast: showToast,
  });

  annotations = createAnnotations({
    stage,
    timeline,
    info: currentInfo,
    getCurrentFrame: () => timeline.getState(),
    onSeek: (frame) => timeline.seekToFrame(frame),
    onToast: showToast,
  });

  drawer = createDrawer({
    info: currentInfo,
    stage,
    timeline,
    onInfoUpdated: (nextInfo) => {
      currentInfo = nextInfo || {};
      annotations.setInfo(currentInfo);
    },
    onStageReload: (nextInfo) => {
      currentInfo = nextInfo || {};
      const targetMode = currentInfo.has_ref ? "split" : "clone";
      stage.init({ ...currentInfo, mode_default: targetMode });
      if (stage.getState().mode !== targetMode) {
        stage.setMode(targetMode);
      }
      timeline.setInfo(currentInfo, { reloadWaveform: true });
      annotations.setInfo(currentInfo);
    },
    onToast: showToast,
  });

  window.addEventListener("kinearc:sceneready", (evt) => {
    const detail = evt?.detail || {};
    timeline.updateTiming({
      durationSec: detail.durationSec,
      totalFrames: detail.totalFrames,
      fps: detail.fps,
    });
    const st = timeline.getState();
    annotations.setFrameContext({ frame: st.currentFrame, timeSec: st.currentTimeSec });
  });

  const app = {
    stage,
    timeline,
    annotations,
    drawer,
    showToast,
    getInfo: () => currentInfo,
  };
  window.__kinearcApp = app;
  return app;
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      bootstrap();
    }, { once: true });
  } else {
    bootstrap();
  }
}
