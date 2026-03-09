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


if __name__ == "__main__":
    unittest.main()
