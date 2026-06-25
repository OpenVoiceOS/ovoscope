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
"""Unit tests for the MiniSimpleListener harness (ovos-simple-listener)."""
import io
import time
import unittest
import wave

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage

from ovoscope.simple_listener import MiniSimpleListener
from ovoscope.voice_loop import MockHotWordEngine, MockStreamingSTT

def _mic_available() -> bool:
    """SimpleListener eagerly builds a real microphone in __init__ (mic=None),
    so the harness can only be constructed when a microphone plugin is present.
    """
    try:
        from ovos_plugin_manager.microphone import OVOSMicrophoneFactory
        OVOSMicrophoneFactory.create()
        return True
    except Exception:
        return False


HAS_MIC = _mic_available()

try:
    import ovos_simple_listener  # noqa: F401
    HAS_SIMPLE = True
except ImportError:
    HAS_SIMPLE = False


def _wav(speech_seconds=0.6, sample_rate=16000, sample_width=2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setframerate(sample_rate)
        w.setsampwidth(sample_width)
        w.setnchannels(1)
        w.writeframes(b"\x10\x20" * int(sample_rate * speech_seconds))
    return buf.getvalue()


@unittest.skipUnless(HAS_SIMPLE, "ovos-simple-listener not installed")
class TestMiniSimpleListener(unittest.TestCase):
    """MiniSimpleListener integration tests against a real SimpleListener."""

    def test_full_sequence_with_utterance(self):
        """A wake word + command yields the full bus sequence + utterance."""
        with MiniSimpleListener(
            wakeword=MockHotWordEngine("hey_mycroft", trigger_after=2),
            stt_instance=MockStreamingSTT(transcript="turn on the lights"),
        ) as sl:
            msgs = sl.feed_file(_wav(), silence_tail_chunks=20)
            types = [m.msg_type for m in msgs]
            self.assertIn("recognizer_loop:wakeword", types)
            self.assertIn("recognizer_loop:record_begin", types)
            self.assertIn("recognizer_loop:record_end", types)
            sl.assert_utterance_emitted("turn on the lights", msgs)

    def test_empty_transcript_unknown(self):
        """An empty transcript emits the recognition-unknown event."""
        with MiniSimpleListener(
            wakeword=MockHotWordEngine("hey_mycroft", trigger_after=2),
            stt_instance=MockStreamingSTT(transcript=""),
        ) as sl:
            msgs = sl.feed_file(_wav(), silence_tail_chunks=20)
            types = [m.msg_type for m in msgs]
            self.assertIn("recognizer_loop:speech.recognition.unknown", types)
            self.assertNotIn("recognizer_loop:utterance", types)

    def test_record_begin_helper(self):
        """The shared assert_record_begin_emitted helper works here too."""
        with MiniSimpleListener(
            wakeword=MockHotWordEngine("hey_mycroft", trigger_after=1),
            stt_instance=MockStreamingSTT(transcript="hello"),
        ) as sl:
            sl.feed_file(_wav(), silence_tail_chunks=20)
            sl.assert_record_begin_emitted()


# ---------------------------------------------------------------------------
# TestMiniSimpleListenerNamespaceBridging
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_SIMPLE, "ovos-simple-listener not installed")
@unittest.skipUnless(HAS_MIC, "no ovos microphone plugin available")
class TestMiniSimpleListenerNamespaceBridging(unittest.TestCase):
    """The _SimpleBusCallbacks emit the LEGACY ``recognizer_loop:*`` topics;
    ``record_begin``/``record_end``/``utterance`` are migrated to the ovos.*
    spec namespace.  These tests pin that the FakeBus namespace bridging
    connects the two namespaces, and that turning it off isolates one.
    """

    def test_full_sequence_legacy_reaches_spec_via_bridging(self):
        """Default harness (bridging on): the legacy record-begin/record-end/
        utterance emitted while running the listener are also delivered to
        subscribers on the spec topics."""
        with MiniSimpleListener(
            wakeword=MockHotWordEngine("hey_mycroft", trigger_after=2),
            stt_instance=MockStreamingSTT(transcript="turn on the lights"),
        ) as sl:
            spec = {"begin": [], "end": [], "utt": []}
            sl.bus.on(str(SpecMessage.LISTENER_RECORD_STARTED),
                      lambda m: spec["begin"].append(m))
            sl.bus.on(str(SpecMessage.LISTENER_RECORD_ENDED),
                      lambda m: spec["end"].append(m))
            sl.bus.on(str(SpecMessage.UTTERANCE),
                      lambda m: spec["utt"].append(m))

            msgs = sl.feed_file(_wav(), silence_tail_chunks=20)
            time.sleep(0.05)
            legacy_types = [m.msg_type for m in msgs]
            self.assertIn("recognizer_loop:record_begin", legacy_types)
            self.assertTrue(spec["begin"],
                            "ovos.listener.record.started not seen via bridge")
            self.assertTrue(spec["end"],
                            "ovos.listener.record.ended not seen via bridge")
            self.assertTrue(spec["utt"],
                            "ovos.utterance.handle not seen via bridge")

    def test_record_begin_spec_native(self):
        """A SPEC producer reaches a spec subscriber natively."""
        with MiniSimpleListener(
            wakeword=MockHotWordEngine("hey_mycroft", trigger_after=2),
        ) as sl:
            spec_hits = []
            sl.bus.on(str(SpecMessage.LISTENER_RECORD_STARTED),
                      lambda m: spec_hits.append(m))
            sl.bus.emit(Message(str(SpecMessage.LISTENER_RECORD_STARTED)))
            time.sleep(0.05)
            self.assertTrue(spec_hits,
                            "ovos.listener.record.started not delivered natively")

    def test_no_bridging_isolates_legacy_from_spec(self):
        """With bridging OFF, a legacy record-begin does NOT reach a spec-only
        subscriber."""
        with MiniSimpleListener(
            wakeword=MockHotWordEngine("hey_mycroft", trigger_after=2),
            modernize=False, emit_legacy=False,
        ) as sl:
            legacy_hits, spec_hits = [], []
            sl.bus.on("recognizer_loop:record_begin",
                      lambda m: legacy_hits.append(m))
            sl.bus.on(str(SpecMessage.LISTENER_RECORD_STARTED),
                      lambda m: spec_hits.append(m))
            sl.bus.emit(Message("recognizer_loop:record_begin"))
            time.sleep(0.1)
            self.assertTrue(legacy_hits, "legacy record_begin should still fire")
            self.assertEqual(spec_hits, [],
                             "spec topic must not fire with bridging off")


if __name__ == "__main__":
    unittest.main()
