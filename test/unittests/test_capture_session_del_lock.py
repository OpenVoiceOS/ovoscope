"""CaptureSession must not take the bus lock from __del__.

pyee's EventEmitter guards its handler map with a plain (non-reentrant)
``threading.Lock``. ``_call_handlers`` holds that lock while it copies the
handler list, and the copy can start CPython's cyclic garbage collector. If
the collector then runs ``CaptureSession.__del__`` on the same thread, and
``__del__`` calls ``bus.remove()``, ``remove_listener`` waits for the lock its
own thread already holds: a self-deadlock. It hung ovos-skill-weather#263 on
Python 3.10 and 3.12.

These tests use a ``SimpleNamespace(bus=FakeBus())`` stub, so no MiniCroft
is booted.
"""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ovos_utils.fakebus import FakeBus

from ovoscope import CaptureSession

# long enough for a healthy __del__ on a slow runner, short enough to fail fast
JOIN_TIMEOUT = 5.0


def _session():
    bus = FakeBus()
    return CaptureSession(SimpleNamespace(bus=bus)), bus


class TestDelDoesNotTakeTheBusLock(unittest.TestCase):

    def test_del_while_the_emitter_lock_is_held_on_the_same_thread(self):
        """The collector running __del__ inside _call_handlers must not hang."""
        session, bus = _session()
        errors = []

        def collect_during_emit():
            # what _call_handlers does: hold the emitter lock on this thread
            with bus.ee._lock:
                try:
                    session.__del__()  # what the cyclic collector would call
                except Exception as exc:  # pragma: no cover - reported below
                    errors.append(exc)

        # daemon: before the fix this thread never returns
        worker = threading.Thread(target=collect_during_emit, daemon=True)
        worker.start()
        worker.join(JOIN_TIMEOUT)

        self.assertFalse(
            worker.is_alive(),
            "CaptureSession.__del__ deadlocked on the pyee emitter lock")
        self.assertEqual(errors, [])
        self.assertTrue(session.done.is_set())

    def test_del_does_not_touch_the_bus(self):
        session, bus = _session()
        with patch.object(bus, "remove") as remove:
            session.__del__()
        remove.assert_not_called()


class TestFinishIsIdempotent(unittest.TestCase):

    def test_a_second_finish_does_not_touch_the_bus(self):
        session, bus = _session()
        first = session.finish()
        with patch.object(bus, "remove") as remove:
            second = session.finish()
        remove.assert_not_called()
        self.assertEqual(first, second)

    def test_the_first_finish_still_removes_every_listener(self):
        session, bus = _session()
        with patch.object(bus, "remove", wraps=bus.remove) as remove:
            session.finish()
        removed = {call.args[0] for call in remove.call_args_list}
        self.assertIn("message", removed)
        for topic in session._effective_eof_msgs():
            self.assertIn(topic, removed)
        self.assertTrue(session.done.is_set())


if __name__ == "__main__":
    unittest.main()
