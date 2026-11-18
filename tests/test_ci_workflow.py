"""Regression guards for GitHub Actions CI workflow configuration."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _extract_linux_setup_block(workflow_text: str) -> str:
    match = re.search(
        r"(?ms)^[ \t]+- name: Install FFmpeg & (?:Chromium|Browser) \(Linux\)\n(?P<body>.*?)(?=^[ \t]+- name: |\Z)",
        workflow_text,
    )
    assert match is not None, "Missing Linux FFmpeg & Browser setup step in ci.yml"
    return match.group("body")


def test_ci_linux_setup_avoids_snap_apt_chromium_packages() -> None:
    """Ubuntu runners must not apt-install chromium-browser/chromium Snap shims."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    linux_step = _extract_linux_setup_block(text)

    assert "apt-get install" in linux_step and "ffmpeg" in linux_step
    for line in linux_step.splitlines():
        if "apt-get install" in line and ".deb" not in line:
            assert not re.search(r"\bchromium(?:-browser)?\b", line), (
                "Avoid apt-get installing Ubuntu Snap transitional chromium packages "
                f"in CI Linux setup step: {line!r}"
            )


def test_ci_linux_setup_uses_preinstalled_or_deb_browser_and_verifies_binaries() -> None:
    """Linux CI should prefer preinstalled Chrome/Chromium, fall back without Snap, and guard CHROME_PATH."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    linux_step = _extract_linux_setup_block(text)

    assert "google-chrome" in linux_step
    assert "CHROME_PATH=" in linux_step
    assert "GITHUB_ENV" in linux_step
    assert "ffmpeg -version" in linux_step
    assert "ffprobe -version" in linux_step
    assert "--version" in linux_step
    # Must fail explicitly if no browser binary resolved rather than exporting empty CHROME_PATH.
    assert re.search(r"\[ -z \"\$CHROME_BIN\" \]|test -n \"\$CHROME_BIN\"", linux_step)
