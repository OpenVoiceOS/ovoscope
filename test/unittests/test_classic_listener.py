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
"""Unit tests for the MiniClassicListener harness (mycroft-classic-listener).

The event-bridge test does not need the classic listener installed (it drives a
plain EventEmitter).  The file-drive test exercises the real RecognizerLoop and
is gated on the package being importable.
"""
import io
import unittest
import wave

from ovos_utils.fakebus import FakeBus

from ovoscope.classic_listener import (
    MiniClassicListener,
    bridge_recognizer_loop_to_bus,
    classic_listener_available,
)
from ovoscope.voice_loop import MockHotWordEngine, MockStreamingSTT

try:
    from pyee import EventEmitter
    HAS_PYEE = True
except ImportError:
    HAS_PYEE = False

HAS_CLASSIC = classic_listener_available()


def _wav(speech_seconds=2.0, sample_rate=16000, sample_width=2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setframerate(sample_rate)
        w.setsampwidth(sample_width)
        w.setnchannels(1)
        w.writeframes(b"\x10\x20" * int(sample_rate * speech_seconds))
    return buf.getvalue()


@unittest.skipUnless(HAS_PYEE, "pyee not installed")
class TestEventBridge(unittest.TestCase):
    """The RecognizerLoop event → FakeBus bridge (no classic listener needed)."""

    def test_bridge_translates_events(self):
        """Internal loop events become recognizer_loop:* bus messages."""
        loop = EventEmitter()
        harness = MiniClassicListener(recognizer_loop=loop)

        loop.emit("recognizer_loop:record_begin")
        loop.emit("recognizer_loop:wakeword", {"utterance": "hey mycroft"})
        loop.emit("recognizer_loop:utterance",
                  {"utterances": ["hello world"], "lang": "en-us"})
        loop.emit("recognizer_loop:record_end")
        harness._last_messages = list(harness._messages)

        harness.assert_record_begin_emitted()
        harness.assert_wakeword_detected()
        harness.assert_utterance_emitted("hello world")

    def test_bridge_unknown_event(self):
        """The unknown event is forwarded to the bus."""
        bus = FakeBus()
        seen = []
        bus.on("message", lambda m: seen.append(
            m if isinstance(m, str) else m.serialize()))
        loop = EventEmitter()
        bridge_recognizer_loop_to_bus(loop, bus)
        loop.emit("recognizer_loop:speech.recognition.unknown")
        self.assertTrue(
            any("speech.recognition.unknown" in s for s in seen)
        )

    def test_feed_file_requires_built_loop(self):
        """feed_file is unavailable when an external loop was supplied."""
        harness = MiniClassicListener(recognizer_loop=EventEmitter())
        with self.assertRaises(RuntimeError):
            harness.feed_file(b"\x00" * 1024)


@unittest.skipUnless(HAS_CLASSIC, "mycroft-classic-listener not installed")
class TestMiniClassicListenerFileDrive(unittest.TestCase):
    """Best-effort file-driven test against a real RecognizerLoop."""

    def test_full_sequence_with_utterance(self):
        """Driving an audio file yields record-begin and the utterance."""
        with MiniClassicListener(
            wakeword=MockHotWordEngine("hey_mycroft", trigger_after=1),
            stt_instance=MockStreamingSTT(transcript="hello world"),
        ) as cl:
            msgs = cl.feed_file(_wav(2.0), tail_silence_seconds=3.0, timeout=20)
            types = [m.msg_type for m in msgs]
            self.assertIn("recognizer_loop:record_begin", types)
            self.assertIn("recognizer_loop:record_end", types)
            cl.assert_utterance_emitted("hello world", msgs)


if __name__ == "__main__":
    unittest.main()
