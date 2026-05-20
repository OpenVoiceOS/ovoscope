"""Regression tests for ovoscope.pipeline._SinkSkill."""

import pytest

from ovoscope.pipeline import _SinkSkill


class _FakeBus:
    def __init__(self):
        self.handlers = []
        self.removed = []

    def on(self, event, handler):
        self.handlers.append((event, handler))

    def remove(self, event, handler):
        self.removed.append((event, handler))


class TestSinkSkillBusHandling:
    def test_constructs_with_bus_none(self):
        # Regression: _SinkSkill(bus=None) used to crash because __init__
        # called bus.on(...) before checking for None. PipelineHarness relies
        # on this two-step construction (create skill, then attach bus after
        # MiniCroft is built).
        sink = _SinkSkill(bus=None)
        assert sink.bus is None
        assert sink._last_match is None

    def test_attaches_when_bus_set_via_setter(self):
        sink = _SinkSkill(bus=None)
        bus = _FakeBus()
        sink.bus = bus
        # Both subscriptions registered
        events = [e for e, _ in bus.handlers]
        assert "intent.service.skills.activated" in events
        assert "intent_failure" in events

    def test_constructs_with_live_bus(self):
        bus = _FakeBus()
        sink = _SinkSkill(bus=bus)
        events = [e for e, _ in bus.handlers]
        assert "intent.service.skills.activated" in events
        assert "intent_failure" in events

    def test_rebinding_bus_detaches_previous(self):
        old = _FakeBus()
        new = _FakeBus()
        sink = _SinkSkill(bus=old)
        sink.bus = new
        # Old bus had its handlers removed
        old_removed_events = [e for e, _ in old.removed]
        assert "intent.service.skills.activated" in old_removed_events
        assert "intent_failure" in old_removed_events
        # New bus has fresh handlers
        new_events = [e for e, _ in new.handlers]
        assert "intent.service.skills.activated" in new_events
        assert "intent_failure" in new_events
