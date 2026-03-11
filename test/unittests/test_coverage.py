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
"""Unit tests for ovoscope.coverage."""

import os
import tempfile

import pytest

from ovoscope.coverage import (
    RepoCoverage,
    EcosystemCoverageReport,
    scan_workspace,
    _has_e2e_tests,
    _count_fixtures,
    _find_pyproject_tomls,
    _parse_entry_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(root: str, name: str, pyproject_content: str, has_e2e: bool = False) -> str:
    """Create a fake repo directory inside *root* and return its path."""
    repo = os.path.join(root, name)
    os.makedirs(repo)
    with open(os.path.join(repo, "pyproject.toml"), "w") as f:
        f.write(pyproject_content)
    if has_e2e:
        e2e = os.path.join(repo, "test", "end2end")
        os.makedirs(e2e)
        with open(os.path.join(e2e, "test_e2e.py"), "w") as f:
            f.write("# test")
    return repo


_SKILL_PYPROJECT = """
[project]
name = "my-skill"

[project.entry-points."opm.skill"]
"my-skill.test" = "my_skill:MySkill"
"""

_PIPELINE_PYPROJECT = """
[project]
name = "my-pipeline"

[project.entry-points."opm.pipeline"]
"my-pipeline.test" = "my_pipeline:MyPipeline"
"""

_NO_OVOS_PYPROJECT = """
[project]
name = "some-unrelated-package"

[project.scripts]
my-tool = "my_tool:main"
"""


# ---------------------------------------------------------------------------
# _has_e2e_tests
# ---------------------------------------------------------------------------


class TestHasE2eTests:
    def test_true_when_test_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            e2e = os.path.join(tmp, "test", "end2end")
            os.makedirs(e2e)
            with open(os.path.join(e2e, "test_skill.py"), "w") as f:
                f.write("# test")
            assert _has_e2e_tests(tmp) is True

    def test_false_when_no_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert _has_e2e_tests(tmp) is False

    def test_false_when_dir_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "test", "end2end"))
            assert _has_e2e_tests(tmp) is False

    def test_false_with_only_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            e2e = os.path.join(tmp, "test", "end2end")
            os.makedirs(e2e)
            with open(os.path.join(e2e, "__init__.py"), "w") as f:
                f.write("")
            assert _has_e2e_tests(tmp) is False


# ---------------------------------------------------------------------------
# _count_fixtures
# ---------------------------------------------------------------------------


class TestCountFixtures:
    def test_counts_json_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            e2e = os.path.join(tmp, "test", "end2end")
            os.makedirs(e2e)
            for name in ["a.json", "b.json", "c.py"]:
                open(os.path.join(e2e, name), "w").close()
            assert _count_fixtures(tmp) == 2

    def test_zero_when_no_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert _count_fixtures(tmp) == 0


# ---------------------------------------------------------------------------
# _find_pyproject_tomls
# ---------------------------------------------------------------------------


class TestFindPyprojectTomls:
    def test_finds_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo1 = os.path.join(tmp, "repo1")
            os.makedirs(repo1)
            open(os.path.join(repo1, "pyproject.toml"), "w").close()
            results = _find_pyproject_tomls(tmp)
            assert any("repo1" in r for r in results)

    def test_skips_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = os.path.join(tmp, ".venv", "lib")
            os.makedirs(venv)
            open(os.path.join(venv, "pyproject.toml"), "w").close()
            results = _find_pyproject_tomls(tmp)
            assert not any(".venv" in r for r in results)


# ---------------------------------------------------------------------------
# scan_workspace
# ---------------------------------------------------------------------------


class TestScanWorkspace:
    def test_finds_skill_repos(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, "my-skill", _SKILL_PYPROJECT, has_e2e=False)
            report = scan_workspace(tmp)
            assert len(report.repos) == 1
            assert report.repos[0].repo_type == "skill"
            assert report.repos[0].has_e2e_tests is False

    def test_skill_with_e2e(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, "my-skill", _SKILL_PYPROJECT, has_e2e=True)
            report = scan_workspace(tmp)
            assert report.repos[0].has_e2e_tests is True

    def test_ignores_non_ovos_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, "unrelated", _NO_OVOS_PYPROJECT)
            report = scan_workspace(tmp)
            assert len(report.repos) == 0

    def test_coverage_pct(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, "skill-a", _SKILL_PYPROJECT, has_e2e=True)
            _make_repo(tmp, "skill-b", _SKILL_PYPROJECT, has_e2e=False)
            report = scan_workspace(tmp)
            assert report.coverage_pct == 50.0

    def test_empty_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = scan_workspace(tmp)
            assert report.repos == []
            assert report.coverage_pct == 0.0

    def test_to_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, "my-skill", _SKILL_PYPROJECT)
            report = scan_workspace(tmp)
            j = report.to_json()
            assert "repos" in j
            assert "coverage_pct" in j

    def test_print_table_no_crash(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, "my-skill", _SKILL_PYPROJECT, has_e2e=True)
            report = scan_workspace(tmp)
            report.print_table()
            out = capsys.readouterr().out
            assert "my-skill" in out
