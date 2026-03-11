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
"""Unit tests for ovoscope.diff."""

import json
import os
import tempfile
from typing import Any, Dict, List

import pytest

from ovoscope.diff import (
    MessageDiff,
    FixtureDiffResult,
    diff_fixtures,
    _dict_diff,
    _load_messages,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_fixture(msgs: List[Dict[str, Any]]) -> str:
    """Write a minimal fixture JSON to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump({"source_message": {"type": "recognizer_loop:utterance", "data": {}, "context": {}},
               "expected_messages": msgs}, tmp)
    tmp.flush()
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# _dict_diff
# ---------------------------------------------------------------------------


class TestDictDiff:
    def test_no_diff(self):
        assert _dict_diff({"a": 1}, {"a": 1}) == {}

    def test_missing_key_in_actual(self):
        diffs = _dict_diff({"a": 1}, {})
        assert "a" in diffs
        assert diffs["a"] == (1, None)

    def test_value_mismatch(self):
        diffs = _dict_diff({"a": 1}, {"a": 2})
        assert diffs["a"] == (1, 2)

    def test_extra_key_in_actual_ignored(self):
        # Only keys in expected are checked
        diffs = _dict_diff({"a": 1}, {"a": 1, "b": 99})
        assert diffs == {}


# ---------------------------------------------------------------------------
# _load_messages
# ---------------------------------------------------------------------------


class TestLoadMessages:
    def test_loads_expected_messages(self):
        path = _write_fixture([{"type": "speak", "data": {"utterance": "hi"}, "context": {}}])
        msgs = _load_messages(path)
        assert len(msgs) == 1
        assert msgs[0]["type"] == "speak"
        os.unlink(path)

    def test_empty_list(self):
        path = _write_fixture([])
        msgs = _load_messages(path)
        assert msgs == []
        os.unlink(path)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            _load_messages("/nonexistent/fixture.json")


# ---------------------------------------------------------------------------
# diff_fixtures
# ---------------------------------------------------------------------------


class TestDiffFixtures:
    def test_identical_fixtures(self):
        msgs = [{"type": "speak", "data": {"utterance": "hello"}, "context": {}}]
        p1 = _write_fixture(msgs)
        p2 = _write_fixture(msgs)
        result = diff_fixtures(p1, p2)
        assert result.is_identical
        assert all(d.status == "match" for d in result.diffs)
        os.unlink(p1)
        os.unlink(p2)

    def test_type_mismatch(self):
        p1 = _write_fixture([{"type": "speak", "data": {}, "context": {}}])
        p2 = _write_fixture([{"type": "mycroft.stop", "data": {}, "context": {}}])
        result = diff_fixtures(p1, p2)
        assert not result.is_identical
        assert result.diffs[0].status == "type_mismatch"
        os.unlink(p1)
        os.unlink(p2)

    def test_data_mismatch(self):
        p1 = _write_fixture([{"type": "speak", "data": {"utterance": "hello"}, "context": {}}])
        p2 = _write_fixture([{"type": "speak", "data": {"utterance": "goodbye"}, "context": {}}])
        result = diff_fixtures(p1, p2)
        assert not result.is_identical
        assert result.diffs[0].status == "data_mismatch"
        assert "utterance" in result.diffs[0].data_diffs
        os.unlink(p1)
        os.unlink(p2)

    def test_missing_message(self):
        p1 = _write_fixture([
            {"type": "speak", "data": {}, "context": {}},
            {"type": "mycroft.mic.listen", "data": {}, "context": {}},
        ])
        p2 = _write_fixture([{"type": "speak", "data": {}, "context": {}}])
        result = diff_fixtures(p1, p2)
        assert not result.is_identical
        statuses = [d.status for d in result.diffs]
        assert "missing" in statuses
        os.unlink(p1)
        os.unlink(p2)

    def test_extra_message(self):
        p1 = _write_fixture([{"type": "speak", "data": {}, "context": {}}])
        p2 = _write_fixture([
            {"type": "speak", "data": {}, "context": {}},
            {"type": "extra_msg", "data": {}, "context": {}},
        ])
        result = diff_fixtures(p1, p2)
        assert not result.is_identical
        statuses = [d.status for d in result.diffs]
        assert "extra" in statuses
        os.unlink(p1)
        os.unlink(p2)

    def test_to_json(self):
        msgs = [{"type": "speak", "data": {}, "context": {}}]
        p1 = _write_fixture(msgs)
        p2 = _write_fixture(msgs)
        result = diff_fixtures(p1, p2)
        j = result.to_json()
        assert "is_identical" in j
        assert "diffs" in j
        assert isinstance(j["diffs"], list)
        os.unlink(p1)
        os.unlink(p2)

    def test_print_report_no_crash(self, capsys):
        msgs = [{"type": "speak", "data": {"utterance": "hi"}, "context": {}}]
        p1 = _write_fixture(msgs)
        p2 = _write_fixture([{"type": "speak", "data": {"utterance": "bye"}, "context": {}}])
        result = diff_fixtures(p1, p2)
        result.print_report(color=False)
        out = capsys.readouterr().out
        assert "DATA" in out
        os.unlink(p1)
        os.unlink(p2)
