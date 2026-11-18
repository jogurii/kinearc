#!/usr/bin/env python3
"""
review_viewer.py — Backward-Compatible Compatibility Shim for kinearc_ui.py
Part of the kinearc skill toolkit.

Delegates to `kinearc_ui.main` while preserving `ViewerState`, `make_handler`,
and `ReusableThreadingTCPServer` imports for existing callers.
"""

import argparse

try:
    import kinearc_ui
    from kinearc_ui import ReusableThreadingTCPServer, UiState, make_handler
except ImportError:
    from . import kinearc_ui
    from .kinearc_ui import ReusableThreadingTCPServer, UiState, make_handler


class ViewerState(UiState):
    """Backward-compatible wrapper preserving legacy (clone_path, ref_path, out_dir) positional args."""

    def __init__(
        self,
        clone_path: str | None = None,
        ref_path: str | None = None,
        out_dir: str = ".kinearc_analysis",
        **kwargs,
    ):
        super().__init__(clone_path=clone_path, ref_path=ref_path, out_dir=out_dir, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    """Build legacy CLI parser preserving the default .kinearc_analysis out_dir."""
    parser = argparse.ArgumentParser(description="Standalone Interactive Web Review & Annotation Viewer for kinearc.")
    parser.add_argument("clone", nargs="?", default=None, help="Path to rendered/reconstructed MP4 video")
    parser.add_argument("--ref", default=None, help="Optional reference video for comparison modes")
    parser.add_argument("--out_dir", default=".kinearc_analysis", help="Directory where selection.json and selection/ PNGs are saved")
    parser.add_argument("--port", type=int, default=4175, help="Local HTTP port")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open browser")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Delegate review_viewer CLI execution directly to kinearc_ui.main."""
    kinearc_ui.main(argv)


__all__ = [
    "ReusableThreadingTCPServer",
    "UiState",
    "ViewerState",
    "build_parser",
    "main",
    "make_handler",
]


if __name__ == "__main__":
    main()
