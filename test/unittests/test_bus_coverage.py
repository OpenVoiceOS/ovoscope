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
"""Unit tests for ovoscope.bus_coverage."""

import json
from unittest.mock import MagicMock, patch

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovoscope.bus_coverage import (
    BusCoverageReport,
    BusCoverageTracker,
    EmitterEntry,
    HandlerEntry,
    SkillBusCoverage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(msg_type: str, skill_id: str = None) -> Message:
    """Create a minimal Message with optional skill_id in context."""
    context = {}
    if skill_id:
        context["skill_id"] = skill_id
    return Message(msg_type, {}, context)


def _make_tracker_with_handlers():
    """Build a BusCoverageTracker whose bus has two fake skill handlers."""
    bus = FakeBus()

    skill_a = MagicMock()
    skill_b = MagicMock()
    skill_a.__class__.__name__ = "SkillA"
    skill_b.__class__.__name__ = "SkillB"

    # Register bound-like handlers using lambdas bound to skill instances
    handler_a1 = MagicMock()
    handler_a1.__self__ = skill_a
    handler_a2 = MagicMock()
    handler_a2.__self__ = skill_a
    handler_b1 = MagicMock()
    handler_b1.__self__ = skill_b

    bus.on("speak", handler_a1)
    bus.on("intent.service.skills.activate", handler_a2)
    bus.on("speak", handler_b1)

    minicroft = MagicMock()
    minicroft.plugin_skills = {
        "skill-a.author": skill_a,
        "skill-b.author": skill_b,
    }

    tracker = BusCoverageTracker(bus, minicroft)
    return tracker, bus, skill_a, skill_b


# ---------------------------------------------------------------------------
# HandlerEntry
# ---------------------------------------------------------------------------


class TestHandlerEntry:
    def test_covered_true_when_invoked(self):
        h = HandlerEntry(msg_type="speak", handler_count=1, invocation_count=3, covered=True)
        assert h.covered is True

    def test_covered_false_when_not_invoked(self):
        h = HandlerEntry(msg_type="speak", handler_count=1, invocation_count=0, covered=False)
        assert h.covered is False

    def test_to_dict_keys(self):
        h = HandlerEntry(msg_type="speak", handler_count=2, invocation_count=5, covered=True)
        d = h.to_dict()
        assert set(d.keys()) == {"msg_type", "handler_count", "invocation_count", "covered"}
        assert d["msg_type"] == "speak"
        assert d["handler_count"] == 2
        assert d["invocation_count"] == 5
        assert d["covered"] is True


# ---------------------------------------------------------------------------
# EmitterEntry
# ---------------------------------------------------------------------------


class TestEmitterEntry:
    def test_observed_true_when_count_positive(self):
        e = EmitterEntry(msg_type="speak", observed_count=1, asserted_count=0, observed=True, asserted=False)
        assert e.observed is True
        assert e.asserted is False

    def test_to_dict_keys(self):
        e = EmitterEntry(msg_type="speak", observed_count=2, asserted_count=1, observed=True, asserted=True)
        d = e.to_dict()
        assert set(d.keys()) == {"msg_type", "observed_count", "asserted_count", "observed", "asserted"}


# ---------------------------------------------------------------------------
# SkillBusCoverage properties
# ---------------------------------------------------------------------------


class TestSkillBusCoverage:
    def _make_skill(self) -> SkillBusCoverage:
        skill = SkillBusCoverage(skill_id="test.skill")
        skill.listeners = [
            HandlerEntry("speak", 1, 3, True),
            HandlerEntry("intent.activate", 1, 0, False),
            HandlerEntry("intent.deactivate", 1, 1, True),
        ]
        skill.emitters = [
            EmitterEntry("speak", 3, 2, True, True),
            EmitterEntry("gui.page.show", 1, 0, True, False),
            EmitterEntry("ovos.utterance.handled", 1, 0, True, False),
        ]
        return skill

    def test_listener_coverage_pct(self):
        skill = self._make_skill()
        # 2 out of 3 listeners covered
        assert abs(skill.listener_coverage_pct - 66.7) < 0.5

    def test_observed_emitter_pct(self):
        skill = self._make_skill()
        # all 3 emitters observed
        assert skill.observed_emitter_pct == pytest.approx(100.0)

    def test_asserted_emitter_pct(self):
        skill = self._make_skill()
        # only 1 of 3 asserted
        assert abs(skill.asserted_emitter_pct - 33.3) < 0.5

    def test_empty_listeners_pct(self):
        skill = SkillBusCoverage(skill_id="empty.skill")
        assert skill.listener_coverage_pct == 0.0
        assert skill.observed_emitter_pct == 0.0
        assert skill.asserted_emitter_pct == 0.0

    def test_to_dict_structure(self):
        skill = self._make_skill()
        d = skill.to_dict()
        assert "skill_id" in d
        assert "listener_coverage_pct" in d
        assert "observed_emitter_pct" in d
        assert "asserted_emitter_pct" in d
        assert isinstance(d["listeners"], list)
        assert isinstance(d["emitters"], list)


# ---------------------------------------------------------------------------
# BusCoverageReport
# ---------------------------------------------------------------------------


class TestBusCoverageReport:
    def _make_report(self) -> BusCoverageReport:
        skill = SkillBusCoverage(skill_id="my.skill")
        skill.listeners = [
            HandlerEntry("speak", 1, 2, True),
            HandlerEntry("intent.activate", 1, 0, False),
        ]
        skill.emitters = [
            EmitterEntry("speak", 2, 1, True, True),
        ]
        return BusCoverageReport(skills=[skill])

    def test_summary_line_format(self):
        report = self._make_report()
        line = report.summary_line()
        assert "my.skill" in line
        assert "listeners:" in line
        assert "observed:" in line
        assert "asserted:" in line

    def test_to_json_is_valid(self):
        report = self._make_report()
        raw = report.to_json()
        data = json.loads(raw)
        assert "skills" in data
        assert "totals" in data
        assert isinstance(data["skills"], list)

    def test_totals_dict_counts(self):
        report = self._make_report()
        totals = report._totals_dict()
        assert totals["listener_total"] == 2
        assert totals["listener_covered"] == 1
        assert totals["emitter_total"] == 1
        assert totals["observed_count"] == 1
        assert totals["asserted_count"] == 1

    def test_print_report_no_error(self, capsys):
        report = self._make_report()
        report.print_report()
        captured = capsys.readouterr()
        assert "Bus Coverage Report" in captured.out
        assert "my.skill" in captured.out

    def test_print_report_verbose(self, capsys):
        report = self._make_report()
        report.print_report(verbose=True)
        captured = capsys.readouterr()
        assert "LISTENERS" in captured.out
        assert "EMITTERS" in captured.out


# ---------------------------------------------------------------------------
# BusCoverageTracker
# ---------------------------------------------------------------------------


class _FakeSkill:
    """Minimal stand-in for a skill instance with a bound handler."""

    def __init__(self):
        pass

    def on_speak(self, message):
        pass


class TestBusCoverageTrackerSnapshotListeners:
    def test_snapshot_registers_handlers_by_skill(self):
        """snapshot_listeners should map bound handlers to their skill_id."""
        bus = FakeBus()
        skill_a = _FakeSkill()

        # bound method — __self__ is skill_a
        bus.on("speak", skill_a.on_speak)

        minicroft = MagicMock()
        minicroft.plugin_skills = {"skill-a.author": skill_a}

        tracker = BusCoverageTracker(bus, minicroft)
        tracker.snapshot_listeners()

        assert "skill-a.author" in tracker._registered
        assert "speak" in tracker._registered["skill-a.author"]

    def test_snapshot_ignores_unattributed_handlers(self):
        """Handlers without __self__ or not in plugin_skills should be ignored."""
        bus = FakeBus()
        bus.on("speak", lambda m: None)  # lambda has no __self__

        minicroft = MagicMock()
        minicroft.plugin_skills = {}

        tracker = BusCoverageTracker(bus, minicroft)
        tracker.snapshot_listeners()

        assert tracker._registered == {}


class TestBusCoverageTrackerEmitPatch:
    def test_start_tracking_counts_emits(self):
        """start_tracking should increment _invocations per emit call."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}

        tracker = BusCoverageTracker(bus, minicroft)
        tracker.start_tracking()

        bus.emit(Message("speak", {}, {}))
        bus.emit(Message("speak", {}, {}))
        bus.emit(Message("intent.activate", {}, {}))

        assert tracker._invocations.get("speak") == 2
        assert tracker._invocations.get("intent.activate") == 1

    def test_stop_tracking_restores_emit(self):
        """stop_tracking should restore the original emit callable."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}

        tracker = BusCoverageTracker(bus, minicroft)
        tracker.start_tracking()
        patched_emit = bus.emit

        tracker.stop_tracking()
        # After stop_tracking the tracker should no longer be active
        assert not tracker._tracking
        assert tracker._original_emit is None
        # The patched emit should be gone
        assert bus.emit is not patched_emit

    def test_double_start_is_idempotent(self):
        """Calling start_tracking twice should not double-wrap."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}

        tracker = BusCoverageTracker(bus, minicroft)
        tracker.start_tracking()
        patched = bus.emit
        tracker.start_tracking()
        assert bus.emit is patched  # still the same patched function


class TestBusCoverageTrackerRecordSession:
    def test_record_session_accumulates_observed(self):
        """Responses with skill_id in context should be recorded as observed."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}
        tracker = BusCoverageTracker(bus, minicroft)

        responses = [
            _make_message("speak", "my.skill"),
            _make_message("speak", "my.skill"),
            _make_message("gui.page.show", "my.skill"),
        ]
        tracker.record_session(responses, [])

        assert tracker._observed["my.skill"]["speak"] == 2
        assert tracker._observed["my.skill"]["gui.page.show"] == 1

    def test_record_session_accumulates_asserted(self):
        """expected_messages with skill_id should be recorded as asserted."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}
        tracker = BusCoverageTracker(bus, minicroft)

        expected = [_make_message("speak", "my.skill")]
        tracker.record_session([], expected)

        assert tracker._asserted["my.skill"]["speak"] == 1

    def test_record_session_fallback_attribution(self):
        """expected_messages without skill_id should fall back to observed skill."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}
        tracker = BusCoverageTracker(bus, minicroft)

        # observed has the type under skill-a
        responses = [_make_message("speak", "skill-a.author")]
        # expected has no skill_id
        expected = [Message("speak", {}, {})]

        tracker.record_session(responses, expected)

        assert "skill-a.author" in tracker._asserted
        assert tracker._asserted["skill-a.author"]["speak"] == 1


class TestBusCoverageTrackerBuildReport:
    def test_build_report_populates_skills(self):
        """build_report should return SkillBusCoverage entries for each skill."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}

        tracker = BusCoverageTracker(bus, minicroft)
        tracker._registered = {"my.skill": {"speak": 1}}
        tracker._invocations = {"speak": 3}
        tracker._observed = {"my.skill": {"speak": 3}}
        tracker._asserted = {"my.skill": {"speak": 2}}

        report = tracker.build_report()

        assert len(report.skills) == 1
        skill = report.skills[0]
        assert skill.skill_id == "my.skill"
        assert len(skill.listeners) == 1
        assert skill.listeners[0].covered is True
        assert skill.listeners[0].invocation_count == 3
        assert len(skill.emitters) == 1
        assert skill.emitters[0].observed is True
        assert skill.emitters[0].asserted is True

    def test_build_report_uncovered_listener(self):
        """Listeners whose msg_type was never emitted should have covered=False."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}

        tracker = BusCoverageTracker(bus, minicroft)
        tracker._registered = {"my.skill": {"never.emitted": 1}}
        tracker._invocations = {}

        report = tracker.build_report()
        assert report.skills[0].listeners[0].covered is False

    def test_build_report_empty(self):
        """build_report on a fresh tracker should return an empty report."""
        bus = FakeBus()
        minicroft = MagicMock()
        minicroft.plugin_skills = {}
        tracker = BusCoverageTracker(bus, minicroft)
        report = tracker.build_report()
        assert report.skills == []


class TestBusCoverageTrackerGetBusEvents:
    def test_returns_ee_events(self):
        """_get_bus_events should read bus.ee._events for pyee EventEmitter."""
        bus = FakeBus()
        bus.on("test.event", lambda m: None)
        minicroft = MagicMock()
        minicroft.plugin_skills = {}
        tracker = BusCoverageTracker(bus, minicroft)
        events = tracker._get_bus_events()
        assert "test.event" in events

    def test_returns_empty_for_unknown_bus(self):
        """_get_bus_events should return {} if no known event attributes exist."""
        bus = MagicMock()
        del bus.ee
        del bus._events
        minicroft = MagicMock()
        minicroft.plugin_skills = {}
        tracker = BusCoverageTracker(bus, minicroft)
        # Should not raise
        events = tracker._get_bus_events()
        assert isinstance(events, dict)


class TestBusCoverageTrackerIterHandlers:
    def test_iter_handlers_ordered_dict(self):
        """_iter_handlers should yield keys from an OrderedDict (pyee v9 format)."""
        import collections

        def my_handler():
            pass

        od = collections.OrderedDict({my_handler: my_handler})
        result = list(BusCoverageTracker._iter_handlers(od))
        assert result == [my_handler]

    def test_iter_handlers_list(self):
        """_iter_handlers should yield each item from a list (no .fn attr)."""
        def my_handler():
            pass

        result = list(BusCoverageTracker._iter_handlers([my_handler]))
        assert result == [my_handler]

    def test_iter_handlers_single_callable(self):
        """_iter_handlers should yield a single callable directly."""
        def my_handler():
            pass

        result = list(BusCoverageTracker._iter_handlers(my_handler))
        assert result == [my_handler]

    def test_iter_handlers_pyee_wrapper_in_list(self):
        """_iter_handlers should unwrap .fn from pyee listener wrappers in a list."""
        def fn():
            pass

        class _Wrapper:
            def __init__(self, fn):
                self.fn = fn

        wrapper = _Wrapper(fn)
        result = list(BusCoverageTracker._iter_handlers([wrapper]))
        assert result == [fn]
