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

from ovos_bus_client.message import Message
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

try:
    from ovos_spec_tools import SpecMessage
    HAS_SPEC = True
except ImportError:
    HAS_SPEC = False

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


@unittest.skipUnless(HAS_PYEE, "pyee not installed")
@unittest.skipUnless(HAS_SPEC, "ovos-spec-tools not installed")
class TestClassicListenerNamespaceBridging(unittest.TestCase):
    """The classic listener bridge emits the LEGACY recognizer_loop:* /
    mycroft.awoken topics, while OVOS migrates them to the ovos.* SPEC namespace.
    These tests pin that the harness FakeBus namespace bridging connects the two,
    and that turning it off isolates a single namespace.

    Migrated pairs exercised here (legacy -> spec):
        recognizer_loop:utterance     -> ovos.utterance.handle
        recognizer_loop:record_begin  -> ovos.listener.record.started
        recognizer_loop:record_end    -> ovos.listener.record.ended
        mycroft.awoken                -> ovos.listener.awoken
    """

    def _harness(self, **kwargs):
        """Build a MiniClassicListener around a plain EventEmitter loop.

        No classic listener install is needed — the bridge drives any
        EventEmitter and re-emits its events onto the harness FakeBus.
        """
        return MiniClassicListener(recognizer_loop=EventEmitter(), **kwargs)

    def test_utterance_legacy_reaches_spec_default(self):
        """Default harness (bridging on): the bridge's legacy
        recognizer_loop:utterance reaches an ovos.utterance.handle subscriber."""
        h = self._harness()  # modernize/emit_legacy default on
        seen = []
        h.bus.on(str(SpecMessage.UTTERANCE), lambda m: seen.append(m.msg_type))
        h.loop.emit("recognizer_loop:utterance",
                    {"utterances": ["hello world"], "lang": "en-us"})
        self.assertIn(str(SpecMessage.UTTERANCE), seen)

    def test_utterance_spec_reaches_legacy_default(self):
        """Default harness (bridging on): a SPEC producer of
        ovos.utterance.handle reaches a legacy recognizer_loop:utterance
        subscriber — the new namespace is exercised natively too."""
        h = self._harness()
        seen = []
        h.bus.on("recognizer_loop:utterance", lambda m: seen.append(m.msg_type))
        h.bus.emit(Message(str(SpecMessage.UTTERANCE),
                           {"utterances": ["hello world"]}))
        self.assertIn("recognizer_loop:utterance", seen)

    def test_record_begin_end_bridge_to_spec(self):
        """The bridge's record_begin/record_end reach their spec counterparts."""
        h = self._harness()
        started, ended = [], []
        h.bus.on(str(SpecMessage.LISTENER_RECORD_STARTED),
                 lambda m: started.append(m.msg_type))
        h.bus.on(str(SpecMessage.LISTENER_RECORD_ENDED),
                 lambda m: ended.append(m.msg_type))
        h.loop.emit("recognizer_loop:record_begin")
        h.loop.emit("recognizer_loop:record_end")
        self.assertIn(str(SpecMessage.LISTENER_RECORD_STARTED), started)
        self.assertIn(str(SpecMessage.LISTENER_RECORD_ENDED), ended)

    def test_awoken_bridges_to_spec(self):
        """The bridge maps recognizer_loop:awoken -> mycroft.awoken, which
        migrates to ovos.listener.awoken via modernize bridging."""
        h = self._harness()
        seen = []
        h.bus.on(str(SpecMessage.LISTENER_AWOKEN), lambda m: seen.append(m.msg_type))
        h.loop.emit("recognizer_loop:awoken")
        self.assertIn(str(SpecMessage.LISTENER_AWOKEN), seen)

    def test_awoken_spec_reaches_legacy_default(self):
        """A SPEC producer of ovos.listener.awoken reaches a legacy
        mycroft.awoken subscriber via emit_legacy bridging."""
        h = self._harness()
        seen = []
        h.bus.on("mycroft.awoken", lambda m: seen.append(m.msg_type))
        h.bus.emit(Message(str(SpecMessage.LISTENER_AWOKEN)))
        self.assertIn("mycroft.awoken", seen)

    def test_no_bridging_isolates_legacy_from_spec(self):
        """With bridging OFF, the bridge's legacy emits do NOT reach the
        spec-only subscribers — proving a single namespace can be exercised."""
        h = self._harness(modernize=False, emit_legacy=False)
        utt, started, ended, awoken = [], [], [], []
        h.bus.on(str(SpecMessage.UTTERANCE), lambda m: utt.append(m))
        h.bus.on(str(SpecMessage.LISTENER_RECORD_STARTED), lambda m: started.append(m))
        h.bus.on(str(SpecMessage.LISTENER_RECORD_ENDED), lambda m: ended.append(m))
        h.bus.on(str(SpecMessage.LISTENER_AWOKEN), lambda m: awoken.append(m))

        h.loop.emit("recognizer_loop:utterance", {"utterances": ["hi"]})
        h.loop.emit("recognizer_loop:record_begin")
        h.loop.emit("recognizer_loop:record_end")
        h.loop.emit("recognizer_loop:awoken")

        self.assertEqual(utt, [])
        self.assertEqual(started, [])
        self.assertEqual(ended, [])
        self.assertEqual(awoken, [])


if __name__ == "__main__":
    unittest.main()
