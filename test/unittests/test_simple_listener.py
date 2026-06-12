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
import unittest
import wave

from ovoscope.simple_listener import MiniSimpleListener
from ovoscope.voice_loop import MockHotWordEngine, MockStreamingSTT

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


if __name__ == "__main__":
    unittest.main()
