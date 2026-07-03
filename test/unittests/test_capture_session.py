"""Unit tests for CaptureSession."""
import threading
import unittest

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import CaptureSession, get_minicroft


class TestCaptureSession(unittest.TestCase):
    """CaptureSession is tested by emitting directly on MiniCroft's FakeBus."""

    def setUp(self):
        LOG.set_level("ERROR")
        # empty MiniCroft — we drive the bus manually
        self.mc = get_minicroft([])

    def tearDown(self):
        self.mc.stop()
        LOG.set_level("CRITICAL")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _emit_after(self, delay_s: float, msg: Message):
        """Emit msg after delay_s seconds (from a background thread)."""
        def _run():
            import time
            time.sleep(delay_s)
            self.mc.bus.emit(msg)
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------
    def test_capture_receives_messages(self):
        """Messages emitted after capture() starts are stored in .responses.

        The EOF message itself IS included in responses — the generic "message"
        handler appends it before the specific EOF handler sets done.  This is
        consistent with how End2EndTest includes ovos.utterance.handled in its
        expected_messages list.
        """
        cs = CaptureSession(self.mc,
                            eof_msgs=["test.eof"],
                            ignore_messages=[])
        self._emit_after(0.05, Message("test.msg.A", data={"n": 1}))
        self._emit_after(0.10, Message("test.eof"))

        cs.capture(Message("test.trigger"), timeout=3)
        msgs = cs.finish()

        types = [m.msg_type for m in msgs]
        self.assertIn("test.trigger", types)
        self.assertIn("test.msg.A", types)
        # EOF is the final message in responses (captured before done is set)
        self.assertEqual(msgs[-1].msg_type, "test.eof")

    def test_capture_ignores_listed_messages(self):
        """Messages in ignore_messages must not appear in .responses."""
        cs = CaptureSession(self.mc,
                            eof_msgs=["test.eof"],
                            ignore_messages=["test.noise"])
        self._emit_after(0.05, Message("test.noise"))
        self._emit_after(0.10, Message("test.signal"))
        self._emit_after(0.15, Message("test.eof"))

        cs.capture(Message("test.trigger"), timeout=3)
        msgs = cs.finish()

        types = [m.msg_type for m in msgs]
        self.assertNotIn("test.noise", types)
        self.assertIn("test.signal", types)

    def test_capture_eof_stops_collection(self):
        """Messages emitted after the EOF must not be captured."""
        cs = CaptureSession(self.mc,
                            eof_msgs=["test.eof"],
                            ignore_messages=[])
        self._emit_after(0.05, Message("test.before"))
        self._emit_after(0.10, Message("test.eof"))
        # Give eof handler time to set done before test.after is emitted
        self._emit_after(0.25, Message("test.after"))   # must NOT appear

        cs.capture(Message("test.trigger"), timeout=3)
        msgs = cs.finish()

        types = [m.msg_type for m in msgs]
        self.assertIn("test.before", types)
        # The EOF itself is the last captured message; test.after should not appear
        self.assertNotIn("test.after", types,
                         "message after EOF must not be captured")

    def test_capture_async_messages_separated(self):
        """Messages listed in async_messages go to async_responses, not responses."""
        cs = CaptureSession(self.mc,
                            eof_msgs=["test.eof"],
                            ignore_messages=[],
                            async_messages=["test.async"])
        self._emit_after(0.05, Message("test.sync"))
        self._emit_after(0.08, Message("test.async"))
        self._emit_after(0.12, Message("test.eof"))

        cs.capture(Message("test.trigger"), timeout=3)
        msgs = cs.finish()

        sync_types = [m.msg_type for m in msgs]
        async_types = [m.msg_type for m in cs.async_responses]

        self.assertIn("test.sync", sync_types)
        self.assertNotIn("test.async", sync_types,
                         "async message must not be in main responses")
        self.assertIn("test.async", async_types,
                       "async message must be in async_responses")

    def test_finish_returns_responses_list(self):
        """finish() must return the same list as .responses."""
        cs = CaptureSession(self.mc, eof_msgs=["test.eof"], ignore_messages=[])
        self._emit_after(0.05, Message("test.x"))
        self._emit_after(0.10, Message("test.eof"))

        cs.capture(Message("test.trigger"), timeout=3)
        returned = cs.finish()

        self.assertIsInstance(returned, list)
        self.assertTrue(len(returned) >= 1,
                        "at least the trigger message must be in the list")

    def test_finish_stops_future_capture(self):
        """After finish(), further bus messages must not append to responses."""
        cs = CaptureSession(self.mc, eof_msgs=["test.eof"], ignore_messages=[])
        self._emit_after(0.05, Message("test.eof"))  # trigger finish quickly
        cs.capture(Message("test.trigger"), timeout=3)
        responses_before = cs.finish()
        count_before = len(responses_before)

        # emit another message after finish — should be ignored
        self.mc.bus.emit(Message("test.post.finish"))
        import time; time.sleep(0.05)

        self.assertEqual(len(cs.responses), count_before,
                         "no new messages should be captured after finish()")

    def test_multiple_eof_types(self):
        """Any message in the eof_msgs list should stop capture."""
        cs = CaptureSession(self.mc,
                            eof_msgs=["eof.alpha", "eof.beta"],
                            ignore_messages=[])
        self._emit_after(0.05, Message("test.x"))
        self._emit_after(0.10, Message("eof.beta"))   # second eof type
        self._emit_after(0.20, Message("test.late"))  # must not appear

        cs.capture(Message("test.trigger"), timeout=3)
        msgs = cs.finish()
        types = [m.msg_type for m in msgs]

        self.assertIn("test.x", types)
        self.assertNotIn("test.late", types)

    def test_eof_count_waits_for_n_occurrences(self):
        """With eof_count>1, capture continues until an eof topic is seen that
        many times — for scenarios with N concurrent lifecycles each terminating
        on the same eof topic."""
        cs = CaptureSession(self.mc,
                            eof_msgs=["test.eof"],
                            eof_count=2,
                            ignore_messages=[])
        self._emit_after(0.05, Message("test.eof"))      # 1st eof — must NOT stop
        self._emit_after(0.10, Message("test.between"))  # captured (after 1st eof)
        self._emit_after(0.15, Message("test.eof"))      # 2nd eof — stops capture
        self._emit_after(0.30, Message("test.after"))    # must NOT appear

        cs.capture(Message("test.trigger"), timeout=3)
        msgs = cs.finish()
        types = [m.msg_type for m in msgs]

        self.assertIn("test.between", types,
                      "a message between the 1st and 2nd eof must be captured")
        self.assertEqual(types.count("test.eof"), 2,
                         "both eof occurrences are captured")
        self.assertNotIn("test.after", types,
                         "message after the Nth eof must not be captured")

    def test_eof_count_resets_between_captures(self):
        """The eof counter resets per capture() call so eof_count applies fresh."""
        cs = CaptureSession(self.mc,
                            eof_msgs=["test.eof"],
                            eof_count=2,
                            ignore_messages=[])
        self._emit_after(0.05, Message("test.eof"))
        self._emit_after(0.10, Message("test.eof"))
        cs.capture(Message("test.trigger1"), timeout=3)
        cs.finish()
        # a second capture must again require 2 eofs, not be already-done
        cs2 = CaptureSession(self.mc, eof_msgs=["test.eof"], eof_count=2,
                             ignore_messages=[])
        self._emit_after(0.05, Message("test.eof"))
        self._emit_after(0.10, Message("test.mid"))
        self._emit_after(0.15, Message("test.eof"))
        cs2.capture(Message("test.trigger2"), timeout=3)
        types = [m.msg_type for m in cs2.finish()]
        self.assertIn("test.mid", types)

    def test_capture_timeout_returns_partial_results(self):
        """If the EOF never fires, capture() must return after the timeout
        and finish() must still return whatever was captured."""
        cs = CaptureSession(self.mc, eof_msgs=["never.fires"], ignore_messages=[])
        self._emit_after(0.05, Message("test.partial"))
        # timeout=0.2 — EOF never fires
        cs.capture(Message("test.trigger"), timeout=0.2)
        msgs = cs.finish()
        types = [m.msg_type for m in msgs]
        self.assertIn("test.partial", types)


class TestCaptureSessionNamespaceMirror(unittest.TestCase):
    """Collapsing the legacy<->ovos.* namespace mirror in the captured stream.

    A bare FakeBus (no MiniCroft handlers) is used so the dual-namespace
    emit is not perturbed by mock-TTS or other in-process components.
    """

    def setUp(self):
        import types
        from ovos_utils.fakebus import FakeBus
        LOG.set_level("ERROR")
        self.bus = FakeBus()
        self.holder = types.SimpleNamespace(bus=self.bus)

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _emit_after(self, delay_s, msg):
        def _run():
            import time
            time.sleep(delay_s)
            self.bus.emit(msg)
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    def test_namespace_mirror_counted_once(self):
        """A logical event reaching the bus on BOTH namespaces (a canonical
        topic and its legacy migration mirror, same payload) is captured once.

        This is the namespace-migration dual-send: without collapsing, a
        sequence authored against a single namespace would double its counts
        ("got 10, expected 5").
        """
        spec, legacy = "ovos.utterance.speak", "speak"
        payload = {"utterance": "hello"}
        cs = CaptureSession(self.holder, eof_msgs=["test.eof"], ignore_messages=[])
        self._emit_after(0.05, Message(spec, data=dict(payload)))
        self._emit_after(0.10, Message(legacy, data=dict(payload)))  # mirror
        self._emit_after(0.15, Message("test.eof"))

        cs.capture(Message("test.trigger"), timeout=3)
        types_ = [m.msg_type for m in cs.finish()]

        self.assertEqual(types_.count(spec), 1)
        self.assertEqual(types_.count(legacy), 0,
                         "the legacy mirror of the preceding canonical message "
                         "must not be counted a second time")

    def test_namespace_mirror_kept_when_collapse_disabled(self):
        """collapse_namespace_mirrors=False keeps BOTH namespaces so a test may
        assert the mirror explicitly."""
        spec, legacy = "ovos.utterance.speak", "speak"
        payload = {"utterance": "hello"}
        cs = CaptureSession(self.holder, eof_msgs=["test.eof"], ignore_messages=[],
                            collapse_namespace_mirrors=False)
        self._emit_after(0.05, Message(spec, data=dict(payload)))
        self._emit_after(0.10, Message(legacy, data=dict(payload)))
        self._emit_after(0.15, Message("test.eof"))

        cs.capture(Message("test.trigger"), timeout=3)
        types_ = [m.msg_type for m in cs.finish()]

        self.assertEqual(types_.count(spec), 1)
        self.assertEqual(types_.count(legacy), 1)

    def test_distinct_events_not_collapsed(self):
        """Two genuine events on a migrating topic with DIFFERENT payloads are
        both kept — collapse only drops an adjacent, payload-equal mirror."""
        cs = CaptureSession(self.holder, eof_msgs=["test.eof"], ignore_messages=[])
        self._emit_after(0.05, Message("speak", data={"utterance": "first"}))
        self._emit_after(0.10, Message("speak", data={"utterance": "second"}))
        self._emit_after(0.15, Message("test.eof"))

        cs.capture(Message("test.trigger"), timeout=3)
        utts = [m.data.get("utterance") for m in cs.finish()
                if m.msg_type == "speak"]

        self.assertEqual(utts, ["first", "second"],
                         "distinct payloads on the same topic must not collapse")


if __name__ == "__main__":
    unittest.main()
