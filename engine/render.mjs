#!/usr/bin/env node
/**
 * render.mjs — Standalone Headless Chromium WebCodecs / CDP 4K Renderer for kinearc.
 *
 * Subcommands:
 *   stills --scene <scene.html|project.json> --out_dir <dir> --times <t1,t2,...> [--scale 1] [--width 1920] [--height 1080]
 *   render --project <project.json|scene.html> --out <out.mp4> [--scale 1] [--fps 60] [--crf 16] [--json-progress]
 */

import { execFileSync, spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { requireBrowserExecutable } from "./browser_find.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..");
const AUDIO_MIX_PY = path.join(REPO_ROOT, "scripts", "audio_mix.py");

const WEBCODECS_CANDIDATES = [
  "avc1.640034",
  "avc1.4d0034",
  "avc1.420034",
  "avc1.640033",
  "avc1.640028",
];

const DEFAULT_READY_TIMEOUT_MS = 15000;

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".htm": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".mjs": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".wasm": "application/wasm",
  ".glb": "model/gltf-binary",
  ".gltf": "model/gltf+json",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".wav": "audio/wav",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".aac": "audio/aac",
};

function printUsage() {
  console.log(
    [
      "kinearc native renderer (Headless Chromium WebCodecs + CDP)",
      "",
      "Usage:",
      "  node engine/render.mjs stills --scene <scene.html|project.json> --out_dir <dir> --times <0.2,1.5> [--scale 1] [--width 1920] [--height 1080]",
      "  node engine/render.mjs render --project <kinearc.project.json|scene.html> --out <out.mp4> [--scale 1] [--fps 60] [--crf 16] [--json-progress]",
    ].join("\n")
  );
}

function requireFiniteNumber(raw, label, { allowZero = false } = {}) {
  if (typeof raw === "boolean" || raw === null || raw === undefined || String(raw).trim() === "") {
    throw new Error(`${label} must be a finite number, got ${JSON.stringify(raw)}`);
  }
  const num = Number(raw);
  if (!Number.isFinite(num)) {
    throw new Error(`${label} must be a finite number, got ${JSON.stringify(raw)}`);
  }
  if (allowZero ? num < 0 : num <= 0) {
    throw new Error(`${label} must be ${allowZero ? ">= 0" : "> 0"}, got ${num}`);
  }
  return num;
}

function evenDimension(val) {
  const num = requireFiniteNumber(val, "dimension", { allowZero: false });
  return Math.max(2, Math.floor(Math.round(num) / 2) * 2);
}

function resolveExistingFile(rawPath, baseDir, label) {
  if (typeof rawPath !== "string" || !rawPath.trim()) {
    throw new Error(`${label} path must be a non-empty string, got ${JSON.stringify(rawPath)}`);
  }
  const absPath = path.isAbsolute(rawPath) ? path.resolve(rawPath) : path.resolve(baseDir, rawPath);
  let stat;
  try {
    stat = fs.statSync(absPath);
  } catch {
    throw new Error(`${label} file not found: ${absPath}`);
  }
  if (!stat.isFile()) {
    throw new Error(`${label} is not a regular file: ${absPath}`);
  }
  return absPath;
}

function parseCliArgs(argv) {
  if (argv.length === 0 || argv[0] === "-h" || argv[0] === "--help") {
    return { command: "help", flags: {} };
  }
  const command = argv[0];
  if (command !== "stills" && command !== "render") {
    throw new Error(`Unknown subcommand "${command}". Expected "stills" or "render".`);
  }
  const flags = {};
  const booleanFlags = new Set(["json-progress", "help"]);

  for (let i = 1; i < argv.length; i++) {
    const token = argv[i];
    if (token === "-h") {
      flags.help = true;
      continue;
    }
    if (!token.startsWith("--")) {
      throw new Error(`Unexpected positional argument: ${token}`);
    }
    const eqIdx = token.indexOf("=");
    if (eqIdx !== -1) {
      const key = token.slice(2, eqIdx);
      flags[key] = token.slice(eqIdx + 1);
      continue;
    }
    const key = token.slice(2);
    if (booleanFlags.has(key)) {
      flags[key] = true;
      continue;
    }
    if (i + 1 >= argv.length) {
      throw new Error(`Flag --${key} requires a value.`);
    }
    flags[key] = argv[++i];
  }
  return { command, flags };
}

function parseSceneEntry(entry, projectDir) {
  if (typeof entry === "string") {
    return { path: resolveExistingFile(entry, projectDir, "Scene"), duration: null };
  }
  if (entry && typeof entry === "object" && !Array.isArray(entry)) {
    const rawPath = entry.path ?? entry.file ?? entry.src ?? entry.html;
    if (typeof rawPath !== "string" || !rawPath.trim()) {
      throw new Error(`Scene entry missing 'path'/'file'/'src'/'html': ${JSON.stringify(entry)}`);
    }
    const absScene = resolveExistingFile(rawPath, projectDir, "Scene");
    const rawDur = entry.duration ?? entry.total ?? null;
    const duration = rawDur !== null && rawDur !== undefined
      ? requireFiniteNumber(rawDur, "scene duration", { allowZero: false })
      : null;
    return { path: absScene, duration };
  }
  throw new Error(`Scene entry must be a path string or object, got ${typeof entry}`);
}

function parseOptionalTrack(audioCfg, keys, projectDir, label) {
  let raw = null;
  for (const key of keys) {
    if (key in audioCfg && audioCfg[key] !== null && audioCfg[key] !== undefined) {
      const candidate = audioCfg[key];
      if (typeof candidate !== "string") {
        throw new Error(`Audio '${keys[0]}' must be a path string or null, got ${JSON.stringify(candidate)}`);
      }
      if (!candidate.trim()) continue;
      raw = candidate;
      break;
    }
  }
  if (raw === null) return null;
  return resolveExistingFile(raw, projectDir, label);
}

function parseAudioConfig(rawAudio, projectDir) {
  if (rawAudio === null || rawAudio === undefined) return null;
  if (typeof rawAudio !== "object" || Array.isArray(rawAudio)) {
    throw new Error(`Project manifest 'audio' must be an object or null.`);
  }
  if (Object.keys(rawAudio).length === 0) return null;

  const voice = parseOptionalTrack(rawAudio, ["voice", "voice_path"], projectDir, "Audio voice");
  const bgm = parseOptionalTrack(rawAudio, ["bgm", "bgm_path"], projectDir, "Audio bgm");
  const sfx = parseOptionalTrack(rawAudio, ["sfx", "sfx_path"], projectDir, "Audio sfx");

  const rawKeep = rawAudio.keep_video_audio ?? false;
  if (typeof rawKeep !== "boolean") {
    throw new Error(`Audio 'keep_video_audio' must be a boolean, got ${JSON.stringify(rawKeep)}`);
  }

  if (!voice && !bgm && !sfx && !rawKeep) return null;

  return {
    voice,
    bgm,
    sfx,
    voice_vol: requireFiniteNumber(rawAudio.voice_vol ?? 1.0, "voice_vol", { allowZero: true }),
    bgm_vol: requireFiniteNumber(rawAudio.bgm_vol ?? 0.35, "bgm_vol", { allowZero: true }),
    video_vol: requireFiniteNumber(rawAudio.video_vol ?? 1.0, "video_vol", { allowZero: true }),
    fade_out: requireFiniteNumber(rawAudio.fade_out ?? 1.5, "fade_out", { allowZero: true }),
    keep_video_audio: rawKeep,
  };
}

function loadAndValidateManifest(inputPath, { scale = 1, fpsOverride = null, widthOverride = null, heightOverride = null } = {}) {
  const scaleVal = requireFiniteNumber(scale, "scale", { allowZero: false });
  const fpsOvr = fpsOverride !== null && fpsOverride !== undefined
    ? requireFiniteNumber(fpsOverride, "fps", { allowZero: false })
    : null;
  const widthOvr = widthOverride !== null && widthOverride !== undefined
    ? Math.round(requireFiniteNumber(widthOverride, "width", { allowZero: false }))
    : null;
  const heightOvr = heightOverride !== null && heightOverride !== undefined
    ? Math.round(requireFiniteNumber(heightOverride, "height", { allowZero: false }))
    : null;

  const absInput = resolveExistingFile(inputPath, process.cwd(), "Project/Scene");
  const projectDir = path.dirname(absInput);
  const ext = path.extname(absInput).toLowerCase();

  if (ext === ".html" || ext === ".htm") {
    const baseWidth = widthOvr ?? 1920;
    const baseHeight = heightOvr ?? 1080;
    return {
      kind: "scene",
      projectDir,
      manifestPath: absInput,
      fps: fpsOvr ?? 60,
      baseWidth,
      baseHeight,
      width: evenDimension(baseWidth * scaleVal),
      height: evenDimension(baseHeight * scaleVal),
      scale: scaleVal,
      scenes: [{ path: absInput, duration: null }],
      audio: null,
    };
  }

  if (ext !== ".json") {
    throw new Error(`Unsupported file extension "${ext}" (expected .json or .html/.htm): ${absInput}`);
  }

  const rawText = fs.readFileSync(absInput, "utf8");
  const data = JSON.parse(rawText);
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`Project manifest must be a JSON object: ${absInput}`);
  }

  const fps = fpsOvr ?? requireFiniteNumber(data.fps ?? 60, "fps", { allowZero: false });
  const rawW = widthOvr ?? Math.round(requireFiniteNumber(data.width ?? 1920, "width", { allowZero: false }));
  const rawH = heightOvr ?? Math.round(requireFiniteNumber(data.height ?? 1080, "height", { allowZero: false }));
  if (rawW <= 0 || rawH <= 0) {
    throw new Error(`Project width and height must be positive integers, got ${rawW}x${rawH}`);
  }

  if (!Array.isArray(data.scenes) || data.scenes.length === 0) {
    throw new Error("Project manifest 'scenes' must be a non-empty list.");
  }
  const scenes = data.scenes.map((item) => parseSceneEntry(item, projectDir));
  const audio = parseAudioConfig(data.audio, projectDir);

  return {
    kind: "project",
    projectDir,
    manifestPath: absInput,
    fps,
    baseWidth: rawW,
    baseHeight: rawH,
    width: evenDimension(rawW * scaleVal),
    height: evenDimension(rawH * scaleVal),
    scale: scaleVal,
    scenes,
    audio,
  };
}

function ensureExecutableOnPath(cmd, args) {
  try {
    execFileSync(cmd, args, { stdio: "ignore", timeout: 5000 });
    return true;
  } catch {
    return false;
  }
}

function findPythonExecutable() {
  const candidates = [];
  if (process.env.KINEARC_PYTHON) candidates.push(process.env.KINEARC_PYTHON);
  if (process.env.PYTHON) candidates.push(process.env.PYTHON);
  if (process.platform === "win32") {
    candidates.push("python", "python3");
  } else {
    candidates.push("python3", "python");
  }
  for (const bin of candidates) {
    if (ensureExecutableOnPath(bin, ["--version"])) return bin;
  }
  throw new Error("Python executable ('python' / 'python3') not found on PATH for audio mixing.");
}

function isUnderRoot(rootReal, targetReal) {
  const rel = path.relative(rootReal, targetReal);
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

function buildMountConfig(baseDir, scenePaths) {
  const realBase = fs.realpathSync(baseDir);
  const externalRoots = new Map();
  const sceneUrls = [];

  for (const scenePath of scenePaths) {
    const realScene = fs.realpathSync(scenePath);
    if (isUnderRoot(realBase, realScene)) {
      const rel = path.relative(realBase, realScene).split(path.sep).map(encodeURIComponent).join("/");
      sceneUrls.push(`/${rel}`);
    } else {
      const sceneDir = path.dirname(realScene);
      let mountIdx = externalRoots.get(sceneDir);
      if (mountIdx === undefined) {
        mountIdx = externalRoots.size;
        externalRoots.set(sceneDir, mountIdx);
      }
      const fileName = encodeURIComponent(path.basename(realScene));
      sceneUrls.push(`/__kinearc_mount_${mountIdx}/${fileName}`);
    }
  }

  const mounts = [{ prefix: "/", rootReal: realBase }];
  for (const [dirReal, idx] of externalRoots.entries()) {
    mounts.unshift({ prefix: `/__kinearc_mount_${idx}/`, rootReal: dirReal });
  }
  return { mounts, sceneUrls };
}

function startLocalServer({ mounts, runToken, onChunk }) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(async (req, res) => {
      try {
        const parsed = new URL(req.url || "/", "http://127.0.0.1");
        if (req.method === "POST" && parsed.pathname === "/__kinearc_chunk") {
          if (req.headers["x-kinearc-token"] !== runToken) {
            res.writeHead(403, { "Content-Type": "text/plain" });
            res.end("Forbidden");
            return;
          }
          const parts = [];
          for await (const chunk of req) {
            parts.push(chunk);
          }
          const buf = Buffer.concat(parts);
          await onChunk(buf);
          res.writeHead(200, { "Content-Type": "text/plain", "Cache-Control": "no-store" });
          res.end("ok");
          return;
        }

        if (req.method !== "GET" && req.method !== "HEAD") {
          res.writeHead(405, { "Content-Type": "text/plain" });
          res.end("Method Not Allowed");
          return;
        }

        let decodedPath;
        try {
          decodedPath = decodeURIComponent(parsed.pathname);
        } catch {
          res.writeHead(400, { "Content-Type": "text/plain" });
          res.end("Bad Request");
          return;
        }

        if (decodedPath.includes("\0")) {
          res.writeHead(403, { "Content-Type": "text/plain" });
          res.end("Forbidden");
          return;
        }

        let matchedMount = null;
        let relSegment = "";
        for (const m of mounts) {
          if (m.prefix === "/") {
            matchedMount = m;
            relSegment = decodedPath.replace(/^\/+/, "");
            break;
          }
          if (decodedPath.startsWith(m.prefix)) {
            matchedMount = m;
            relSegment = decodedPath.slice(m.prefix.length);
            break;
          }
        }
        if (!matchedMount) {
          res.writeHead(404, { "Content-Type": "text/plain" });
          res.end("Not Found");
          return;
        }

        const candidate = path.resolve(matchedMount.rootReal, relSegment);
        if (!isUnderRoot(matchedMount.rootReal, candidate)) {
          res.writeHead(403, { "Content-Type": "text/plain" });
          res.end("Forbidden");
          return;
        }

        let realFile;
        try {
          realFile = fs.realpathSync(candidate);
        } catch {
          res.writeHead(404, { "Content-Type": "text/plain" });
          res.end("Not Found");
          return;
        }
        if (!isUnderRoot(matchedMount.rootReal, realFile)) {
          res.writeHead(403, { "Content-Type": "text/plain" });
          res.end("Forbidden");
          return;
        }

        const stat = fs.statSync(realFile);
        if (!stat.isFile()) {
          res.writeHead(404, { "Content-Type": "text/plain" });
          res.end("Not Found");
          return;
        }

        const ext = path.extname(realFile).toLowerCase();
        const contentType = MIME_TYPES[ext] || "application/octet-stream";
        res.writeHead(200, {
          "Content-Type": contentType,
          "Content-Length": stat.size,
          "Cache-Control": "no-store",
        });
        if (req.method === "HEAD") {
          res.end();
          return;
        }
        const stream = fs.createReadStream(realFile);
        stream.on("error", (streamErr) => {
          if (!res.headersSent) {
            res.writeHead(500, { "Content-Type": "text/plain" });
            res.end(streamErr?.message || "Internal Server Error");
          } else {
            res.destroy();
          }
        });
        stream.pipe(res);
      } catch (err) {
        if (!res.headersSent) {
          res.writeHead(500, { "Content-Type": "text/plain" });
          res.end(err?.message || "Internal Server Error");
        } else {
          res.destroy();
        }
      }
    });

    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      resolve({
        server,
        port: addr.port,
        baseUrl: `http://127.0.0.1:${addr.port}`,
        close: () =>
          new Promise((resClose) => {
            if (typeof server.closeAllConnections === "function") {
              server.closeAllConnections();
            }
            server.close(() => resClose());
          }),
      });
    });
  });
}

function removeDirWithRetries(dirPath, attempts = 8, delayMs = 100) {
  for (let i = 0; i < attempts; i++) {
    try {
      fs.rmSync(dirPath, { recursive: true, force: true });
      return;
    } catch {
      if (i === attempts - 1) return;
      const until = Date.now() + delayMs;
      while (Date.now() < until) {
        // Brief sync backoff on Windows file lock release
      }
    }
  }
}

function buildBrowserProcessEnv(baseEnv = process.env) {
  const env = { ...baseEnv };
  if (process.platform === "win32") {
    return env;
  }
  // Chromium binds its SingletonSocket inside $TMPDIR (sun_path <= 107 bytes on POSIX).
  // Deep TMPDIR values (e.g., pytest tmp_path on CI) crash Chrome with "Socket path too long".
  const curTmp = String(env.TMPDIR || env.TMP || env.TEMP || os.tmpdir());
  if (Buffer.byteLength(curTmp, "utf8") <= 55) {
    return env;
  }
  try {
    fs.accessSync("/tmp", fs.constants.W_OK | fs.constants.X_OK);
    env.TMPDIR = "/tmp";
    env.TMP = "/tmp";
    env.TEMP = "/tmp";
  } catch {
    // Keep caller environment unchanged if /tmp is unavailable.
  }
  return env;
}

async function launchBrowserSession({ browserPath, timeoutMs = DEFAULT_READY_TIMEOUT_MS }) {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "kinearc-chrome-"));
  const chromeArgs = [
    "--headless=new",
    "--remote-debugging-port=0",
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-dev-shm-usage",
    "--enable-webgl",
    "--ignore-gpu-blocklist",
    "--mute-audio",
    "--autoplay-policy=no-user-gesture-required",
    ...(process.platform === "linux" ? ["--no-sandbox"] : []),
    "about:blank",
  ];

  const proc = spawn(browserPath, chromeArgs, {
    stdio: ["ignore", "pipe", "pipe"],
    env: buildBrowserProcessEnv(),
  });

  let ws = null;
  let exited = false;
  const exitPromise = new Promise((resolve) => {
    proc.once("exit", () => {
      exited = true;
      resolve();
    });
  });

  const cleanup = async () => {
    try {
      if (ws && ws.readyState === WebSocket.OPEN) {
        await Promise.race([
          cdpSend("Browser.close").catch(() => {}),
          new Promise((r) => setTimeout(r, 1200)),
        ]);
      }
    } catch {
      // ignore
    }
    try {
      if (ws && ws.readyState !== WebSocket.CLOSED) ws.close();
    } catch {
      // ignore
    }
    if (!exited) {
      try {
        proc.kill();
      } catch {
        // ignore
      }
      await Promise.race([exitPromise, new Promise((r) => setTimeout(r, 2000))]);
    }
    removeDirWithRetries(userDataDir);
  };

  let seq = 0;
  const pending = new Map();
  const listeners = new Map();

  const cdpSend = (method, params = {}) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error(`CDP WebSocket is not open for ${method}`));
    }
    return new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject, method });
      ws.send(JSON.stringify({ id, method, params }));
    });
  };

  const cdpOn = (method, fn) => {
    if (!listeners.has(method)) listeners.set(method, new Set());
    listeners.get(method).add(fn);
    return () => listeners.get(method)?.delete(fn);
  };

  const cdpWaitEvent = (method, waitMs) => {
    let cancelFn = () => {};
    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        off();
        reject(new Error(`Timed out after ${waitMs}ms waiting for CDP event ${method}`));
      }, waitMs);
      timer.unref?.();
      const off = cdpOn(method, (params) => {
        clearTimeout(timer);
        off();
        resolve(params);
      });
      cancelFn = () => {
        clearTimeout(timer);
        off();
      };
    });
    promise.catch(() => {});
    promise.cancel = cancelFn;
    return promise;
  };

  try {
    const devToolsWsUrl = await new Promise((resolve, reject) => {
      let stderrBuf = "";
      const onExitEarly = (code) => {
        clearTimeout(timer);
        proc.stderr.off("data", onData);
        reject(new Error(`Headless browser exited early (code ${code}).\n${stderrBuf}`));
      };
      const timer = setTimeout(() => {
        proc.off("exit", onExitEarly);
        proc.stderr.off("data", onData);
        reject(new Error(`Timed out waiting for headless browser DevTools endpoint.\n${stderrBuf}`));
      }, timeoutMs);
      timer.unref?.();

      const onData = (chunk) => {
        stderrBuf += chunk.toString("utf8");
        const m = stderrBuf.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (m) {
          clearTimeout(timer);
          proc.off("exit", onExitEarly);
          proc.stderr.off("data", onData);
          resolve(m[1]);
        }
      };
      proc.stderr.on("data", onData);
      proc.once("exit", onExitEarly);
    });

    const devHost = new URL(devToolsWsUrl).host;
    let targets = await (await fetch(`http://${devHost}/json/list`)).json();
    let pageTarget = targets.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
    if (!pageTarget) {
      pageTarget = await (await fetch(`http://${devHost}/json/new?about:blank`)).json();
    }
    if (!pageTarget?.webSocketDebuggerUrl) {
      throw new Error("Could not acquire a page WebSocket debugger URL from headless browser.");
    }

    ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", (ev) => reject(new Error(`CDP WebSocket error: ${ev?.message || "connect failed"}`)), { once: true });
    });

    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(String(ev.data));
      if (msg.id !== undefined && pending.has(msg.id)) {
        const entry = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) {
          entry.reject(new Error(`CDP ${entry.method} error: ${msg.error.message || JSON.stringify(msg.error)}`));
        } else {
          entry.resolve(msg.result);
        }
        return;
      }
      if (msg.method && listeners.has(msg.method)) {
        for (const fn of listeners.get(msg.method)) {
          try {
            fn(msg.params || {});
          } catch {
            // keep event dispatch resilient
          }
        }
      }
    });

    ws.addEventListener("close", () => {
      for (const [, entry] of pending) {
        entry.reject(new Error(`CDP WebSocket closed while waiting for ${entry.method}`));
      }
      pending.clear();
    });

    await cdpSend("Page.enable");
    await cdpSend("Runtime.enable");
    await cdpSend("Runtime.addBinding", { name: "__kinearcProgress" });

    return { send: cdpSend, on: cdpOn, waitEvent: cdpWaitEvent, close: cleanup };
  } catch (err) {
    await cleanup();
    throw err;
  }
}

function formatCdpException(exceptionDetails) {
  if (!exceptionDetails) return "Unknown page evaluation error";
  const desc = exceptionDetails.exception?.description || exceptionDetails.exception?.value;
  return desc ? String(desc) : String(exceptionDetails.text || "Page evaluation error");
}

async function evaluateOrThrow(cdp, expression, { awaitPromise = true } = {}) {
  const res = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise,
    returnByValue: true,
  });
  if (res.exceptionDetails) {
    throw new Error(formatCdpException(res.exceptionDetails));
  }
  return res.result?.value;
}

function withDeadline(promise, timeoutMs, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]).finally(() => clearTimeout(timer));
}

async function navigateAndAwaitReady({ cdp, url, outW, outH, timeoutMs }) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: outW,
    height: outH,
    deviceScaleFactor: 1,
    mobile: false,
  });

  const pageErrors = [];
  const offErr = cdp.on("Runtime.exceptionThrown", (params) => {
    pageErrors.push(formatCdpException(params.exceptionDetails));
  });

  try {
    return await withDeadline(
      (async () => {
        const loadPromise = cdp.waitEvent("Page.loadEventFired", timeoutMs);
        try {
          const nav = await cdp.send("Page.navigate", { url });
          if (nav?.errorText) {
            throw new Error(`Navigation error: ${nav.errorText}`);
          }
          await loadPromise;
        } finally {
          loadPromise.cancel?.();
        }

        const info = await evaluateOrThrow(
          cdp,
          `(async () => {
            const k = window.kinearc;
            const hasReady = Boolean(
              (k && "ready" in k && k.ready !== undefined) ||
              ("ready" in window && window.ready !== undefined)
            );
            if (hasReady) {
              const readyVal = k && k.ready !== undefined ? k.ready : window.ready;
              await Promise.resolve(readyVal);
            } else if (document.fonts && document.fonts.ready) {
              await document.fonts.ready;
            }
            const seekFn = (k && typeof k.seek === "function") ? k.seek.bind(k)
              : (typeof window.renderAt === "function") ? window.renderAt.bind(window)
              : (typeof window.seek === "function") ? window.seek.bind(window)
              : null;
            const rawTotal = (k && (k.totalDuration ?? k.total)) ?? window.TOTAL ?? null;
            return { hasSeek: Boolean(seekFn), rawTotal };
          })()`,
          { awaitPromise: true }
        );

        return info;
      })(),
      timeoutMs,
      `Timed out after ${timeoutMs}ms waiting for scene ready: ${url}`
    ).then(
      (info) => {
        if (pageErrors.length > 0) {
          throw new Error(`Scene failed (${url}): ${pageErrors[0]}`);
        }
        info.pageErrors = pageErrors;
        return info;
      },
      (err) => {
        if (err.message.startsWith(`Scene failed (${url}):`)) throw err;
        const extra = pageErrors.length ? ` (${pageErrors[0]})` : "";
        throw new Error(`Scene failed (${url}): ${err.message}${extra}`);
      }
    );
  } finally {
    offErr();
  }
}

async function seekScene(cdp, timeSec) {
  await evaluateOrThrow(
    cdp,
    `(async () => {
      const k = window.kinearc;
      const seekFn = (k && typeof k.seek === "function") ? k.seek.bind(k)
        : (typeof window.renderAt === "function") ? window.renderAt.bind(window)
        : (typeof window.seek === "function") ? window.seek.bind(window)
        : null;
      if (seekFn) {
        const ret = seekFn(${JSON.stringify(timeSec)});
        if (ret && typeof ret.then === "function") await ret;
      }
      if (document.body) void document.body.offsetHeight;
    })()`,
    { awaitPromise: true }
  );
}

function writeToStream(stream, buffer) {
  return new Promise((resolve, reject) => {
    if (stream.destroyed || !stream.writable) {
      reject(new Error("FFmpeg stdin stream is closed."));
      return;
    }
    const onError = (err) => {
      stream.off("drain", onDrain);
      reject(err);
    };
    const onDrain = () => {
      stream.off("error", onError);
      resolve();
    };
    stream.once("error", onError);
    const ok = stream.write(buffer);
    if (ok) {
      stream.off("error", onError);
      resolve();
    } else {
      stream.once("drain", onDrain);
    }
  });
}

function spawnFfmpegPipe(args) {
  const proc = spawn("ffmpeg", args, { stdio: ["pipe", "ignore", "pipe"] });
  let stderr = "";
  let aborted = false;
  let exitError = null;
  let settled = false;

  proc.stderr.on("data", (d) => {
    stderr += d.toString("utf8");
  });
  proc.stdin.on("error", () => {
    // Prevent unhandled stream 'error' event on EPIPE when ffmpeg exits early
  });

  const closed = new Promise((resolve) => {
    proc.once("close", () => {
      settled = true;
      resolve();
    });
  });

  const done = new Promise((resolve, reject) => {
    proc.once("error", (err) => {
      exitError = err;
      settled = true;
      reject(err);
    });
    proc.once("close", (code, signal) => {
      settled = true;
      if (aborted) {
        resolve();
        return;
      }
      if (code === 0) {
        resolve();
      } else {
        const msg = `ffmpeg exited with code ${code ?? `signal:${signal}`}:\n${stderr.slice(-1600)}`;
        exitError = new Error(msg);
        reject(exitError);
      }
    });
  });
  done.catch(() => {});

  return {
    proc,
    done,
    write: async (buf) => {
      if (aborted) throw new Error("FFmpeg pipe aborted.");
      if (exitError) throw exitError;
      await writeToStream(proc.stdin, buf);
      if (exitError) throw exitError;
    },
    finish: async () => {
      if (!proc.stdin.writableEnded && !proc.stdin.destroyed) {
        proc.stdin.end();
      }
      await done;
    },
    abort: async () => {
      aborted = true;
      try {
        if (!proc.stdin.destroyed) proc.stdin.destroy();
      } catch {
        // ignore
      }
      if (!settled) {
        try {
          if (!proc.killed) proc.kill();
        } catch {
          // ignore
        }
        let sigtermTimer = null;
        let sigkillTimer = null;
        const clearTimers = () => {
          if (sigtermTimer !== null) {
            clearTimeout(sigtermTimer);
            sigtermTimer = null;
          }
          if (sigkillTimer !== null) {
            clearTimeout(sigkillTimer);
            sigkillTimer = null;
          }
        };
        closed.then(clearTimers);
        try {
          await Promise.race([
            closed,
            new Promise((resolve) => {
              sigtermTimer = setTimeout(() => {
                try {
                  if (!settled) proc.kill("SIGKILL");
                } catch {
                  // ignore
                }
                resolve();
              }, 2000);
              sigtermTimer.unref?.();
            }),
          ]);
          if (!settled) {
            await Promise.race([
              closed,
              new Promise((resolve) => {
                sigkillTimer = setTimeout(resolve, 1000);
                sigkillTimer.unref?.();
              }),
            ]);
          }
        } finally {
          clearTimers();
        }
      }
      await done.catch(() => {});
    },
  };
}

async function detectWebCodecsPlan(cdp, { outW, outH, fps, crf }) {
  const targetBitrate = Math.round(
    Math.max(2_000_000, Math.min(80_000_000, outW * outH * fps * 0.12 * Math.pow(2, (16 - crf) / 6)))
  );

  return await evaluateOrThrow(
    cdp,
    `(async () => {
      const canvases = Array.from(document.querySelectorAll("canvas")).filter((c) => {
        const st = getComputedStyle(c);
        const r = c.getBoundingClientRect();
        return st.display !== "none" && st.visibility !== "hidden" && parseFloat(st.opacity) > 0 && r.width > 0 && r.height > 0;
      });
      if (canvases.length === 0) {
        return { mode: "cdp_png", reason: "no_canvas" };
      }

      let primary = canvases[0];
      let bestArea = 0;
      let bestRect = primary.getBoundingClientRect();
      for (const c of canvases) {
        const r = c.getBoundingClientRect();
        const area = r.width * r.height;
        if (area >= bestArea) {
          bestArea = area;
          primary = c;
          bestRect = r;
        }
      }

      const fillsViewport =
        Math.abs(bestRect.width - ${outW}) <= 2 && Math.abs(bestRect.height - ${outH}) <= 2;
      if (!fillsViewport) {
        return { mode: "cdp_png", reason: "canvas_not_full_viewport" };
      }

      const ancestors = new Set();
      for (let node = primary; node; node = node.parentElement) ancestors.add(node);

      let hasOverlayDom = false;
      if (document.body) {
        for (const el of document.body.querySelectorAll("*")) {
          if (el === primary || ancestors.has(el)) continue;
          const tag = el.tagName;
          if (tag === "SCRIPT" || tag === "STYLE" || tag === "META" || tag === "LINK" || tag === "TITLE" || tag === "NOSCRIPT") {
            continue;
          }
          const st = getComputedStyle(el);
          if (st.display === "none" || st.visibility === "hidden" || parseFloat(st.opacity) <= 0) continue;
          const r = el.getBoundingClientRect();
          if (r.width <= 0 || r.height <= 0) continue;

          const hasDirectText = Array.from(el.childNodes).some(
            (n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim().length > 0
          );
          const hasNonZeroBg = st.backgroundColor && st.backgroundColor !== "rgba(0, 0, 0, 0)" && st.backgroundColor !== "transparent";
          const hasBgImg = st.backgroundImage && st.backgroundImage !== "none";
          const isVisualTag = tag === "SVG" || tag === "IMG" || tag === "VIDEO" || tag === "CANVAS";
          if (hasDirectText || hasNonZeroBg || hasBgImg || isVisualTag) {
            hasOverlayDom = true;
            break;
          }
        }
      }

      if (hasOverlayDom) {
        return { mode: "cdp_png", reason: "dom_overlay" };
      }
      if (typeof VideoEncoder === "undefined" || typeof VideoFrame === "undefined") {
        return { mode: "cdp_png", reason: "webcodecs_unavailable" };
      }

      const candidates = ${JSON.stringify(WEBCODECS_CANDIDATES)};
      for (const codec of candidates) {
        try {
          const support = await VideoEncoder.isConfigSupported({
            codec,
            width: ${outW},
            height: ${outH},
            bitrate: ${targetBitrate},
            framerate: ${fps},
            latencyMode: "realtime",
            avc: { format: "annexb" },
          });
          if (support.supported) {
            return {
              mode: "webcodecs",
              codec,
              bitrate: ${targetBitrate},
              canvasExact: primary.width === ${outW} && primary.height === ${outH},
            };
          }
        } catch {
          // try next codec candidate
        }
      }
      return { mode: "cdp_png", reason: "codec_unsupported" };
    })()`,
    { awaitPromise: true }
  );
}

async function renderSceneWebCodecs({
  cdp,
  plan,
  segPath,
  outW,
  outH,
  fps,
  sceneFrames,
  runToken,
  setChunkHandler,
  onFrameProgress,
}) {
  const ff = spawnFfmpegPipe([
    "-y",
    "-fflags",
    "+genpts",
    "-f",
    "h264",
    "-r",
    String(fps),
    "-i",
    "pipe:0",
    "-c:v",
    "copy",
    "-bsf:v",
    `setts=pts=N/(${fps}*TB):dts=N/(${fps}*TB):duration=1/(${fps}*TB)`,
    "-movflags",
    "+faststart",
    segPath,
  ]);

  let chunkCount = 0;
  setChunkHandler(async (buf) => {
    chunkCount++;
    await ff.write(buf);
  });

  const offBinding = cdp.on("Runtime.bindingCalled", (params) => {
    if (params.name === "__kinearcProgress") {
      const localFrame = Number(params.payload);
      if (Number.isFinite(localFrame) && localFrame > 0) {
        onFrameProgress(localFrame);
      }
    }
  });

  try {
    const keyInterval = Math.max(1, Math.round(fps));
    const encRes = await evaluateOrThrow(
      cdp,
      `(async () => {
        const canvases = Array.from(document.querySelectorAll("canvas")).filter((c) => {
          const st = getComputedStyle(c);
          const r = c.getBoundingClientRect();
          return st.display !== "none" && st.visibility !== "hidden" && parseFloat(st.opacity) > 0 && r.width > 0 && r.height > 0;
        });
        let primary = canvases[0];
        let bestArea = 0;
        for (const c of canvases) {
          const r = c.getBoundingClientRect();
          if (r.width * r.height >= bestArea) {
            bestArea = r.width * r.height;
            primary = c;
          }
        }

        const outW = ${outW};
        const outH = ${outH};
        const fps = ${fps};
        const totalFrames = ${sceneFrames};
        const needsResize = primary.width !== outW || primary.height !== outH;
        const off = needsResize ? new OffscreenCanvas(outW, outH) : null;
        const offCtx = off ? off.getContext("2d") : null;

        const k = window.kinearc;
        const seekFn = (k && typeof k.seek === "function") ? k.seek.bind(k)
          : (typeof window.renderAt === "function") ? window.renderAt.bind(window)
          : (typeof window.seek === "function") ? window.seek.bind(window)
          : null;

        let encoderErr = null;
        let encodedChunks = 0;
        let uploadChain = Promise.resolve();

        const encoder = new VideoEncoder({
          output: (chunk) => {
            encodedChunks++;
            const buf = new Uint8Array(chunk.byteLength);
            chunk.copyTo(buf);
            uploadChain = uploadChain.then(async () => {
              const resp = await fetch(location.origin + "/__kinearc_chunk", {
                method: "POST",
                headers: { "x-kinearc-token": ${JSON.stringify(runToken)} },
                body: buf,
              });
              if (!resp.ok) {
                throw new Error("Chunk upload failed with HTTP " + resp.status);
              }
            });
          },
          error: (err) => {
            encoderErr = err?.message || String(err);
          },
        });

        encoder.configure({
          codec: ${JSON.stringify(plan.codec)},
          width: outW,
          height: outH,
          bitrate: ${plan.bitrate},
          framerate: fps,
          latencyMode: "realtime",
          avc: { format: "annexb" },
        });

        try {
          for (let f = 0; f < totalFrames; f++) {
            if (encoderErr) throw new Error(encoderErr);
            const t = f / fps;
            if (seekFn) {
              try {
                const r = seekFn(t);
                if (r && typeof r.then === "function") await r;
              } catch (seekErr) {
                const msg = seekErr?.message || String(seekErr);
                throw new Error("__KINEARC_SCENE_ERR__:" + msg);
              }
            }
            let src = primary;
            if (needsResize) {
              offCtx.clearRect(0, 0, outW, outH);
              offCtx.drawImage(primary, 0, 0, outW, outH);
              src = off;
            }
            const tsUs = Math.round((f * 1_000_000) / fps);
            const nextUs = Math.round(((f + 1) * 1_000_000) / fps);
            const durUs = Math.max(1, nextUs - tsUs);
            const vf = new VideoFrame(src, { timestamp: tsUs, duration: durUs });
            encoder.encode(vf, { keyFrame: f === 0 || (f % ${keyInterval} === 0) });
            vf.close();

            if (typeof window.__kinearcProgress === "function") {
              window.__kinearcProgress(String(f + 1));
            }
            if (encoder.encodeQueueSize >= 8 || f % 10 === 9) {
              while (encoder.encodeQueueSize >= 8 && !encoderErr) {
                await new Promise((res) => setTimeout(res, 1));
              }
              await new Promise((res) => setTimeout(res, 0));
            }
          }
          await encoder.flush();
          await uploadChain;
          if (encoderErr) throw new Error(encoderErr);
          return { encodedChunks };
        } finally {
          try {
            if (encoder.state !== "closed") encoder.close();
          } catch {
            // ignore
          }
        }
      })()`,
      { awaitPromise: true }
    );

    await ff.finish();
    if (!encRes || encRes.encodedChunks === 0 || chunkCount === 0) {
      throw new Error("WebCodecs produced zero H.264 chunks.");
    }
    return { mode: "webcodecs", chunks: chunkCount };
  } catch (err) {
    await ff.abort();
    throw err;
  } finally {
    offBinding();
    setChunkHandler(async () => {});
  }
}

async function renderSceneCdpPng({ cdp, segPath, fps, crf, sceneFrames, onFrameProgress }) {
  const ff = spawnFfmpegPipe([
    "-y",
    "-f",
    "image2pipe",
    "-vcodec",
    "png",
    "-framerate",
    String(fps),
    "-i",
    "pipe:0",
    "-r",
    String(fps),
    "-c:v",
    "libx264",
    "-crf",
    String(crf),
    "-pix_fmt",
    "yuv420p",
    "-preset",
    "medium",
    "-movflags",
    "+faststart",
    segPath,
  ]);

  try {
    for (let f = 0; f < sceneFrames; f++) {
      const t = f / fps;
      await seekScene(cdp, t);
      const shot = await cdp.send("Page.captureScreenshot", {
        format: "png",
        optimizeForSpeed: true,
      });
      await ff.write(Buffer.from(shot.data, "base64"));
      onFrameProgress(f + 1);
    }
    await ff.finish();
    return { mode: "cdp_png" };
  } catch (err) {
    await ff.abort();
    throw err;
  }
}

function runCommandChecked(cmd, args, { suppressStdout = false } = {}) {
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, {
      stdio: ["ignore", suppressStdout ? "pipe" : "inherit", "pipe"],
    });
    let stdoutBuf = "";
    let stderrBuf = "";
    if (proc.stdout) {
      proc.stdout.on("data", (d) => {
        stdoutBuf += d.toString("utf8");
      });
    }
    proc.stderr.on("data", (d) => {
      stderrBuf += d.toString("utf8");
    });
    proc.once("error", reject);
    proc.once("exit", (code) => {
      if (code === 0) resolve({ stdout: stdoutBuf, stderr: stderrBuf });
      else reject(new Error(`${cmd} exited with code ${code}:\n${stderrBuf || stdoutBuf}`));
    });
  });
}

function copyOrMoveFile(src, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  try {
    fs.renameSync(src, dest);
  } catch {
    fs.copyFileSync(src, dest);
    try {
      fs.unlinkSync(src);
    } catch {
      // ignore
    }
  }
}

async function cmdStills(flags) {
  if (!flags.scene) throw new Error("--scene is required for 'stills'.");
  if (!flags.times) throw new Error("--times is required for 'stills'.");

  const scale = flags.scale !== undefined ? requireFiniteNumber(flags.scale, "scale", { allowZero: false }) : 1;
  const rawTokens = String(flags.times)
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  if (rawTokens.length === 0) {
    throw new Error("--times must provide at least one timestamp in seconds.");
  }
  const times = rawTokens.map((tok) => requireFiniteNumber(tok, "timestamp", { allowZero: true }));
  const timeoutMs = flags.timeout !== undefined
    ? requireFiniteNumber(flags.timeout, "timeout", { allowZero: false })
    : DEFAULT_READY_TIMEOUT_MS;

  const manifest = loadAndValidateManifest(flags.scene, {
    scale,
    widthOverride: flags.width,
    heightOverride: flags.height,
  });
  const browserPath = requireBrowserExecutable();
  const outDir = path.resolve(flags.out_dir || flags["out-dir"] || ".kinearc_analysis/stills");
  fs.mkdirSync(outDir, { recursive: true });

  const { mounts, sceneUrls } = buildMountConfig(manifest.projectDir, [manifest.scenes[0].path]);
  const runToken = crypto.randomBytes(16).toString("hex");
  const server = await startLocalServer({ mounts, runToken, onChunk: async () => {} });

  let browser = null;
  try {
    browser = await launchBrowserSession({ browserPath, timeoutMs });
    const savedPaths = [];

    for (let idx = 0; idx < times.length; idx++) {
      const t = times[idx];
      const urlObj = new URL(sceneUrls[0], server.baseUrl);
      urlObj.searchParams.set("t", String(t));
      urlObj.searchParams.set("scale", String(manifest.scale));

      await navigateAndAwaitReady({
        cdp: browser,
        url: urlObj.toString(),
        outW: manifest.width,
        outH: manifest.height,
        timeoutMs,
      });
      await seekScene(browser, t);

      const shot = await browser.send("Page.captureScreenshot", { format: "png" });
      const outFile = path.join(outDir, `still_${idx}_${t}s.png`);
      fs.writeFileSync(outFile, Buffer.from(shot.data, "base64"));
      savedPaths.push(outFile);
    }

    console.log(JSON.stringify({ ok: true, width: manifest.width, height: manifest.height, files: savedPaths }));
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}

async function cmdRender(flags) {
  if (!flags.project) throw new Error("--project is required for 'render'.");
  if (!flags.out) throw new Error("--out is required for 'render'.");

  const scale = flags.scale !== undefined ? requireFiniteNumber(flags.scale, "scale", { allowZero: false }) : 1;
  const crf = flags.crf !== undefined ? Number(flags.crf) : 16;
  if (!Number.isInteger(crf) || crf < 0 || crf > 51) {
    throw new Error(`crf must be an integer in [0, 51], got ${JSON.stringify(flags.crf)}`);
  }
  const jsonProgress = Boolean(flags["json-progress"]);
  const timeoutMs = flags.timeout !== undefined
    ? requireFiniteNumber(flags.timeout, "timeout", { allowZero: false })
    : DEFAULT_READY_TIMEOUT_MS;

  const manifest = loadAndValidateManifest(flags.project, {
    scale,
    fpsOverride: flags.fps,
    widthOverride: flags.width,
    heightOverride: flags.height,
  });

  const finalOut = path.resolve(flags.out);
  const browserPath = requireBrowserExecutable();
  if (!ensureExecutableOnPath("ffmpeg", ["-version"])) {
    throw new Error("ffmpeg executable not found on PATH.");
  }
  let pythonBin = null;
  if (manifest.audio !== null) {
    if (!fs.existsSync(AUDIO_MIX_PY)) {
      throw new Error(`audio_mix.py not found at ${AUDIO_MIX_PY}`);
    }
    pythonBin = findPythonExecutable();
  }

  const tempWorkDir = fs.mkdtempSync(path.join(os.tmpdir(), "kinearc-render-"));
  const { mounts, sceneUrls } = buildMountConfig(
    manifest.projectDir,
    manifest.scenes.map((s) => s.path)
  );
  const runToken = crypto.randomBytes(16).toString("hex");
  let activeChunkHandler = async () => {};
  const server = await startLocalServer({
    mounts,
    runToken,
    onChunk: (buf) => activeChunkHandler(buf),
  });

  let browser = null;
  try {
    browser = await launchBrowserSession({ browserPath, timeoutMs });
    const segmentRecords = [];
    const knownFramesPerScene = manifest.scenes.map((s) =>
      s.duration !== null ? Math.max(1, Math.round(s.duration * manifest.fps)) : null
    );
    let completedFramesPrior = 0;

    for (let i = 0; i < manifest.scenes.length; i++) {
      const scene = manifest.scenes[i];
      const urlObj = new URL(sceneUrls[i], server.baseUrl);
      urlObj.searchParams.set("scale", String(manifest.scale));
      urlObj.searchParams.set("t", "0");
      const sceneUrl = urlObj.toString();

      const readyInfo = await navigateAndAwaitReady({
        cdp: browser,
        url: sceneUrl,
        outW: manifest.width,
        outH: manifest.height,
        timeoutMs,
      });

      let sceneDur = null;
      if (readyInfo.rawTotal !== null && readyInfo.rawTotal !== undefined && Number.isFinite(Number(readyInfo.rawTotal)) && Number(readyInfo.rawTotal) > 0) {
        sceneDur = Number(readyInfo.rawTotal);
      } else if (scene.duration !== null) {
        sceneDur = scene.duration;
      } else {
        throw new Error(`Scene ${sceneUrl} did not report finite positive totalDuration/TOTAL and manifest omitted duration.`);
      }

      const sceneFrames = Math.max(1, Math.round(sceneDur * manifest.fps));
      knownFramesPerScene[i] = sceneFrames;

      const estimateTotalFrames = () => {
        let sum = 0;
        for (let idx = 0; idx < knownFramesPerScene.length; idx++) {
          sum += knownFramesPerScene[idx] ?? sceneFrames;
        }
        return Math.max(1, sum);
      };

      const emitProgress = (localFrame) => {
        if (!jsonProgress) return;
        const globalFrame = completedFramesPrior + localFrame;
        const globalTotal = estimateTotalFrames();
        const pct = Math.min(100, Math.round((globalFrame / globalTotal) * 10000) / 100);
        process.stdout.write(
          JSON.stringify({
            type: "progress",
            scene: i,
            frame: globalFrame,
            total: globalTotal,
            progress: pct,
          }) + "\n"
        );
      };

      const segPath = path.join(tempWorkDir, `seg_${String(i).padStart(4, "0")}.mp4`);
      const plan = await detectWebCodecsPlan(browser, {
        outW: manifest.width,
        outH: manifest.height,
        fps: manifest.fps,
        crf,
      });

      let result;
      if (plan.mode === "webcodecs") {
        try {
          result = await renderSceneWebCodecs({
            cdp: browser,
            plan,
            segPath,
            outW: manifest.width,
            outH: manifest.height,
            fps: manifest.fps,
            sceneFrames,
            runToken,
            setChunkHandler: (fn) => {
              activeChunkHandler = fn;
            },
            onFrameProgress: emitProgress,
          });
        } catch (webcodecsErr) {
          const msg = webcodecsErr?.message || "";
          const sceneIdx = msg.indexOf("__KINEARC_SCENE_ERR__:");
          if (sceneIdx !== -1) {
            throw new Error(msg.slice(sceneIdx + "__KINEARC_SCENE_ERR__:".length).trim());
          }
          if (!jsonProgress) {
            console.error(`[kinearc] WebCodecs fallback to CDP PNG on scene ${i}: ${msg}`);
          }
          result = await renderSceneCdpPng({
            cdp: browser,
            segPath,
            fps: manifest.fps,
            crf,
            sceneFrames,
            onFrameProgress: emitProgress,
          });
        }
      } else {
        result = await renderSceneCdpPng({
          cdp: browser,
          segPath,
          fps: manifest.fps,
          crf,
          sceneFrames,
          onFrameProgress: emitProgress,
        });
      }

      completedFramesPrior += sceneFrames;
      segmentRecords.push({ path: segPath, mode: result.mode });
    }

    let videoOnlyPath;
    if (segmentRecords.length === 1) {
      videoOnlyPath = segmentRecords[0].path;
    } else {
      videoOnlyPath = path.join(tempWorkDir, "concat_video.mp4");
      const concatListPath = path.join(tempWorkDir, "concat.txt");
      const listBody = segmentRecords
        .map((seg) => `file '${seg.path.replace(/\\/g, "/").replace(/'/g, "'\\''")}'`)
        .join("\n");
      fs.writeFileSync(concatListPath, listBody + "\n", "utf8");

      const uniformMode = segmentRecords.every((s) => s.mode === segmentRecords[0].mode);
      if (uniformMode) {
        await runCommandChecked(
          "ffmpeg",
          ["-y", "-f", "concat", "-safe", "0", "-i", concatListPath, "-c:v", "copy", "-movflags", "+faststart", videoOnlyPath],
          { suppressStdout: true }
        );
      } else {
        await runCommandChecked(
          "ffmpeg",
          [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concatListPath,
            "-r",
            String(manifest.fps),
            "-c:v",
            "libx264",
            "-crf",
            String(crf),
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-movflags",
            "+faststart",
            videoOnlyPath,
          ],
          { suppressStdout: true }
        );
      }
    }

    if (manifest.audio === null) {
      copyOrMoveFile(videoOnlyPath, finalOut);
    } else {
      fs.mkdirSync(path.dirname(finalOut), { recursive: true });
      const mixArgs = [
        AUDIO_MIX_PY,
        "mix",
        "--video",
        videoOnlyPath,
        "--out",
        finalOut,
        "--voice_vol",
        String(manifest.audio.voice_vol),
        "--bgm_vol",
        String(manifest.audio.bgm_vol),
        "--video_vol",
        String(manifest.audio.video_vol),
        "--fade_out",
        String(manifest.audio.fade_out),
      ];
      if (manifest.audio.voice) mixArgs.push("--voice", manifest.audio.voice);
      if (manifest.audio.bgm) mixArgs.push("--bgm", manifest.audio.bgm);
      if (manifest.audio.sfx) mixArgs.push("--sfx", manifest.audio.sfx);
      if (manifest.audio.keep_video_audio) mixArgs.push("--keep_video_audio");

      await runCommandChecked(pythonBin, mixArgs, { suppressStdout: jsonProgress });
    }

    if (jsonProgress) {
      process.stdout.write(
        JSON.stringify({
          type: "done",
          out: finalOut,
          width: manifest.width,
          height: manifest.height,
          fps: manifest.fps,
          frames: completedFramesPrior,
        }) + "\n"
      );
    } else {
      console.log(
        `[kinearc] Rendered ${completedFramesPrior} frames (${manifest.width}x${manifest.height} @ ${manifest.fps}fps) -> ${finalOut}`
      );
    }
  } finally {
    if (browser) await browser.close();
    await server.close();
    removeDirWithRetries(tempWorkDir);
  }
}

async function main() {
  const { command, flags } = parseCliArgs(process.argv.slice(2));
  if (command === "help" || flags.help) {
    printUsage();
    return;
  }
  if (command === "stills") {
    await cmdStills(flags);
    return;
  }
  if (command === "render") {
    await cmdRender(flags);
  }
}

main().catch((err) => {
  console.error(`[kinearc] Error: ${err?.message || err}`);
  process.exit(1);
});
