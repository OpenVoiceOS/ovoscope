"""Regression tests for ovoscope.pipeline._SinkSkill."""

import importlib.util
import threading
import time
import unittest

import pytest

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus

from ovoscope.pipeline import PipelineHarness, _SinkSkill

# PipelineHarness spins up a full MiniCroft pinned to the adapt pipeline.
ADAPT_AVAILABLE = importlib.util.find_spec("ovos_adapt") is not None

LEGACY_UTTERANCE = "recognizer_loop:utterance"
SPEC_UTTERANCE = str(SpecMessage.UTTERANCE)  # ovos.utterance.handle


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


# ---------------------------------------------------------------------------
# TestPipelineHarnessNamespaceBridging
# ---------------------------------------------------------------------------

@unittest.skipUnless(ADAPT_AVAILABLE, "ovos-adapt pipeline plugin not installed")
class TestPipelineHarnessNamespaceBridging(unittest.TestCase):
    """PipelineHarness injects utterances on the LEGACY topic
    (``recognizer_loop:utterance``). These tests pin that the harness FakeBus
    bridges that to/from the ovos.* SPEC topic (``ovos.utterance.handle``) so a
    pipeline test can drive EITHER namespace, and that disabling the bridge
    isolates a single namespace.
    """

    PIPELINE = ["ovos-adapt-pipeline-plugin-high"]

    def _emit_and_collect(self, harness, emit_topic, watch_topic, *, timeout=3.0):
        """Subscribe on ``watch_topic``, emit one utterance on ``emit_topic``,
        return the payloads observed on ``watch_topic``."""
        seen = []
        got = threading.Event()

        def _on(msg):
            if isinstance(msg, str):
                msg = Message.deserialize(msg)
            seen.append(msg)
            got.set()

        harness._mc.bus.on(watch_topic, _on)
        try:
            harness._mc.bus.emit(Message(
                emit_topic,
                data={"utterances": ["turn on the lights"], "lang": "en-US"},
            ))
            got.wait(timeout)
        finally:
            harness._mc.bus.remove(watch_topic, _on)
        return seen

    def test_legacy_utterance_observed_on_spec_topic(self):
        """Default harness (bridging on): an utterance injected on the legacy
        ``recognizer_loop:utterance`` topic is observed on the spec
        ``ovos.utterance.handle`` topic (modernize bridging)."""
        with PipelineHarness(pipeline=self.PIPELINE) as h:
            seen = self._emit_and_collect(h, LEGACY_UTTERANCE, SPEC_UTTERANCE)
            self.assertTrue(seen, "legacy utterance was not bridged to the spec topic")
            self.assertEqual(seen[0].data["utterances"], ["turn on the lights"])

    def test_spec_utterance_drives_pipeline_and_legacy_listener(self):
        """An utterance injected on the SPEC topic still drives the pipeline
        (a match is produced) and reaches a LEGACY listener (emit_legacy)."""
        with PipelineHarness(pipeline=self.PIPELINE) as h:
            legacy_seen = self._emit_and_collect(h, SPEC_UTTERANCE, LEGACY_UTTERANCE)
            self.assertTrue(legacy_seen,
                            "spec utterance was not bridged to the legacy topic")
            self.assertEqual(legacy_seen[0].data["utterances"], ["turn on the lights"])

    def test_no_bridging_isolates_legacy_from_spec(self):
        """With bridging OFF, a legacy utterance emit does NOT reach a
        spec-only subscriber — a single namespace is exercised in isolation."""
        with PipelineHarness(pipeline=self.PIPELINE,
                             modernize=False, emit_legacy=False) as h:
            seen = self._emit_and_collect(h, LEGACY_UTTERANCE, SPEC_UTTERANCE,
                                          timeout=0.5)
            self.assertEqual(seen, [],
                             "legacy emit must not reach the spec topic when bridging is off")
