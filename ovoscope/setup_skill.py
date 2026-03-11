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

Supports Claude Code, Gemini CLI, and OpenCode. Running without flags
auto-detects which tools are installed and installs for all of them.

Usage::

    ovoscope-setup                     # auto-detect and install all
    ovoscope-setup --claude            # Claude Code only
    ovoscope-setup --gemini            # Gemini CLI only (project-level)
    ovoscope-setup --opencode          # OpenCode only (project-level)
    ovoscope-setup --gemini --path /my/workspace
    ovoscope-setup --list              # show detected tools without installing
    ovoscope-setup --uninstall --claude

Each tool installs skill/agent definition files so the AI assistant can
discover the ovoscope CLI commands and documentation automatically.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from importlib import resources
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Skill data helpers
# ---------------------------------------------------------------------------

def _skill_data_dir() -> Path:
    """Return the path to the bundled skill_data package directory."""
    with resources.path("ovoscope.skill_data", "__init__.py") as p:
        return p.parent


def _copy_tree(src: Path, dst: Path) -> List[Path]:
    """Copy *src* directory tree into *dst*, creating dirs as needed.

    Returns list of destination paths written.
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
    """Add execute bits to *path* (owner + group + other)."""
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------

def _claude_skill_dir() -> Path:
    """Return ``~/.claude/skills/ovoscope``."""
    return Path.home() / ".claude" / "skills" / "ovoscope"


def _claude_is_installed() -> bool:
    """Return True if ``claude`` binary is on PATH."""
    return shutil.which("claude") is not None


def install_claude(verbose: bool = True) -> bool:
    """Install the ovoscope skill for Claude Code.

    Copies ``skill_data/claude/`` into ``~/.claude/skills/ovoscope/``.

    Args:
        verbose: Print progress messages.

    Returns:
        True on success.
    """
    src = _skill_data_dir() / "claude"
    dst = _claude_skill_dir()
    dst.mkdir(parents=True, exist_ok=True)

    written = _copy_tree(src, dst)

    # Ensure wrapper scripts are executable
    scripts_dir = dst / "scripts"
    if scripts_dir.is_dir():
        for script in scripts_dir.glob("*.sh"):
            _make_executable(script)

    if verbose:
        print(f"[claude]  installed {len(written)} files → {dst}")
    return True


def uninstall_claude(verbose: bool = True) -> bool:
    """Remove the ovoscope skill from Claude Code.

    Args:
        verbose: Print progress messages.

    Returns:
        True if the directory was removed, False if it did not exist.
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
        project_path: Project root. Defaults to the current working directory.
    """
    root = project_path or Path.cwd()
    return root / ".gemini" / "skills" / "ovoscope"


def _gemini_is_installed() -> bool:
    """Return True if ``gemini`` binary is on PATH."""
    return shutil.which("gemini") is not None


def install_gemini(project_path: Optional[Path] = None, verbose: bool = True) -> bool:
    """Install the ovoscope skill for Gemini CLI.

    Copies ``skill_data/gemini/`` into ``<project>/.gemini/skills/ovoscope/``.
    Gemini skills are project-level; run this from your workspace root.

    Args:
        project_path: Project root to install into. Defaults to ``Path.cwd()``.
        verbose: Print progress messages.

    Returns:
        True on success.
    """
    src = _skill_data_dir() / "gemini"
    dst = _gemini_skill_dir(project_path)
    dst.mkdir(parents=True, exist_ok=True)

    written = _copy_tree(src, dst)

    scripts_dir = dst / "scripts"
    if scripts_dir.is_dir():
        for script in scripts_dir.glob("*.sh"):
            _make_executable(script)

    if verbose:
        print(f"[gemini]  installed {len(written)} files → {dst}")
    return True


def uninstall_gemini(project_path: Optional[Path] = None, verbose: bool = True) -> bool:
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
# OpenCode
# ---------------------------------------------------------------------------

def _opencode_agent_dir(project_path: Optional[Path] = None) -> Path:
    """Return ``<project>/.opencode/agents/``."""
    root = project_path or Path.cwd()
    return root / ".opencode" / "agents"


def _opencode_is_installed() -> bool:
    """Return True if ``opencode`` binary is on PATH."""
    return shutil.which("opencode") is not None


def install_opencode(project_path: Optional[Path] = None, verbose: bool = True) -> bool:
    """Install the ovoscope agent for OpenCode.

    Copies ``skill_data/opencode/ovoscope.md`` into
    ``<project>/.opencode/agents/ovoscope.md``.

    Args:
        project_path: Project root. Defaults to ``Path.cwd()``.
        verbose: Print progress messages.

    Returns:
        True on success.
    """
    src = _skill_data_dir() / "opencode" / "ovoscope.md"
    dst_dir = _opencode_agent_dir(project_path)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "ovoscope.md"
    shutil.copy2(src, dst)
    if verbose:
        print(f"[opencode] installed agent → {dst}")
    return True


def uninstall_opencode(project_path: Optional[Path] = None, verbose: bool = True) -> bool:
    """Remove the ovoscope agent from OpenCode.

    Args:
        project_path: Project root. Defaults to ``Path.cwd()``.
        verbose: Print progress messages.

    Returns:
        True if removed, False if not found.
    """
    dst = _opencode_agent_dir(project_path) / "ovoscope.md"
    if dst.exists():
        dst.unlink()
        if verbose:
            print(f"[opencode] removed {dst}")
        return True
    if verbose:
        print(f"[opencode] not installed ({dst} not found)")
    return False


# ---------------------------------------------------------------------------
# Auto-detect
# ---------------------------------------------------------------------------

def detect_tools() -> List[str]:
    """Return list of AI tool names that appear to be installed.

    Checks whether ``claude``, ``gemini``, and ``opencode`` are on PATH.

    Returns:
        List of strings from ``{"claude", "gemini", "opencode"}``.
    """
    found = []
    if _claude_is_installed():
        found.append("claude")
    if _gemini_is_installed():
        found.append("gemini")
    if _opencode_is_installed():
        found.append("opencode")
    return found


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the ``ovoscope-setup`` command.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (0 = success, 1 = nothing installed).
    """
    parser = argparse.ArgumentParser(
        prog="ovoscope-setup",
        description=(
            "Install the ovoscope skill/agent into AI coding assistants.\n\n"
            "Run without flags to auto-detect and install for all tools found on PATH.\n"
            "Gemini and OpenCode installs are project-level (written to the current\n"
            "directory or the path given by --path)."
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
        "--opencode",
        action="store_true",
        help="Install for OpenCode (<path>/.opencode/agents/ovoscope.md).",
    )
    parser.add_argument(
        "--path",
        metavar="DIR",
        default=None,
        help=(
            "Project root for Gemini and OpenCode installs (default: current directory)."
        ),
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the skill/agent instead of installing it.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="Show which tools are detected without installing anything.",
    )

    args = parser.parse_args(argv)
    project_path = Path(args.path).resolve() if args.path else None

    # --list mode
    if args.list_only:
        found = detect_tools()
        if found:
            print("Detected AI tools on PATH: " + ", ".join(found))
        else:
            print("No supported AI tools detected on PATH (claude, gemini, opencode).")
        return 0

    # Determine which tools to act on
    explicit = args.claude or args.gemini or args.opencode
    if not explicit:
        # Auto-detect
        found = detect_tools()
        if not found:
            print(
                "No supported AI tools detected on PATH.\n"
                "Install claude, gemini, or opencode first, or use --claude/--gemini/--opencode explicitly."
            )
            return 1
        args.claude = "claude" in found
        args.gemini = "gemini" in found
        args.opencode = "opencode" in found
        print(f"Auto-detected: {', '.join(found)}")

    installed = 0

    if args.uninstall:
        if args.claude:
            uninstall_claude()
        if args.gemini:
            uninstall_gemini(project_path)
        if args.opencode:
            uninstall_opencode(project_path)
    else:
        if args.claude:
            install_claude()
            installed += 1
        if args.gemini:
            install_gemini(project_path)
            installed += 1
        if args.opencode:
            install_opencode(project_path)
            installed += 1

        if installed:
            print(
                "\nInstallation complete. Restart your AI assistant or open a new session\n"
                "for the ovoscope skill to be available."
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
