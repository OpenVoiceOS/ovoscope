"""Regression tests for ovoscope.pipeline._SinkSkill."""

import pytest

from ovos_utils.fakebus import FakeBus

from ovoscope.pipeline import _SinkSkill


class _RecordingBus:
    def __init__(self):
        self.handlers = []
        self.removed = []

    def on(self, event, handler):
        self.handlers.append((event, handler))

    def remove(self, event, handler):
        self.removed.append((event, handler))


class TestSinkSkillBusHandling:
    def test_default_constructs_with_fakebus(self):
        # Regression: previously _SinkSkill(bus=None) crashed and
        # PipelineHarness relied on passing None then rebinding. Now bus
        # defaults to a FakeBus so construction is always safe and the
        # skill is immediately usable.
        sink = _SinkSkill()
        assert isinstance(sink.bus, FakeBus)
        assert sink._last_match is None

    def test_explicit_none_falls_back_to_fakebus(self):
        sink = _SinkSkill(bus=None)
        assert isinstance(sink.bus, FakeBus)

    def test_constructs_with_supplied_bus(self):
        bus = _RecordingBus()
        sink = _SinkSkill(bus=bus)
        events = [e for e, _ in bus.handlers]
        assert "intent.service.skills.activated" in events
        assert "intent_failure" in events

    def test_rebinding_bus_detaches_previous(self):
        old = _RecordingBus()
        new = _RecordingBus()
        sink = _SinkSkill(bus=old)
        sink.bus = new
        old_removed = [e for e, _ in old.removed]
        assert "intent.service.skills.activated" in old_removed
        assert "intent_failure" in old_removed
        new_events = [e for e, _ in new.handlers]
        assert "intent.service.skills.activated" in new_events
        assert "intent_failure" in new_events

    def test_setting_bus_to_none_raises(self):
        sink = _SinkSkill()
        with pytest.raises(ValueError):
            sink.bus = None
