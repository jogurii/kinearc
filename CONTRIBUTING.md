# Contributing

Thank you for helping improve `kinearc`. The repository is intentionally lean: zero-build frontend ES modules, zero-dependency Node.js 24+ engine helpers, Python computer vision & HTTP tooling, and fast isolated pytest suites.

## Local Setup

```bash
git clone https://github.com/<your-username>/kinearc.git
cd kinearc
python install.py --agent all --link
python -B scripts/kinearc_cli.py doctor --strict
python -B -m pytest -p no:cacheprovider tests/ -v
```

Using `--link` creates a symlink or Windows directory junction to your checkout so changes apply immediately across installed AI agents.

## Repository Layout

```text
engine/       Zero-npm Node 24+ Chromium WebCodecs/CDP 4K renderer
scripts/      Python CLI, CV capture, audio mixing & Workbench server
scripts/ui/   Zero-build browser ES modules & dark-mode stylesheet
references/   Agent authoring guides (kinearc-engine, 3d, ad-craft, audio, etc.)
examples/     Ready-to-render 3D promo and interactive tutorial projects
tests/        Pytest unit, integration, API & headless browser E2E suites
install.py    Cross-platform skill installer & environment validator
```

## Change Guidelines

1. **Preserve zero-dependency simplicity:** `engine/` runs on Node.js 24+ built-ins (`WebSocket`, `fetch`, `node:http`, `node:child_process`) and `scripts/ui/` loads directly without a bundler. Avoid adding build steps or third-party dependencies unless strictly justified.
2. **Test before opening a PR:** Run both `node --check` on modified `.js`/`.mjs` files and `python -B -m pytest -p no:cacheprovider tests/ -v`. Keep `__pycache__`, `.pytest_cache`, and temporary `.kinearc_analysis` outputs out of commits.
3. **Keep security boundaries intact:** Any new file/path endpoint must confine paths under its designated root (`_safe_resolve_under` / `isUnderRoot`), bind only to `127.0.0.1`, and avoid `shell=True` subprocess execution.
4. **Update references truthfully:** Ensure `SKILL.md`, `README.md`, `CHANGELOG.md`, and `references/` match shipped behavior without stale placeholders.
