# Copyright 2024 Jarbas AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""ovoscope-setup — install the ovoscope skill into AI coding assistants.

Supports Claude Code and Gemini CLI.  Running without flags auto-detects
which tools are installed and installs for all of them.

The ``SKILL.md`` and wrapper script are bundled with the package.
Documentation is downloaded from the ovoscope GitHub repository so the
installed assets always reflect the latest docs without bloating the wheel.

Usage::

    ovoscope-setup                     # auto-detect and install all
    ovoscope-setup --claude            # Claude Code only
    ovoscope-setup --gemini            # Gemini CLI only (project-level)
    ovoscope-setup --gemini --path /my/workspace
    ovoscope-setup --list              # show detected tools without installing
    ovoscope-setup --uninstall --claude
    ovoscope-setup --no-docs           # skip doc download (offline / CI use)
"""
from __future__ import annotations

import argparse
import shutil
import stat
import sys
import urllib.error
import urllib.request
from importlib import resources
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# GitHub source for docs
# ---------------------------------------------------------------------------

#: Raw-content base URL for ovoscope docs on the master branch.
GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/TigreGotico/ovoscope/master"
)

#: Files to download into ``assets/docs/``.
_DOCS_FILES = [
    "docs/audio-testing.md",
    "docs/capture-session.md",
    "docs/ci-integration.md",
    "docs/cli.md",
    "docs/end2end-test.md",
    "docs/gui-testing.md",
    "docs/index.md",
    "docs/listener.md",
    "docs/minicroft.md",
    "docs/ocp.md",
    "docs/phal.md",
    "docs/pipeline.md",
    "docs/pydantic-integration.md",
    "docs/usage-guide.md",
]

#: Extra root-level files to download into ``assets/``.
_ASSET_FILES = [
    "FAQ.md",
    "QUICK_FACTS.md",
]


# ---------------------------------------------------------------------------
# Skill data helpers
# ---------------------------------------------------------------------------

def _skill_data_dir() -> Path:
    """Return the path to the bundled ``skill_data`` package directory."""
    with resources.path("ovoscope.skill_data", "__init__.py") as p:
        return p.parent


def _copy_tree(src: Path, dst: Path) -> List[Path]:
    """Recursively copy *src* into *dst*.

    Args:
        src: Source directory.
        dst: Destination directory (created if absent).

    Returns:
        List of destination paths written.
    """
    written: List[Path] = []
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            dest = dst / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            written.append(dest)
    return written


def _make_executable(path: Path) -> None:
    """Add execute bits (owner + group + other) to *path*."""
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# Documentation download
# ---------------------------------------------------------------------------

def download_docs(assets_dir: Path, verbose: bool = True) -> int:
    """Download ovoscope docs from GitHub into *assets_dir*.

    Downloads each file listed in :data:`_DOCS_FILES` into
    ``assets_dir/docs/`` and each file in :data:`_ASSET_FILES` into
    ``assets_dir/``.  Files that cannot be fetched (network error, 404)
    are skipped with a warning rather than aborting the whole install.

    Args:
        assets_dir: Destination ``assets/`` directory.
        verbose: Print progress messages.

    Returns:
        Number of files successfully downloaded.
    """
    downloaded = 0

    # docs/ subdirectory
    docs_dst = assets_dir / "docs"
    docs_dst.mkdir(parents=True, exist_ok=True)
    for rel_path in _DOCS_FILES:
        url = f"{GITHUB_RAW_BASE}/{rel_path}"
        dest = docs_dst / Path(rel_path).name
        if _fetch(url, dest, verbose=verbose):
            downloaded += 1

    # root-level assets (FAQ.md, QUICK_FACTS.md)
    assets_dir.mkdir(parents=True, exist_ok=True)
    for rel_path in _ASSET_FILES:
        url = f"{GITHUB_RAW_BASE}/{rel_path}"
        dest = assets_dir / rel_path
        if _fetch(url, dest, verbose=verbose):
            downloaded += 1

    return downloaded


def _fetch(url: str, dest: Path, verbose: bool = True) -> bool:
    """Download *url* to *dest*.

    Args:
        url: Full URL to fetch.
        dest: Destination file path.
        verbose: Print per-file status.

    Returns:
        True on success, False on any error.
    """
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            dest.write_bytes(resp.read())
        if verbose:
            print(f"  ↓ {dest.name}")
        return True
    except (urllib.error.URLError, OSError) as exc:
        print(f"  ! skipped {dest.name}: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------

def _claude_skill_dir() -> Path:
    """Return ``~/.claude/skills/ovoscope``."""
    return Path.home() / ".claude" / "skills" / "ovoscope"


def _claude_is_installed() -> bool:
    """Return True if the ``claude`` binary is on PATH."""
    return shutil.which("claude") is not None


def install_claude(fetch_docs: bool = True, verbose: bool = True) -> bool:
    """Install the ovoscope skill for Claude Code.

    Copies the bundled ``SKILL.md`` and wrapper script into
    ``~/.claude/skills/ovoscope/``, then optionally downloads
    documentation from GitHub into ``assets/``.

    Args:
        fetch_docs: Download docs from GitHub (default True).
        verbose: Print progress messages.

    Returns:
        True on success.
    """
    src = _skill_data_dir() / "claude"
    dst = _claude_skill_dir()
    dst.mkdir(parents=True, exist_ok=True)

    written = _copy_tree(src, dst)

    for script in (dst / "scripts").glob("*.sh"):
        _make_executable(script)

    if verbose:
        print(f"[claude]  installed {len(written)} bundled files → {dst}")

    if fetch_docs:
        if verbose:
            print("[claude]  downloading docs from GitHub …")
        n = download_docs(dst / "assets", verbose=verbose)
        if verbose:
            print(f"[claude]  {n} doc files downloaded")

    return True


def uninstall_claude(verbose: bool = True) -> bool:
    """Remove the ovoscope skill from Claude Code.

    Args:
        verbose: Print progress messages.

    Returns:
        True if removed, False if not found.
    """
    dst = _claude_skill_dir()
    if dst.exists():
        shutil.rmtree(dst)
        if verbose:
            print(f"[claude]  removed {dst}")
        return True
    if verbose:
        print(f"[claude]  not installed ({dst} not found)")
    return False


# ---------------------------------------------------------------------------
# Gemini CLI
# ---------------------------------------------------------------------------

def _gemini_skill_dir(project_path: Optional[Path] = None) -> Path:
    """Return ``<project>/.gemini/skills/ovoscope``.

    Args:
        project_path: Project root. Defaults to ``Path.cwd()``.
    """
    return (project_path or Path.cwd()) / ".gemini" / "skills" / "ovoscope"


def _gemini_is_installed() -> bool:
    """Return True if the ``gemini`` binary is on PATH."""
    return shutil.which("gemini") is not None


def install_gemini(
    project_path: Optional[Path] = None,
    fetch_docs: bool = True,
    verbose: bool = True,
) -> bool:
    """Install the ovoscope skill for Gemini CLI.

    Copies the bundled ``SKILL.md`` and wrapper script into
    ``<project>/.gemini/skills/ovoscope/``, then optionally downloads
    documentation from GitHub into ``assets/``.

    Gemini skills are project-level.  Run from your workspace root or
    pass *project_path* explicitly.

    Args:
        project_path: Project root. Defaults to ``Path.cwd()``.
        fetch_docs: Download docs from GitHub (default True).
        verbose: Print progress messages.

    Returns:
        True on success.
    """
    src = _skill_data_dir() / "gemini"
    dst = _gemini_skill_dir(project_path)
    dst.mkdir(parents=True, exist_ok=True)

    written = _copy_tree(src, dst)

    for script in (dst / "scripts").glob("*.sh"):
        _make_executable(script)

    if verbose:
        print(f"[gemini]  installed {len(written)} bundled files → {dst}")

    if fetch_docs:
        if verbose:
            print("[gemini]  downloading docs from GitHub …")
        n = download_docs(dst / "assets", verbose=verbose)
        if verbose:
            print(f"[gemini]  {n} doc files downloaded")

    return True


def uninstall_gemini(
    project_path: Optional[Path] = None,
    verbose: bool = True,
) -> bool:
    """Remove the ovoscope skill from Gemini CLI.

    Args:
        project_path: Project root. Defaults to ``Path.cwd()``.
        verbose: Print progress messages.

    Returns:
        True if removed, False if not found.
    """
    dst = _gemini_skill_dir(project_path)
    if dst.exists():
        shutil.rmtree(dst)
        if verbose:
            print(f"[gemini]  removed {dst}")
        return True
    if verbose:
        print(f"[gemini]  not installed ({dst} not found)")
    return False


# ---------------------------------------------------------------------------
# Auto-detect
# ---------------------------------------------------------------------------

def detect_tools() -> List[str]:
    """Return names of AI tools whose binaries are on PATH.

    Returns:
        Subset of ``["claude", "gemini"]``.
    """
    found = []
    if _claude_is_installed():
        found.append("claude")
    if _gemini_is_installed():
        found.append("gemini")
    return found


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the ``ovoscope-setup`` command.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 = success, 1 = nothing installed.
    """
    parser = argparse.ArgumentParser(
        prog="ovoscope-setup",
        description=(
            "Install the ovoscope skill into AI coding assistants.\n\n"
            "Run without flags to auto-detect and install for all tools found\n"
            "on PATH.  Gemini installs are project-level (written to the\n"
            "current directory or the path given by --path).\n\n"
            "Documentation is fetched from GitHub at install time so the\n"
            "bundled wheel stays small.  Pass --no-docs to skip the download."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--claude",
        action="store_true",
        help="Install for Claude Code (~/.claude/skills/ovoscope/).",
    )
    parser.add_argument(
        "--gemini",
        action="store_true",
        help="Install for Gemini CLI (<path>/.gemini/skills/ovoscope/).",
    )
    parser.add_argument(
        "--path",
        metavar="DIR",
        default=None,
        help="Project root for Gemini install (default: current directory).",
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        dest="no_docs",
        help="Skip downloading documentation from GitHub.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the skill instead of installing it.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="Show which tools are detected without installing anything.",
    )

    args = parser.parse_args(argv)
    project_path = Path(args.path).resolve() if args.path else None
    fetch_docs = not args.no_docs

    if args.list_only:
        found = detect_tools()
        if found:
            print("Detected AI tools on PATH: " + ", ".join(found))
        else:
            print("No supported AI tools detected on PATH (claude, gemini).")
        return 0

    explicit = args.claude or args.gemini
    if not explicit:
        found = detect_tools()
        if not found:
            print(
                "No supported AI tools detected on PATH.\n"
                "Install claude or gemini first, or use --claude/--gemini explicitly."
            )
            return 1
        args.claude = "claude" in found
        args.gemini = "gemini" in found
        print(f"Auto-detected: {', '.join(found)}")

    if args.uninstall:
        if args.claude:
            uninstall_claude()
        if args.gemini:
            uninstall_gemini(project_path)
        return 0

    installed = 0
    if args.claude:
        install_claude(fetch_docs=fetch_docs)
        installed += 1
    if args.gemini:
        install_gemini(project_path, fetch_docs=fetch_docs)
        installed += 1

    if installed:
        print(
            "\nInstallation complete. Restart your AI assistant or open a new\n"
            "session for the ovoscope skill to be available."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
