"""The OCP assertions wait for a transition instead of sampling once.

`OCPPlayerHarness.play()` emits on the bus and returns; the player transitions
on ANOTHER thread. Every assertion used to read once, so on a busy box the read
landed before the transition and reported the state it had not left yet: "not
yet" and "wrong" are different answers and one read cannot tell them apart.
Measured by the plugins lane in ovos-media-plugin-chromecast at origin/dev,
4 failures in 12 runs, always the first assert after play().

These rows drive the waiting helper directly, so they do not need a player or a
bus, and they pin the three properties that make the fix safe rather than
merely green.
"""
import time
import unittest

from ovoscope.media import OCPPlayerHarness


class _Harness(OCPPlayerHarness):
    """The helper alone: no bus, no player, no backend."""

    def __init__(self):        # deliberately not calling super().__init__
        pass


class TestTheWaitingHelper(unittest.TestCase):

    def test_a_value_that_is_already_right_returns_at_once(self):
        """A passing assertion must not make the suite slower."""
        h = _Harness()
        started = time.monotonic()
        h._eventually(lambda: "ready", lambda v: v == "ready",
                      lambda v: "never used")
        self.assertLess(time.monotonic() - started, 0.05)

    def test_a_value_that_arrives_late_is_waited_for(self):
        """The defect: the transition lands after the first read."""
        h = _Harness()
        reads = []

        def read():
            reads.append(len(reads))
            # "not yet" for the first few reads, then the real state
            return "playing" if len(reads) > 3 else "stopped"

        h._eventually(read, lambda v: v == "playing", lambda v: "no")
        self.assertGreater(len(reads), 1,
                           "it must re-read, not sample once")

    def test_a_value_that_never_arrives_still_fails(self):
        """The control that matters. A polling assertion that always passes
        would be worse than the flake it replaces."""
        h = _Harness()
        h.settle_timeout = 0.2
        started = time.monotonic()
        with self.assertRaises(AssertionError) as caught:
            h._eventually(lambda: "stopped", lambda v: v == "playing",
                          lambda v: f"Expected playing, got {v}")
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.2, "it must wait the deadline")
        # the message names the state it really read, and the deadline
        self.assertIn("got stopped", str(caught.exception))
        self.assertIn("0.2s", str(caught.exception))

    def test_a_zero_timeout_reads_once(self):
        """The old behaviour stays reachable, for a caller that wants it."""
        h = _Harness()
        h.settle_timeout = 0
        reads = []
        with self.assertRaises(AssertionError):
            h._eventually(lambda: reads.append(1) or "stopped",
                          lambda v: v == "playing",
                          lambda v: f"Expected playing, got {v}")
        self.assertEqual(len(reads), 1)


class TestAssertBackendStoppedReadsBothTogether(unittest.TestCase):
    """is_playing and is_paused are read in ONE pass.

    A backend that stops playing and pauses in the same transition must never
    look stopped in between. Two sequential single-condition waits could see
    exactly that, so the two conditions are read as one tuple.
    """

    def test_a_backend_that_is_paused_is_not_stopped(self):
        class _Backend:
            is_playing = False
            is_paused = True

        h = _Harness()
        h.settle_timeout = 0.05
        h.backend = _Backend()
        with self.assertRaises(AssertionError) as caught:
            h.assert_backend_stopped()
        self.assertIn("is_paused=True", str(caught.exception))

    def test_a_backend_that_is_playing_is_not_stopped(self):
        class _Backend:
            is_playing = True
            is_paused = False

        h = _Harness()
        h.settle_timeout = 0.05
        h.backend = _Backend()
        with self.assertRaises(AssertionError) as caught:
            h.assert_backend_stopped()
        self.assertIn("is_playing=True", str(caught.exception))

    def test_a_backend_that_stops_late_passes(self):
        class _Backend:
            def __init__(self):
                self.reads = 0

            @property
            def is_playing(self):
                self.reads += 1
                return self.reads < 3

            is_paused = False

        h = _Harness()
        h.backend = _Backend()
        h.assert_backend_stopped()          # must not raise


if __name__ == "__main__":
    unittest.main()
