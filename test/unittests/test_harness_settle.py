"""The player asserts wait for the bus instead of reading once.

The harness emits on the bus and the player transitions on another thread,
so an assert that reads a single time reports "not yet" as "wrong". These
pin the waiting, and pin that waiting did not make the assert vacuous.
"""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from ovos_utils.ocp import MediaState, PlayerState

from ovoscope.media import OCPPlayerHarness


class _LateState:
    """A value that becomes ``final`` only after ``delay`` seconds.

    Stands in for the player transitioning on the bus thread.
    """

    def __init__(self, first, final, delay):
        self.first, self.final, self.delay = first, final, delay
        self.ready_at = time.monotonic() + delay
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.final if time.monotonic() >= self.ready_at else self.first


def _harness(timeout=1.0):
    """An OCPPlayerHarness without its __init__: _eventually touches only
    settle_timeout, so the real method is called on a plain stand-in."""
    stub = SimpleNamespace(settle_timeout=timeout)
    stub._eventually = lambda read, want, describe: (
        OCPPlayerHarness._eventually(stub, read, want, describe))
    return stub


class TestEventuallyWaits(unittest.TestCase):
    def test_a_late_value_is_accepted(self):
        late = _LateState(PlayerState.STOPPED, PlayerState.PLAYING, 0.20)
        h = _harness()
        started = time.monotonic()
        h._eventually(late.read, PlayerState.PLAYING, lambda got: f"got {got}")
        waited = time.monotonic() - started
        self.assertGreaterEqual(waited, 0.20,
                                "it returned before the value could change")
        self.assertGreater(late.reads, 1, "it read only once")

    def test_a_value_already_right_returns_at_once(self):
        """A passing assert must not cost the settle timeout, or every green
        suite pays for this fix."""
        h = _harness(timeout=5.0)
        started = time.monotonic()
        h._eventually(lambda: PlayerState.PLAYING, PlayerState.PLAYING,
                      lambda got: f"got {got}")
        self.assertLess(time.monotonic() - started, 0.5)

    def test_a_value_that_never_arrives_still_fails(self):
        """The control. A polling assert that always passed would be worse
        than the flake it replaces."""
        h = _harness(timeout=0.2)
        with self.assertRaises(AssertionError) as caught:
            h._eventually(lambda: PlayerState.STOPPED, PlayerState.PLAYING,
                          lambda got: f"got PlayerState.{got.name}")
        self.assertIn("STOPPED", str(caught.exception),
                      "the message must name the value actually read")

    def test_the_deadline_is_honoured(self):
        h = _harness(timeout=0.2)
        started = time.monotonic()
        with self.assertRaises(AssertionError):
            h._eventually(lambda: MediaState.NO_MEDIA, MediaState.LOADED_MEDIA,
                          lambda got: f"got {got}")
        waited = time.monotonic() - started
        self.assertGreaterEqual(waited, 0.2)
        self.assertLess(waited, 2.0, "it waited well past its own deadline")


class _NeverPlays:
    """A player and backend that stay stopped, however long anyone waits."""

    state = PlayerState.STOPPED
    media_state = MediaState.NO_MEDIA
    now_playing = None
    is_playing = False
    is_paused = False


def _real_harness():
    """A real OCPPlayerHarness without its __init__.

    The asserts read only ``self.player`` and ``self.backend``, so the real
    methods run against a stand-in that never transitions.
    """
    h = object.__new__(OCPPlayerHarness)
    h.player = _NeverPlays()
    h.backend = _NeverPlays()
    return h


class TestTheAssertsRouteThroughTheHelper(unittest.TestCase):
    """C1: the helper being right proves nothing if the asserts do not use it.

    Reverting any one assert to a single read leaves it raising at once, so
    the elapsed time is what pins the routing, not the raise.
    """

    #: Small enough to keep the file fast, large enough that a single read
    #: cannot reach it.
    PATCHED = 0.30

    def _each_assert(self, h):
        return [
            ("assert_player_state",
             lambda: h.assert_player_state(PlayerState.PLAYING)),
            ("assert_media_state",
             lambda: h.assert_media_state(MediaState.LOADED_MEDIA)),
            ("assert_backend_playing", h.assert_backend_playing),
            ("assert_backend_paused", h.assert_backend_paused),
            ("assert_backend_stopped",
             lambda: h.assert_backend_stopped()),
            ("assert_now_playing_uri",
             lambda: h.assert_now_playing_uri("file:///x.mp3")),
        ]

    def test_five_asserts_wait_the_class_timeout_before_they_fail(self):
        h = _real_harness()
        with mock.patch.object(OCPPlayerHarness, "settle_timeout",
                               self.PATCHED):
            for name, call in self._each_assert(h):
                if name == "assert_backend_stopped":
                    # The stand-in genuinely satisfies this one: a waiting
                    # assert on a value already right must return at once.
                    started = time.monotonic()
                    call()
                    self.assertLess(time.monotonic() - started, self.PATCHED,
                                    f"{name} waited on a value already right")
                    continue
                started = time.monotonic()
                with self.assertRaises(AssertionError) as caught:
                    call()
                waited = time.monotonic() - started
                self.assertGreaterEqual(
                    waited, self.PATCHED,
                    f"{name} failed after {waited:.3f}s: it read once "
                    f"instead of waiting the class settle_timeout")
                self.assertLess(waited, self.PATCHED * 10,
                                f"{name} waited past its own deadline")
                self.assertIn("after", str(caught.exception),
                              f"{name} does not say that it waited")
                self.assertIn("settle_timeout", str(caught.exception),
                              f"{name} does not name the deadline it used")


class TestHarnessExposesTheTimeout(unittest.TestCase):
    def test_settle_timeout_is_a_class_attribute(self):
        """A suite on a slow runner has to be able to raise it."""
        self.assertIsInstance(OCPPlayerHarness.settle_timeout, float)
        self.assertGreater(OCPPlayerHarness.settle_timeout, 0)

    def test_the_default_timeout_stays_within_a_readable_range(self):
        """A silently widened default turns a two-second answer into a
        suite that takes minutes to say the same thing. Six asserts share
        this number, so the bound is part of the contract."""
        self.assertGreaterEqual(OCPPlayerHarness.settle_timeout, 0.5)
        self.assertLessEqual(OCPPlayerHarness.settle_timeout, 5.0)


if __name__ == "__main__":
    unittest.main()
