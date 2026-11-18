/**
 * Cross-platform Chrome / Edge / Chromium executable discovery for kinearc.
 * Uses pure Node.js built-ins only.
 */

import fs from "node:fs";
import path from "node:path";

/**
 * Locate a Chromium-family browser executable.
 *
 * @param {object} [options]
 * @param {Record<string, string | undefined>} [options.env=process.env]
 * @param {(p: string) => boolean} [options.exists=fs.existsSync]
 * @param {string} [options.platform=process.platform]
 * @param {((name: string) => string | null) | null} [options.which=null]
 * @returns {string | null}
 */
export function findBrowserExecutable({
  env = process.env,
  exists = fs.existsSync,
  platform = process.platform,
  which = null,
} = {}) {
  const isDefaultExists = exists === fs.existsSync;
  const existsFile = (candidate) => {
    if (!candidate) return false;
    try {
      if (!exists(candidate)) return false;
      if (isDefaultExists) {
        return fs.statSync(candidate).isFile();
      }
      return true;
    } catch {
      return false;
    }
  };

  const rawOverride = env?.CHROME_PATH;
  if (typeof rawOverride === "string" && rawOverride.trim().length > 0) {
    const trimmed = rawOverride.trim();
    if (!existsFile(trimmed)) {
      throw new Error(
        `CHROME_PATH is set to "${trimmed}", but no browser executable exists at that path.`
      );
    }
    return trimmed;
  }

  const pathApi = platform === "win32" ? path.win32 : path.posix;

  const lookupOnPath = (names) => {
    if (typeof which === "function") {
      for (const name of names) {
        const hit = which(name);
        if (hit) return hit;
      }
      return null;
    }
    const rawPath = env?.PATH || env?.Path || "";
    const sep = platform === "win32" ? ";" : ":";
    const dirs = String(rawPath)
      .split(sep)
      .map((s) => s.trim())
      .filter(Boolean);
    for (const dir of dirs) {
      for (const name of names) {
        const direct = pathApi.join(dir, name);
        if (existsFile(direct)) return direct;
        if (platform === "win32" && !name.toLowerCase().endsWith(".exe")) {
          const withExe = `${direct}.exe`;
          if (existsFile(withExe)) return withExe;
        }
      }
    }
    return null;
  };

  const candidates = [];
  let pathNames = [];

  if (platform === "win32") {
    const roots = Array.from(
      new Set(
        [
          env?.PROGRAMFILES,
          env?.ProgramFiles,
          env?.["PROGRAMFILES(X86)"],
          env?.["ProgramFiles(x86)"],
          env?.LOCALAPPDATA,
          "C:\\Program Files",
          "C:\\Program Files (x86)",
        ]
          .map((v) => (typeof v === "string" ? v.trim() : ""))
          .filter(Boolean)
      )
    );
    for (const root of roots) {
      candidates.push(pathApi.join(root, "Google", "Chrome", "Application", "chrome.exe"));
    }
    for (const root of roots) {
      candidates.push(pathApi.join(root, "Microsoft", "Edge", "Application", "msedge.exe"));
    }
    for (const root of roots) {
      candidates.push(pathApi.join(root, "Chromium", "Application", "chrome.exe"));
    }
    pathNames = ["chrome", "google-chrome", "msedge", "chromium"];
  } else if (platform === "darwin") {
    candidates.push(
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
      "/Applications/Chromium.app/Contents/MacOS/Chromium"
    );
    const home = typeof env?.HOME === "string" ? env.HOME.trim() : "";
    if (home) {
      candidates.push(
        pathApi.join(home, "Applications", "Google Chrome.app", "Contents", "MacOS", "Google Chrome"),
        pathApi.join(home, "Applications", "Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge"),
        pathApi.join(home, "Applications", "Chromium.app", "Contents", "MacOS", "Chromium")
      );
    }
    pathNames = ["google-chrome", "chromium", "microsoft-edge"];
  } else {
    pathNames = [
      "google-chrome",
      "google-chrome-stable",
      "chromium",
      "chromium-browser",
      "microsoft-edge",
      "microsoft-edge-stable",
    ];
    candidates.push(
      "/usr/bin/google-chrome",
      "/usr/bin/google-chrome-stable",
      "/usr/bin/chromium",
      "/usr/bin/chromium-browser",
      "/usr/bin/microsoft-edge",
      "/usr/bin/microsoft-edge-stable",
      "/snap/bin/chromium"
    );
  }

  if (platform !== "win32" && platform !== "darwin") {
    const pathHit = lookupOnPath(pathNames);
    if (pathHit) return pathHit;
  }

  for (const candidate of candidates) {
    if (existsFile(candidate)) return candidate;
  }

  if (platform === "win32" || platform === "darwin") {
    const pathHit = lookupOnPath(pathNames);
    if (pathHit) return pathHit;
  }

  return null;
}

/**
 * Locate a Chromium-family browser executable or throw an actionable error.
 *
 * @param {Parameters<typeof findBrowserExecutable>[0]} [options]
 * @returns {string}
 */
export function requireBrowserExecutable(options = {}) {
  const found = findBrowserExecutable(options);
  if (!found) {
    throw new Error(
      "No Chrome, Edge, or Chromium executable was found. Install Chrome/Edge/Chromium or set CHROME_PATH."
    );
  }
  return found;
}
