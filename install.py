#!/usr/bin/env python3
"""
install.py — Cross-platform zero-dependency installer for the kinearc skill.

Copies or links (`--link`) the core kinearc skill files (`SKILL.md`, `engine/`,
`scripts/`, `references/`, `README.md`, `LICENSE`) into AI coding agent skill
directories and validates the host toolchain via `scripts/kinearc_cli.py doctor`.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent
INSTALL_ITEMS = ("SKILL.md", "README.md", "LICENSE", "engine", "scripts", "references")
IGNORE_NAMES = {"__pycache__", ".pytest_cache", "node_modules", ".kinearc_analysis", ".git"}
IGNORE_SUFFIXES = {".pyc", ".pyo"}


def agent_skill_roots(home_dir: Path | None = None, workspace_dir: Path | None = None) -> dict[str, Path]:
    """Return mapping of supported agent keys to their global/workspace kinearc skill path."""
    home = Path(home_dir) if home_dir is not None else Path.home()
    ws = Path(workspace_dir) if workspace_dir is not None else REPO_ROOT
    return {
        "gemini": home / ".gemini" / "config" / "skills" / "kinearc",
        "kiro": home / ".kiro" / "skills" / "kinearc",
        "claude": home / ".claude" / "skills" / "kinearc",
        "agents": home / ".agents" / "skills" / "kinearc",
        "cursor": ws / ".agent" / "skills" / "kinearc",
    }


def resolve_targets(
    agent_arg: str = "all",
    skill_dirs: list[str] | None = None,
    home_dir: Path | None = None,
    workspace_dir: Path | None = None,
) -> list[Path]:
    """Resolve deduplicated list of destination `kinearc` skill paths."""
    roots = agent_skill_roots(home_dir=home_dir, workspace_dir=workspace_dir)
    selected: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        normalized = Path(os.path.abspath(str(p.expanduser())))
        key = os.path.normcase(str(normalized))
        if key not in seen:
            seen.add(key)
            selected.append(normalized)

    tokens = [tok.strip().lower() for tok in (agent_arg or "").split(",") if tok.strip()]
    if "none" not in tokens and (tokens or not skill_dirs):
        if not tokens or "all" in tokens:
            for key in ("gemini", "kiro", "claude", "agents"):
                _add(roots[key])
        else:
            for tok in tokens:
                if tok not in roots:
                    valid = ", ".join([*roots.keys(), "all", "none"])
                    raise ValueError(f"Unsupported agent target {tok!r}; choose from: {valid}")
                _add(roots[tok])

    for raw_dir in skill_dirs or []:
        p = Path(raw_dir).expanduser()
        target = p if p.name.lower() == "kinearc" else p / "kinearc"
        _add(target)

    return selected


def _ignore_filter(_directory: str, entries: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in entries:
        if name in IGNORE_NAMES or Path(name).suffix.lower() in IGNORE_SUFFIXES:
            ignored.add(name)
    return ignored


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    if hasattr(os.path, "isjunction"):
        try:
            return bool(os.path.isjunction(path))
        except OSError:
            return False
    return False


def _remove_existing(dest: Path) -> None:
    if not dest.exists() and not _is_link_or_junction(dest):
        return
    if _is_link_or_junction(dest):
        try:
            dest.rmdir()
        except OSError:
            dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    else:
        dest.unlink()


def _link_directory(src: Path, dest: Path) -> str:
    try:
        os.symlink(str(src), str(dest), target_is_directory=True)
        return "symlink"
    except OSError:
        if os.name == "nt":
            proc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dest), str(src)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                return "junction"
        raise


def install_to_target(
    dest: Path,
    source_root: Path = REPO_ROOT,
    *,
    link: bool = False,
    dry_run: bool = False,
) -> dict[str, str]:
    """Install or link `kinearc` into `dest` without copying cache artifacts."""
    src_resolved = source_root.resolve()
    dest_norm = Path(os.path.abspath(str(dest)))

    if os.path.normcase(str(dest_norm)) == os.path.normcase(str(src_resolved)):
        return {"target": str(dest_norm), "action": "skipped-self"}

    if link:
        if dry_run:
            return {"target": str(dest_norm), "action": "dry-run-link"}
        dest_norm.parent.mkdir(parents=True, exist_ok=True)
        _remove_existing(dest_norm)
        mode = _link_directory(src_resolved, dest_norm)
        return {"target": str(dest_norm), "action": f"linked:{mode}"}

    if dry_run:
        return {"target": str(dest_norm), "action": "dry-run-copy"}

    _remove_existing(dest_norm)
    dest_norm.mkdir(parents=True, exist_ok=True)
    for item in INSTALL_ITEMS:
        src_item = src_resolved / item
        if not src_item.exists():
            continue
        dst_item = dest_norm / item
        if src_item.is_dir():
            shutil.copytree(src_item, dst_item, ignore=_ignore_filter)
        else:
            shutil.copy2(src_item, dst_item)

    return {"target": str(dest_norm), "action": "copied"}


def uninstall_target(dest: Path, source_root: Path = REPO_ROOT, *, dry_run: bool = False) -> dict[str, str]:
    """Remove an installed `kinearc` copy or link at `dest` cleanly."""
    src_resolved = source_root.resolve()
    dest_norm = Path(os.path.abspath(str(dest)))
    if os.path.normcase(str(dest_norm)) == os.path.normcase(str(src_resolved)):
        return {"target": str(dest_norm), "action": "skipped-self"}
    if not dest_norm.exists() and not _is_link_or_junction(dest_norm):
        return {"target": str(dest_norm), "action": "not-found"}
    if dry_run:
        return {"target": str(dest_norm), "action": "dry-run-remove"}
    _remove_existing(dest_norm)
    return {"target": str(dest_norm), "action": "removed"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install, link, or uninstall the kinearc skill across AI coding agents.")
    parser.add_argument(
        "--agent",
        default="all",
        help="Comma-separated targets: gemini,kiro,claude,agents,cursor,all,none (default: all)",
    )
    parser.add_argument(
        "--skill-dir",
        action="append",
        default=[],
        help="Custom agent skills folder (repeatable); installs into <skill-dir>/kinearc",
    )
    parser.add_argument("--home", default=None, help="Override home directory for global skill paths")
    parser.add_argument("--link", action="store_true", help="Symlink/junction targets back to this checkout")
    parser.add_argument("--uninstall", action="store_true", help="Remove installed kinearc copies/links")
    parser.add_argument("--dry-run", action="store_true", help="Print planned targets without touching disk")
    parser.add_argument("--skip-doctor", action="store_true", help="Do not run scripts/kinearc_cli.py doctor afterward")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home_dir = Path(args.home) if args.home else None
    try:
        targets = resolve_targets(args.agent, args.skill_dir, home_dir=home_dir)
    except ValueError as exc:
        print(f"[kinearc install] Error: {exc}", file=sys.stderr)
        return 1

    if not targets:
        print("[kinearc install] No target directories selected.")

    for target in targets:
        if args.uninstall:
            res = uninstall_target(target, dry_run=args.dry_run)
        else:
            res = install_to_target(target, link=args.link, dry_run=args.dry_run)
        print(f"[kinearc install] {res['action']}: {res['target']}")

    if not args.uninstall and not args.dry_run and not args.skip_doctor:
        cli_py = REPO_ROOT / "scripts" / "kinearc_cli.py"
        if cli_py.is_file():
            proc = subprocess.run([sys.executable, "-B", str(cli_py), "doctor"], check=False)
            return int(proc.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
