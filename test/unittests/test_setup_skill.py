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
"""Unit tests for ovoscope.setup_skill (ovoscope-setup entrypoint)."""
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ovoscope.setup_skill import (
    _skill_data_dir,
    install_claude,
    install_gemini,
    install_opencode,
    uninstall_claude,
    uninstall_gemini,
    uninstall_opencode,
    detect_tools,
    main,
)


class TestSkillDataDir(unittest.TestCase):
    """skill_data directory must exist and contain required files."""

    def test_skill_data_dir_exists(self) -> None:
        d = _skill_data_dir()
        self.assertTrue(d.is_dir(), f"skill_data dir not found: {d}")

    def test_claude_skill_md_exists(self) -> None:
        self.assertTrue((_skill_data_dir() / "claude" / "SKILL.md").is_file())

    def test_claude_wrapper_script_exists(self) -> None:
        self.assertTrue((_skill_data_dir() / "claude" / "scripts" / "ovoscope.sh").is_file())

    def test_gemini_skill_md_exists(self) -> None:
        self.assertTrue((_skill_data_dir() / "gemini" / "SKILL.md").is_file())

    def test_opencode_agent_md_exists(self) -> None:
        self.assertTrue((_skill_data_dir() / "opencode" / "ovoscope.md").is_file())

    def test_assets_docs_populated(self) -> None:
        docs = _skill_data_dir() / "claude" / "assets" / "docs"
        self.assertTrue(docs.is_dir())
        self.assertGreater(len(list(docs.glob("*.md"))), 0)


class TestInstallClaude(unittest.TestCase):
    """install_claude copies files to the target directory."""

    def test_installs_to_custom_home(self) -> None:
        with TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            skill_dir = fake_home / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                result = install_claude(verbose=False)
            self.assertTrue(result)
            self.assertTrue((skill_dir / "SKILL.md").is_file())
            self.assertTrue((skill_dir / "scripts" / "ovoscope.sh").is_file())
            self.assertTrue((skill_dir / "assets" / "FAQ.md").is_file())
            self.assertTrue((skill_dir / "assets" / "docs").is_dir())

    def test_script_is_executable(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                install_claude(verbose=False)
            script = skill_dir / "scripts" / "ovoscope.sh"
            self.assertTrue(os.access(script, os.X_OK))

    def test_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                install_claude(verbose=False)
                install_claude(verbose=False)  # second call must not raise
            self.assertTrue((skill_dir / "SKILL.md").is_file())


class TestUninstallClaude(unittest.TestCase):
    """uninstall_claude removes the skill directory."""

    def test_uninstall_existing(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                install_claude(verbose=False)
                result = uninstall_claude(verbose=False)
            self.assertTrue(result)
            self.assertFalse(skill_dir.exists())

    def test_uninstall_not_installed(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                result = uninstall_claude(verbose=False)
            self.assertFalse(result)


class TestInstallGemini(unittest.TestCase):
    """install_gemini copies files into <project>/.gemini/skills/ovoscope/."""

    def test_installs_to_project_path(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            result = install_gemini(project_path=project, verbose=False)
            self.assertTrue(result)
            skill_dir = project / ".gemini" / "skills" / "ovoscope"
            self.assertTrue((skill_dir / "SKILL.md").is_file())
            self.assertTrue((skill_dir / "assets" / "docs").is_dir())

    def test_uninstall_gemini(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            install_gemini(project_path=project, verbose=False)
            result = uninstall_gemini(project_path=project, verbose=False)
            self.assertTrue(result)
            self.assertFalse((project / ".gemini" / "skills" / "ovoscope").exists())


class TestInstallOpencode(unittest.TestCase):
    """install_opencode writes the agent .md file."""

    def test_installs_agent_file(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            result = install_opencode(project_path=project, verbose=False)
            self.assertTrue(result)
            agent = project / ".opencode" / "agents" / "ovoscope.md"
            self.assertTrue(agent.is_file())

    def test_agent_file_has_frontmatter(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            install_opencode(project_path=project, verbose=False)
            content = (project / ".opencode" / "agents" / "ovoscope.md").read_text()
            self.assertTrue(content.startswith("---"))
            self.assertIn("name:", content)
            self.assertIn("description:", content)

    def test_uninstall_opencode(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            install_opencode(project_path=project, verbose=False)
            result = uninstall_opencode(project_path=project, verbose=False)
            self.assertTrue(result)
            self.assertFalse((project / ".opencode" / "agents" / "ovoscope.md").exists())


class TestDetectTools(unittest.TestCase):
    """detect_tools returns tools whose binaries are on PATH."""

    def test_returns_list(self) -> None:
        tools = detect_tools()
        self.assertIsInstance(tools, list)
        for t in tools:
            self.assertIn(t, {"claude", "gemini", "opencode"})

    def test_no_tools_when_nothing_on_path(self) -> None:
        with patch("shutil.which", return_value=None):
            self.assertEqual(detect_tools(), [])

    def test_detects_claude_on_path(self) -> None:
        def fake_which(name: str) -> str | None:
            return "/usr/bin/claude" if name == "claude" else None
        with patch("shutil.which", side_effect=fake_which):
            self.assertIn("claude", detect_tools())


class TestMainCLI(unittest.TestCase):
    """main() argument parsing and dispatch."""

    def test_list_only(self) -> None:
        rc = main(["--list"])
        self.assertEqual(rc, 0)

    def test_explicit_claude(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                rc = main(["--claude"])
            self.assertEqual(rc, 0)
            self.assertTrue((skill_dir / "SKILL.md").is_file())

    def test_explicit_gemini_with_path(self) -> None:
        with TemporaryDirectory() as tmp:
            rc = main(["--gemini", "--path", tmp])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(tmp) / ".gemini" / "skills" / "ovoscope" / "SKILL.md").is_file())

    def test_explicit_opencode_with_path(self) -> None:
        with TemporaryDirectory() as tmp:
            rc = main(["--opencode", "--path", tmp])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(tmp) / ".opencode" / "agents" / "ovoscope.md").is_file())

    def test_uninstall_claude(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                main(["--claude"])
                rc = main(["--uninstall", "--claude"])
            self.assertEqual(rc, 0)
            self.assertFalse(skill_dir.exists())

    def test_autodetect_no_tools_returns_1(self) -> None:
        with patch("shutil.which", return_value=None):
            rc = main([])
        self.assertEqual(rc, 1)

    def test_autodetect_installs_detected_tools(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"

            def fake_which(name: str) -> str | None:
                return f"/usr/bin/{name}" if name == "claude" else None

            with patch("shutil.which", side_effect=fake_which), \
                 patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                rc = main([])
            self.assertEqual(rc, 0)
            self.assertTrue((skill_dir / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
