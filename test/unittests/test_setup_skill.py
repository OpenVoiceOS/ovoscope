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
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ovoscope.setup_skill import (
    _ASSET_FILES,
    _DOCS_FILES,
    _fetch,
    detect_tools,
    download_docs,
    install_claude,
    install_gemini,
    main,
    uninstall_claude,
    uninstall_gemini,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal urllib response stub."""

    def __init__(self, content: bytes = b"# doc") -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_) -> None:
        pass


# ---------------------------------------------------------------------------
# TestFetch
# ---------------------------------------------------------------------------

class TestFetch(unittest.TestCase):
    """_fetch downloads a URL to a local file."""

    def test_success(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "test.md"
            with patch("urllib.request.urlopen", return_value=_FakeResponse(b"# hello")):
                result = _fetch("https://example.com/test.md", dest, verbose=False)
            self.assertTrue(result)
            self.assertEqual(dest.read_bytes(), b"# hello")

    def test_network_error_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "test.md"
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("unreachable"),
            ):
                result = _fetch("https://example.com/test.md", dest, verbose=False)
            self.assertFalse(result)
            self.assertFalse(dest.exists())


# ---------------------------------------------------------------------------
# TestDownloadDocs
# ---------------------------------------------------------------------------

class TestDownloadDocs(unittest.TestCase):
    """download_docs fetches all expected files into assets/."""

    def test_downloads_all_files(self) -> None:
        with TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            with patch(
                "urllib.request.urlopen",
                return_value=_FakeResponse(b"# doc"),
            ):
                n = download_docs(assets, verbose=False)
            self.assertEqual(n, len(_DOCS_FILES) + len(_ASSET_FILES))
            self.assertTrue((assets / "docs").is_dir())
            self.assertTrue((assets / "FAQ.md").is_file())
            self.assertTrue((assets / "QUICK_FACTS.md").is_file())

    def test_partial_failure_continues(self) -> None:
        """A single 404 should not abort the rest of the downloads."""
        call_count = 0

        def flaky_urlopen(url: str, timeout: int = 15) -> _FakeResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise urllib.error.URLError("timeout")
            return _FakeResponse(b"# doc")

        with TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            with patch("urllib.request.urlopen", side_effect=flaky_urlopen):
                n = download_docs(assets, verbose=False)
            total = len(_DOCS_FILES) + len(_ASSET_FILES)
            self.assertEqual(n, total - 1)


# ---------------------------------------------------------------------------
# TestInstallClaude
# ---------------------------------------------------------------------------

class TestInstallClaude(unittest.TestCase):
    """install_claude downloads SKILL.md, writes wrapper, optionally fetches docs."""

    def test_installs_skill_md_and_wrapper(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                install_claude(fetch_docs=True, verbose=False)
            self.assertTrue((skill_dir / "SKILL.md").is_file() or
                            (skill_dir / "scripts" / "ovoscope.sh").is_file())
            self.assertTrue((skill_dir / "scripts" / "ovoscope.sh").is_file())

    def test_script_is_executable(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                install_claude(fetch_docs=False, verbose=False)
            self.assertTrue(os.access(skill_dir / "scripts" / "ovoscope.sh", os.X_OK))

    def test_calls_download_docs_when_fetch_docs_true(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=5) as mock_dl:
                install_claude(fetch_docs=True, verbose=False)
            mock_dl.assert_called_once()

    def test_skips_download_when_fetch_docs_false(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs") as mock_dl:
                install_claude(fetch_docs=False, verbose=False)
            mock_dl.assert_not_called()

    def test_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                install_claude(fetch_docs=False, verbose=False)
                install_claude(fetch_docs=False, verbose=False)
            self.assertTrue((skill_dir / "scripts" / "ovoscope.sh").is_file())

    def test_skill_md_fetched_from_github(self) -> None:
        """SKILL.md must be fetched from GitHub, not copied from a local bundle."""
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            fetched_urls = []

            def capturing_fetch(url: str, dest: Path, verbose: bool = True) -> bool:
                fetched_urls.append(url)
                dest.write_bytes(b"# SKILL.md content")
                return True

            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", side_effect=capturing_fetch), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                install_claude(fetch_docs=False, verbose=False)

            self.assertTrue(
                any("raw.githubusercontent.com" in u for u in fetched_urls),
                f"Expected GitHub URL in fetched URLs, got: {fetched_urls}",
            )


# ---------------------------------------------------------------------------
# TestUninstallClaude
# ---------------------------------------------------------------------------

class TestUninstallClaude(unittest.TestCase):

    def test_uninstall_existing(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                install_claude(fetch_docs=False, verbose=False)
                result = uninstall_claude(verbose=False)
            self.assertTrue(result)
            self.assertFalse(skill_dir.exists())

    def test_uninstall_not_installed_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir):
                result = uninstall_claude(verbose=False)
            self.assertFalse(result)


# ---------------------------------------------------------------------------
# TestInstallGemini
# ---------------------------------------------------------------------------

class TestInstallGemini(unittest.TestCase):

    def test_installs_to_project_path(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            with patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                install_gemini(project_path=project, fetch_docs=True, verbose=False)
            skill_dir = project / ".gemini" / "skills" / "ovoscope"
            self.assertTrue((skill_dir / "scripts" / "ovoscope.sh").is_file())

    def test_calls_download_docs(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=5) as mock_dl:
                install_gemini(project_path=Path(tmp), fetch_docs=True, verbose=False)
            mock_dl.assert_called_once()

    def test_uninstall_gemini(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            with patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                install_gemini(project_path=project, fetch_docs=False, verbose=False)
            result = uninstall_gemini(project_path=project, verbose=False)
            self.assertTrue(result)
            self.assertFalse((project / ".gemini" / "skills" / "ovoscope").exists())


# ---------------------------------------------------------------------------
# TestDetectTools
# ---------------------------------------------------------------------------

class TestDetectTools(unittest.TestCase):

    def test_returns_list(self) -> None:
        tools = detect_tools()
        self.assertIsInstance(tools, list)
        for t in tools:
            self.assertIn(t, {"claude", "gemini"})

    def test_no_tools_when_nothing_on_path(self) -> None:
        with patch("shutil.which", return_value=None):
            self.assertEqual(detect_tools(), [])

    def test_detects_claude(self) -> None:
        with patch("shutil.which", side_effect=lambda n: "/usr/bin/claude" if n == "claude" else None):
            self.assertIn("claude", detect_tools())

    def test_does_not_detect_opencode(self) -> None:
        """opencode is not supported — should never appear in results."""
        with patch("shutil.which", return_value="/usr/bin/opencode"):
            tools = detect_tools()
            self.assertNotIn("opencode", tools)


# ---------------------------------------------------------------------------
# TestMainCLI
# ---------------------------------------------------------------------------

class TestMainCLI(unittest.TestCase):

    def test_list_only(self) -> None:
        self.assertEqual(main(["--list"]), 0)

    def test_explicit_claude_no_docs(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                rc = main(["--claude", "--no-docs"])
            self.assertEqual(rc, 0)
            self.assertTrue((skill_dir / "scripts" / "ovoscope.sh").is_file())

    def test_explicit_gemini_with_path(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                rc = main(["--gemini", "--path", tmp, "--no-docs"])
            self.assertEqual(rc, 0)
            self.assertTrue(
                (Path(tmp) / ".gemini" / "skills" / "ovoscope" / "scripts" / "ovoscope.sh").is_file()
            )

    def test_uninstall_claude(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                main(["--claude", "--no-docs"])
                rc = main(["--uninstall", "--claude"])
            self.assertEqual(rc, 0)
            self.assertFalse(skill_dir.exists())

    def test_no_docs_flag_skips_download(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs") as mock_dl:
                main(["--claude", "--no-docs"])
            mock_dl.assert_not_called()

    def test_autodetect_no_tools_returns_1(self) -> None:
        with patch("shutil.which", return_value=None):
            self.assertEqual(main([]), 1)

    def test_autodetect_installs_detected(self) -> None:
        with TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".claude" / "skills" / "ovoscope"
            with patch("shutil.which", side_effect=lambda n: "/usr/bin/claude" if n == "claude" else None), \
                 patch("ovoscope.setup_skill._claude_skill_dir", return_value=skill_dir), \
                 patch("ovoscope.setup_skill._fetch", return_value=True), \
                 patch("ovoscope.setup_skill.download_docs", return_value=0):
                rc = main(["--no-docs"])
            self.assertEqual(rc, 0)
            self.assertTrue((skill_dir / "scripts" / "ovoscope.sh").is_file())


if __name__ == "__main__":
    unittest.main()
