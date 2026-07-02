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
"""Unit tests for MiniListener.feed_audio_stream and ListenerTest streaming.

Uses a self-contained stub transformer (no native ggwave dependency) that only
emits its message after accumulating a threshold number of frames — exactly the
behaviour ``feed_audio_stream`` exists to support.
"""
import unittest

from ovos_bus_client.message import Message
from ovoscope.listener import ListenerTest, MiniListener, get_mini_listener


_BASE_CONFIG = {"listener": {"audio_transformers": {}}}


class _AccumulatingTransformer:
    """Stub audio transformer that fires only after N fed frames.

    Mirrors a real streaming decoder: a single ``feed_audio`` call never
    produces output, so the aggregating ``feed_audio_stream`` is required to
    observe the emitted message.
    """

    def __init__(self, trigger_after=3, msg_type="recognizer_loop:utterance"):
        self.name = "stub"
        self.priority = 10
        self.trigger_after = trigger_after
        self.msg_type = msg_type
        self.count = 0
        self.bus = None

    def bind(self, bus):
        self.bus = bus

    def feed_audio_chunk(self, chunk):
        self.count += 1
        if self.count == self.trigger_after:
            self.bus.emit(Message(self.msg_type, {"utterances": ["streamed"]}))

    def feed_speech_chunk(self, chunk):
        self.feed_audio_chunk(chunk)

    def shutdown(self):
        pass


def _listener(trigger_after=3):
    plugin = _AccumulatingTransformer(trigger_after=trigger_after)
    return get_mini_listener(
        config=_BASE_CONFIG,
        plugin_instances={"stub": plugin},
    )


class TestFeedAudioStream(unittest.TestCase):
    """MiniListener.feed_audio_stream aggregation behaviour."""

    def test_single_feed_audio_misses_late_decode(self):
        """A lone feed_audio call before the threshold yields nothing."""
        listener = _listener(trigger_after=3)
        try:
            self.assertEqual(listener.feed_audio(b"\x00" * 100), [])
        finally:
            listener.shutdown()

    def test_stream_aggregates_across_frames(self):
        """feed_audio_stream keeps the message emitted on a later frame."""
        listener = _listener(trigger_after=3)
        try:
            msgs = listener.feed_audio_stream([b"\x00" * 100] * 5)
            types = [m.msg_type for m in msgs]
            self.assertIn("recognizer_loop:utterance", types)
        finally:
            listener.shutdown()

    def test_stream_splits_flat_bytes_by_chunk_size(self):
        """A flat bytes object is split into chunk_size frames."""
        listener = _listener(trigger_after=4)
        try:
            # 4 frames of 50 bytes -> fourth frame triggers
            msgs = listener.feed_audio_stream(b"\x00" * 200, chunk_size=50)
            self.assertTrue(
                any(m.msg_type == "recognizer_loop:utterance" for m in msgs)
            )
        finally:
            listener.shutdown()

    def test_stream_feed_speech_path(self):
        """feed='feed_speech' drives the speech feed instead of audio."""
        listener = _listener(trigger_after=2)
        try:
            msgs = listener.feed_audio_stream(
                [b"\x00" * 100] * 3, feed="feed_speech"
            )
            self.assertTrue(
                any(m.msg_type == "recognizer_loop:utterance" for m in msgs)
            )
        finally:
            listener.shutdown()

    def test_invalid_feed_raises(self):
        """An unknown feed method is rejected."""
        listener = _listener()
        try:
            with self.assertRaises(ValueError):
                listener.feed_audio_stream([b"\x00" * 10], feed="nope")
        finally:
            listener.shutdown()


class TestListenerTestStreaming(unittest.TestCase):
    """ListenerTest declarative streaming support."""

    def test_listener_test_feed_audio_stream(self):
        """ListenerTest with feed_method='feed_audio_stream' aggregates."""
        plugin = _AccumulatingTransformer(trigger_after=3)
        ListenerTest(
            config=_BASE_CONFIG,
            plugin_instances={"stub": plugin},
            audio_input=b"\x00" * 300,
            feed_method="feed_audio_stream",
            chunk_size=100,
            expected_types=["recognizer_loop:utterance"],
        ).execute()

    def test_listener_test_forbidden_absent(self):
        """forbidden_types passes when the type never appears."""
        plugin = _AccumulatingTransformer(trigger_after=2)
        ListenerTest(
            config=_BASE_CONFIG,
            plugin_instances={"stub": plugin},
            audio_input=b"\x00" * 200,
            feed_method="feed_audio_stream",
            chunk_size=100,
            expected_types=["recognizer_loop:utterance"],
            forbidden_types=["speak"],
        ).execute()


if __name__ == "__main__":
    unittest.main()
