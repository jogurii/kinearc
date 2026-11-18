# Security Policy

## Scope

`kinearc` executes local media workflows on your machine: Python OpenCV/NumPy scripts, FFmpeg/FFprobe subprocesses, Node.js 24+ WebCodecs captures inside headless Chromium, and a local Workbench HTTP server bound strictly to `127.0.0.1`.

Because HTML scenes run inside a browser iframe/page as authored code (similar to local web development or scripts), vulnerabilities we take seriously include:

- Any ability for a malicious `kinearc.project.json`, filename, URL query parameter, or scene/audio field to traverse directories outside project/render roots (`_safe_resolve_under` / `isUnderRoot`) or overwrite arbitrary host files.
- Argument or shell command injection into FFmpeg, FFprobe, Chromium, or Python subprocesses.
- HTTP endpoints binding to non-loopback interfaces or permitting unintended cross-origin state mutation.
- HTML/DOM injection (XSS) inside `scripts/ui/` when displaying filenames, note text, or CLI error output.
- `install.py` modifying or deleting files outside the explicit `kinearc` skill directories printed to stdout.

## Reporting a Vulnerability

Please report suspected vulnerabilities privately via GitHub Security Advisories rather than opening a public issue:

`https://github.com/<your-username>/kinearc/security/advisories/new`

Include:
1. Affected commit or version (`v3.0.0`, etc.)
2. Minimal reproducing command, manifest, or HTTP request
3. Observed impact

## Supported Versions

Only the latest release/commit on `main` is actively maintained. `kinearc` never requires accounts, external API keys, or cloud credentials for its core CV, Workbench UI, audio mixing, or 4K render pipelines.
