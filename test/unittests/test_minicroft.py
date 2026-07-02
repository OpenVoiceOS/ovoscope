"""Unit tests for MiniCroft and get_minicroft()."""
import threading
import unittest

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovos_utils.log import LOG
from ovos_workshop.skills.ovos import OVOSSkill

from ovos_bus_client.session import SessionManager

from ovoscope import MiniCroft, get_minicroft, DEFAULT_TEST_PIPELINE, LIGHT_TEST_PIPELINE, ADAPT_PIPELINE

LEGACY_UTTERANCE = "recognizer_loop:utterance"
SPEC_UTTERANCE = str(SpecMessage.UTTERANCE)  # ovos.utterance.handle


# ---------------------------------------------------------------------------
# Minimal inline skill used across tests
# ---------------------------------------------------------------------------
SKILL_ID = "ovoscope-unittest-minicroft.test"


class PingSkill(OVOSSkill):
    """Emits 'unittest.pong' in response to 'unittest.ping'."""

    def initialize(self):
        self.add_event("unittest.ping", self.handle_ping)

    def handle_ping(self, message: Message):
        self.bus.emit(Message("unittest.pong",
                              data={"reply": "pong"},
                              context=message.context))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestGetMiniCroft(unittest.TestCase):

    def setUp(self):
        LOG.set_level("ERROR")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def test_empty_skills_reaches_ready(self):
        """get_minicroft([]) should start successfully with no skills."""
        mc = get_minicroft([])
        try:
            from ovos_utils.process_utils import ProcessState
            self.assertEqual(mc.status.state, ProcessState.READY)
        finally:
            mc.stop()

    def test_extra_skill_is_loaded(self):
        """An inline skill passed via extra_skills must appear in plugin_skills."""
        mc = get_minicroft([SKILL_ID], extra_skills={SKILL_ID: PingSkill})
        try:
            self.assertIn(SKILL_ID, mc.plugin_skills,
                          "extra skill should be registered in plugin_skills")
        finally:
            mc.stop()

    def test_max_wait_timeout_raises(self):
        """max_wait=0 should raise TimeoutError because MiniCroft can't be
        instantaneous — the underlying thread needs time to start."""
        with self.assertRaises(TimeoutError):
            get_minicroft([], max_wait=0)

    def test_skill_ids_string_normalised_to_list(self):
        """Passing a bare string is equivalent to passing a single-element list."""
        mc = get_minicroft(SKILL_ID, extra_skills={SKILL_ID: PingSkill})
        try:
            self.assertIn(SKILL_ID, mc.plugin_skills)
        finally:
            mc.stop()

    def test_returns_minicroft_instance(self):
        mc = get_minicroft([])
        try:
            self.assertIsInstance(mc, MiniCroft)
        finally:
            mc.stop()


class TestMiniCroftPipelineIsolation(unittest.TestCase):
    """Tests for MiniCroft default_pipeline override."""

    def setUp(self):
        LOG.set_level("ERROR")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def test_default_pipeline_overrides_default_session(self):
        """default_pipeline is applied to SessionManager.default_session."""
        mc = get_minicroft([], default_pipeline=ADAPT_PIPELINE)
        try:
            self.assertEqual(SessionManager.default_session.pipeline, ADAPT_PIPELINE)
        finally:
            mc.stop()

    def test_default_pipeline_restored_after_stop(self):
        """After stop(), default_session.pipeline is restored to its previous value."""
        original = SessionManager.default_session.pipeline[:]
        mc = get_minicroft([], default_pipeline=ADAPT_PIPELINE)
        mc.stop()
        self.assertEqual(SessionManager.default_session.pipeline, original)

    def test_isolate_config_uses_default_test_pipeline(self):
        """isolate_config=True with no explicit default_pipeline uses DEFAULT_TEST_PIPELINE or fallback."""
        mc = get_minicroft([])
        try:
            # If all plugins are installed, it uses DEFAULT_TEST_PIPELINE.
            # Otherwise it falls back to LIGHT_TEST_PIPELINE.
            # Both are valid outcomes of the "isolation + default" logic.
            self.assertIn(mc.pipeline, [DEFAULT_TEST_PIPELINE, LIGHT_TEST_PIPELINE])
            self.assertEqual(SessionManager.default_session.pipeline, mc.pipeline)
        finally:
            mc.stop()

    def test_persona_stages_absent_from_default_test_pipeline(self):
        """DEFAULT_TEST_PIPELINE must not contain any persona or LLM pipeline stage."""
        for stage in DEFAULT_TEST_PIPELINE:
            self.assertNotIn("persona", stage, f"persona stage found: {stage}")
            self.assertNotIn("ollama", stage, f"ollama stage found: {stage}")
            self.assertNotIn("m2v", stage, f"m2v stage found: {stage}")

    def test_no_pipeline_override_when_none(self):
        """default_pipeline=None must not alter the existing default session pipeline."""
        before = SessionManager.default_session.pipeline[:]
        mc = get_minicroft([], isolate_config=False, default_pipeline=None)
        try:
            self.assertEqual(SessionManager.default_session.pipeline, before)
        finally:
            mc.stop()


class TestMiniCroftInjectMessage(unittest.TestCase):
    """Tests for MiniCroft.inject_message()."""

    def setUp(self):
        LOG.set_level("ERROR")
        self.skill_id = SKILL_ID
        self.mc = get_minicroft([self.skill_id],
                                extra_skills={self.skill_id: PingSkill})

    def tearDown(self):
        self.mc.stop()
        LOG.set_level("CRITICAL")

    def test_inject_message_delivers_to_skill(self):
        """inject_message() should cause the skill handler to fire."""
        received = threading.Event()
        pong_msgs = []

        # Named message handlers on FakeBus receive Message objects directly;
        # only the generic "message" wildcard receives raw serialised strings.
        def on_pong(msg: Message):
            pong_msgs.append(msg)
            received.set()

        self.mc.bus.on("unittest.pong", on_pong)
        try:
            self.mc.inject_message(Message("unittest.ping",
                                           context={"source": "A", "destination": "B"}))
            received.wait(timeout=5)
            self.assertTrue(received.is_set(), "pong not received within 5s")
            self.assertEqual(len(pong_msgs), 1)
            self.assertEqual(pong_msgs[0].data["reply"], "pong")
        finally:
            self.mc.bus.remove("unittest.pong", on_pong)

    def test_inject_message_does_not_go_through_utterance_pipeline(self):
        """inject_message() bypasses the intent pipeline — no utterance.handled."""
        handled = threading.Event()

        def on_handled(msg: Message):
            handled.set()

        self.mc.bus.on("ovos.utterance.handled", on_handled)
        try:
            self.mc.inject_message(
                Message("some.arbitrary.event", context={"source": "A"}))
            # give it a moment
            handled.wait(timeout=1)
            self.assertFalse(handled.is_set(),
                             "inject_message should NOT trigger utterance pipeline")
        finally:
            self.mc.bus.remove("ovos.utterance.handled", on_handled)

    def test_inject_message_with_data(self):
        """Data and context passed to inject_message are forwarded intact."""
        received = threading.Event()
        captured = []

        def on_ping(raw: str):
            captured.append(Message.deserialize(raw))
            received.set()

        self.mc.bus.on("message", on_ping)
        try:
            self.mc.inject_message(
                Message("test.data.check",
                        data={"key": "value"},
                        context={"ctx": "test"}))
            received.wait(timeout=2)
            # find our message
            match = [m for m in captured
                     if m.msg_type == "test.data.check"]
            self.assertTrue(match, "injected message not found on bus")
            self.assertEqual(match[0].data["key"], "value")
            self.assertEqual(match[0].context["ctx"], "test")
        finally:
            self.mc.bus.remove("message", on_ping)


class TestMiniCroftPipelineConfig(unittest.TestCase):
    """Tests for MiniCroft pipeline_config parameter."""

    def setUp(self):
        LOG.set_level("ERROR")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def test_pipeline_config_patches_intents_config(self):
        """pipeline_config must be visible under Configuration()['intents'] while running."""
        from ovos_config.config import Configuration

        captured_config = {}

        # We can only inspect the live config after MiniCroft starts.
        mc = get_minicroft(
            [],
            pipeline_config={"test_plugin": {"key": "patched_value"}},
        )
        try:
            cfg = Configuration()
            captured_config = cfg.get("intents", {}).get("test_plugin", {})
        finally:
            mc.stop()

        self.assertEqual(captured_config.get("key"), "patched_value",
                         "pipeline_config entry should appear in Configuration()['intents']")

    def test_pipeline_config_restored_after_stop(self):
        """After stop(), Configuration()['intents']['test_plugin'] is removed."""
        from ovos_config.config import Configuration

        mc = get_minicroft(
            [],
            pipeline_config={"test_plugin_restore": {"key": "value"}},
        )
        mc.stop()

        cfg = Configuration()
        remaining = cfg.get("intents", {}).get("test_plugin_restore")
        self.assertIsNone(remaining,
                          "pipeline_config entry should be removed after stop()")

    def test_pipeline_config_preserves_existing_key(self):
        """If the plugin key already existed, it is restored (not deleted) after stop()."""
        from ovos_config.config import Configuration

        # Pre-seed the intents config with an existing entry
        cfg = Configuration()
        intents_cfg = cfg.setdefault("intents", {})
        intents_cfg["pre_existing_plugin"] = {"key": "original"}

        try:
            mc = get_minicroft(
                [],
                pipeline_config={"pre_existing_plugin": {"key": "overridden"}},
            )
            # Confirm override is active
            live_val = Configuration().get("intents", {}).get("pre_existing_plugin", {})
            self.assertEqual(live_val.get("key"), "overridden")
            mc.stop()
            # Confirm original value is restored
            restored_val = Configuration().get("intents", {}).get("pre_existing_plugin", {})
            self.assertEqual(restored_val.get("key"), "original",
                             "original pipeline config should be restored after stop()")
        finally:
            # Clean up the pre-seeded key so it doesn't leak into other tests
            cfg.get("intents", {}).pop("pre_existing_plugin", None)

    def test_pipeline_config_none_does_not_patch(self):
        """pipeline_config=None must not modify Configuration()['intents']."""
        from ovos_config.config import Configuration

        before = dict(Configuration().get("intents", {}))
        mc = get_minicroft([], pipeline_config=None)
        try:
            after = dict(Configuration().get("intents", {}))
            # The intents dict may differ (pipeline key is patched by default_pipeline
            # logic), but no new arbitrary keys should appear from pipeline_config=None
            # Verify no unexpected keys were introduced compared to before
            new_keys = set(after.keys()) - set(before.keys())
            pipeline_keys = {"pipeline", "blacklisted_intents"}
            unexpected = new_keys - pipeline_keys
            self.assertEqual(unexpected, set(),
                             f"pipeline_config=None introduced unexpected keys: {unexpected}")
        finally:
            mc.stop()

    def test_pipeline_config_multiple_keys(self):
        """Multiple pipeline_config entries are all patched and all restored."""
        from ovos_config.config import Configuration

        mc = get_minicroft(
            [],
            pipeline_config={
                "plugin_a": {"model": "a"},
                "plugin_b": {"threshold": 0.5},
            },
        )
        try:
            cfg = Configuration().get("intents", {})
            self.assertEqual(cfg.get("plugin_a", {}).get("model"), "a")
            self.assertEqual(cfg.get("plugin_b", {}).get("threshold"), 0.5)
        finally:
            mc.stop()

        cfg_after = Configuration().get("intents", {})
        self.assertIsNone(cfg_after.get("plugin_a"))
        self.assertIsNone(cfg_after.get("plugin_b"))


class TestMiniCroftNamespaceBridging(unittest.TestCase):
    """MiniCroft is the e2e harness bus. Utterances are injected on the LEGACY
    topic (``recognizer_loop:utterance``); these tests pin that MiniCroft's
    FakeBus bridges that to/from the ovos.* SPEC topic
    (``ovos.utterance.handle``) so an e2e test can drive EITHER namespace, and
    that disabling the bridge isolates a single namespace.
    """

    def setUp(self):
        LOG.set_level("ERROR")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _emit_and_collect(self, mc, emit_topic, watch_topic, *, timeout=3.0):
        seen = []
        got = threading.Event()

        def _on(msg):
            if isinstance(msg, str):
                msg = Message.deserialize(msg)
            seen.append(msg)
            got.set()

        mc.bus.on(watch_topic, _on)
        try:
            mc.bus.emit(Message(
                emit_topic,
                data={"utterances": ["hello world"], "lang": "en-US"},
            ))
            got.wait(timeout)
        finally:
            mc.bus.remove(watch_topic, _on)
        return seen

    def test_legacy_utterance_observed_on_spec_topic(self):
        """Default (bridging on): a legacy recognizer_loop:utterance injected
        into the e2e harness is observed on ovos.utterance.handle (modernize)."""
        mc = get_minicroft([])  # modernize/emit_legacy default on
        try:
            seen = self._emit_and_collect(mc, LEGACY_UTTERANCE, SPEC_UTTERANCE)
            self.assertTrue(seen, "legacy utterance was not bridged to the spec topic")
            self.assertEqual(seen[0].data["utterances"], ["hello world"])
        finally:
            mc.stop()

    def test_spec_utterance_reaches_legacy_listener(self):
        """An utterance injected on the SPEC topic reaches a LEGACY listener
        (emit_legacy) — the intent pipeline keys off the legacy topic."""
        mc = get_minicroft([])
        try:
            seen = self._emit_and_collect(mc, SPEC_UTTERANCE, LEGACY_UTTERANCE)
            self.assertTrue(seen, "spec utterance was not bridged to the legacy topic")
            self.assertEqual(seen[0].data["utterances"], ["hello world"])
        finally:
            mc.stop()

    def test_no_bridging_isolates_legacy_from_spec(self):
        """With bridging OFF, a legacy emit does NOT reach a spec-only
        subscriber — the e2e harness exercises a single isolated namespace."""
        mc = get_minicroft([], modernize=False, emit_legacy=False)
        try:
            seen = self._emit_and_collect(mc, LEGACY_UTTERANCE, SPEC_UTTERANCE,
                                          timeout=0.5)
            self.assertEqual(seen, [],
                             "legacy emit must not reach the spec topic when bridging is off")
        finally:
            mc.stop()


if __name__ == "__main__":
    unittest.main()
