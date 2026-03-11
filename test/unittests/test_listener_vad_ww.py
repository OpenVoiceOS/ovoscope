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
"""Unit tests for MiniListener VAD and WakeWord support.

TestMockVADEngine        (7 tests) — MockVADEngine behaviour
TestMockHotWordEngine    (7 tests) — MockHotWordEngine behaviour
TestMiniListenerVAD      (8 tests) — MiniListener VAD integration
TestMiniListenerWakeWord (9 tests) — MiniListener WakeWord integration
TestVADTest              (5 tests) — VADTest declarative helper
TestWakeWordTest         (5 tests) — WakeWordTest declarative helper
"""
import unittest

from ovoscope.listener import (
    MockHotWordEngine,
    MockVADEngine,
    MiniListener,
    VADTest,
    WakeWordTest,
    get_mini_listener,
)


_BASE_CONFIG = {"listener": {"audio_transformers": {}}}

_SILENCE = b"\x00" * 1024
_SPEECH = b"\x01\x02" * 512


# ---------------------------------------------------------------------------
# TestMockVADEngine
# ---------------------------------------------------------------------------

class TestMockVADEngine(unittest.TestCase):
    """MockVADEngine unit tests."""

    def test_silence_all_zeros(self):
        """All-zero bytes are classified as silence."""
        vad = MockVADEngine()
        self.assertTrue(vad.is_silence(b"\x00" * 512))

    def test_non_zero_not_silence(self):
        """Any non-zero byte makes a chunk non-silent."""
        vad = MockVADEngine()
        self.assertFalse(vad.is_silence(b"\x01" + b"\x00" * 511))

    def test_fully_non_zero_not_silence(self):
        """All non-zero bytes are classified as speech."""
        vad = MockVADEngine()
        self.assertFalse(vad.is_silence(b"\xff" * 512))

    def test_empty_chunk_is_silence(self):
        """Empty bytes are treated as silence (vacuously true)."""
        vad = MockVADEngine()
        self.assertTrue(vad.is_silence(b""))

    def test_extract_speech_strips_silence(self):
        """extract_speech returns only non-silent frames."""
        vad = MockVADEngine()
        audio = _SILENCE + _SPEECH  # silence then speech
        result = vad.extract_speech(audio)
        # Result must not be empty and must differ from the all-silent input
        self.assertGreater(len(result), 0)
        self.assertNotEqual(result, audio)

    def test_extract_speech_all_speech(self):
        """extract_speech on all-speech audio returns all bytes."""
        vad = MockVADEngine()
        result = vad.extract_speech(_SPEECH)
        self.assertEqual(result, _SPEECH)

    def test_reset_clears_counter(self):
        """reset() zeroes chunks_processed."""
        vad = MockVADEngine()
        vad.is_silence(b"\x00" * 64)
        vad.is_silence(b"\x01" * 64)
        self.assertEqual(vad.chunks_processed, 2)
        vad.reset()
        self.assertEqual(vad.chunks_processed, 0)


# ---------------------------------------------------------------------------
# TestMockHotWordEngine
# ---------------------------------------------------------------------------

class TestMockHotWordEngine(unittest.TestCase):
    """MockHotWordEngine unit tests."""

    def test_not_found_before_trigger(self):
        """No detection before trigger_after threshold is reached."""
        ww = MockHotWordEngine(trigger_after=3)
        ww.update(b"\x00" * 512)
        ww.update(b"\x00" * 512)
        self.assertFalse(ww.found_wake_word())

    def test_found_at_trigger(self):
        """Detection fires exactly at the trigger_after count."""
        ww = MockHotWordEngine(trigger_after=3)
        for _ in range(3):
            ww.update(b"\x00" * 512)
        self.assertTrue(ww.found_wake_word())

    def test_auto_reset_after_detection(self):
        """found_wake_word() auto-resets after returning True."""
        ww = MockHotWordEngine(trigger_after=1)
        ww.update(b"\x00" * 512)
        self.assertTrue(ww.found_wake_word())
        self.assertFalse(ww.found_wake_word())

    def test_key_phrase_normalized(self):
        """Spaces in key_phrase are replaced with underscores."""
        ww = MockHotWordEngine(key_phrase="hey mycroft")
        self.assertEqual(ww.key_phrase, "hey_mycroft")

    def test_trigger_after_1_default(self):
        """Default trigger_after=1: detection on first update."""
        ww = MockHotWordEngine()
        ww.update(b"\x00" * 512)
        self.assertTrue(ww.found_wake_word())

    def test_reset_clears_state(self):
        """reset() zeroes update_count and clears pending detection."""
        ww = MockHotWordEngine(trigger_after=2)
        ww.update(b"\x00" * 512)
        ww.update(b"\x00" * 512)
        ww.reset()
        self.assertEqual(ww.update_count, 0)
        self.assertFalse(ww.found_wake_word())

    def test_shutdown_no_crash(self):
        """shutdown() on a fresh engine raises no exception."""
        ww = MockHotWordEngine()
        ww.shutdown()  # should not raise


# ---------------------------------------------------------------------------
# TestMiniListenerVAD
# ---------------------------------------------------------------------------

class TestMiniListenerVAD(unittest.TestCase):
    """MiniListener VAD integration tests."""

    def test_is_silence_delegates_to_vad(self):
        """is_silence() uses the injected VAD engine."""
        vad = MockVADEngine()
        listener = MiniListener(_BASE_CONFIG, vad_instance=vad)
        try:
            self.assertTrue(listener.is_silence(_SILENCE))
            self.assertFalse(listener.is_silence(_SPEECH))
        finally:
            listener.shutdown()

    def test_is_silence_no_vad_raises(self):
        """is_silence() without a VAD engine raises RuntimeError."""
        listener = MiniListener(_BASE_CONFIG)
        try:
            with self.assertRaises(RuntimeError):
                listener.is_silence(_SILENCE)
        finally:
            listener.shutdown()

    def test_extract_speech_delegates_to_vad(self):
        """extract_speech() uses the injected VAD engine."""
        vad = MockVADEngine()
        listener = MiniListener(_BASE_CONFIG, vad_instance=vad)
        try:
            result = listener.extract_speech(_SILENCE + _SPEECH)
            self.assertIsInstance(result, bytes)
        finally:
            listener.shutdown()

    def test_extract_speech_no_vad_raises(self):
        """extract_speech() without a VAD engine raises RuntimeError."""
        listener = MiniListener(_BASE_CONFIG)
        try:
            with self.assertRaises(RuntimeError):
                listener.extract_speech(_SILENCE)
        finally:
            listener.shutdown()

    def test_factory_vad_instance(self):
        """get_mini_listener(vad_instance=…) loads VAD correctly."""
        listener = get_mini_listener(vad_instance=MockVADEngine())
        try:
            self.assertTrue(listener.is_silence(_SILENCE))
        finally:
            listener.shutdown()

    def test_vad_chunks_processed_increments(self):
        """chunks_processed increments with each is_silence call."""
        vad = MockVADEngine()
        listener = MiniListener(_BASE_CONFIG, vad_instance=vad)
        try:
            listener.is_silence(_SILENCE)
            listener.is_silence(_SPEECH)
            self.assertEqual(vad.chunks_processed, 2)
        finally:
            listener.shutdown()

    def test_extract_speech_all_silent_returns_empty(self):
        """extract_speech on all-silent audio returns empty bytes."""
        vad = MockVADEngine()
        listener = MiniListener(_BASE_CONFIG, vad_instance=vad)
        try:
            result = listener.extract_speech(_SILENCE)
            self.assertEqual(result, b"")
        finally:
            listener.shutdown()

    def test_extract_speech_all_speech_unchanged(self):
        """extract_speech on all-speech audio returns unchanged bytes."""
        vad = MockVADEngine()
        listener = MiniListener(_BASE_CONFIG, vad_instance=vad)
        try:
            result = listener.extract_speech(_SPEECH)
            self.assertEqual(result, _SPEECH)
        finally:
            listener.shutdown()


# ---------------------------------------------------------------------------
# TestMiniListenerWakeWord
# ---------------------------------------------------------------------------

class TestMiniListenerWakeWord(unittest.TestCase):
    """MiniListener WakeWord integration tests."""

    def test_detect_wakeword_fires_at_threshold(self):
        """detect_wakeword() returns True when the engine fires."""
        ww = MockHotWordEngine(trigger_after=1)
        listener = MiniListener(
            _BASE_CONFIG, ww_instances={"hey_mycroft": ww}
        )
        try:
            self.assertTrue(listener.detect_wakeword(b"\x00" * 512))
        finally:
            listener.shutdown()

    def test_detect_wakeword_before_threshold_false(self):
        """detect_wakeword() returns False before threshold is reached."""
        ww = MockHotWordEngine(trigger_after=3)
        listener = MiniListener(
            _BASE_CONFIG, ww_instances={"hey_mycroft": ww}
        )
        try:
            self.assertFalse(listener.detect_wakeword(b"\x00" * 512))
            self.assertFalse(listener.detect_wakeword(b"\x00" * 512))
        finally:
            listener.shutdown()

    def test_detect_wakeword_no_engines_raises(self):
        """detect_wakeword() without engines raises RuntimeError."""
        listener = MiniListener(_BASE_CONFIG)
        try:
            with self.assertRaises(RuntimeError):
                listener.detect_wakeword(b"\x00" * 512)
        finally:
            listener.shutdown()

    def test_detect_wakeword_unknown_name_raises(self):
        """detect_wakeword(ww_name=…) for an unregistered name raises KeyError."""
        ww = MockHotWordEngine()
        listener = MiniListener(
            _BASE_CONFIG, ww_instances={"hey_mycroft": ww}
        )
        try:
            with self.assertRaises(KeyError):
                listener.detect_wakeword(b"\x00" * 512, ww_name="unknown_ww")
        finally:
            listener.shutdown()

    def test_scan_for_wakeword_detected(self):
        """scan_for_wakeword returns True and correct frame index."""
        ww = MockHotWordEngine(trigger_after=3)
        listener = MiniListener(
            _BASE_CONFIG, ww_instances={"hey_mycroft": ww}
        )
        try:
            found, frame = listener.scan_for_wakeword(
                [b"\x00" * 512] * 5
            )
            self.assertTrue(found)
            self.assertEqual(frame, 2)  # 0-indexed: fires on 3rd frame
        finally:
            listener.shutdown()

    def test_scan_for_wakeword_not_detected(self):
        """scan_for_wakeword returns False when threshold never reached."""
        ww = MockHotWordEngine(trigger_after=10)
        listener = MiniListener(
            _BASE_CONFIG, ww_instances={"hey_mycroft": ww}
        )
        try:
            found, frame = listener.scan_for_wakeword(
                [b"\x00" * 512] * 5
            )
            self.assertFalse(found)
            self.assertIsNone(frame)
        finally:
            listener.shutdown()

    def test_scan_for_wakeword_bytes_input(self):
        """scan_for_wakeword accepts flat bytes and splits by frame_size."""
        ww = MockHotWordEngine(trigger_after=2)
        listener = MiniListener(
            _BASE_CONFIG, ww_instances={"hey_mycroft": ww}
        )
        try:
            # 4 × 512-byte frames as flat bytes
            audio = b"\x00" * (512 * 4)
            found, frame = listener.scan_for_wakeword(audio, frame_size=512)
            self.assertTrue(found)
            self.assertEqual(frame, 1)  # fires on 2nd frame (index 1)
        finally:
            listener.shutdown()

    def test_scan_for_wakeword_no_engines_raises(self):
        """scan_for_wakeword without engines raises RuntimeError."""
        listener = MiniListener(_BASE_CONFIG)
        try:
            with self.assertRaises(RuntimeError):
                listener.scan_for_wakeword([b"\x00" * 512])
        finally:
            listener.shutdown()

    def test_factory_ww_instances(self):
        """get_mini_listener(ww_instances=…) wires engines correctly."""
        ww = MockHotWordEngine(trigger_after=1)
        listener = get_mini_listener(
            ww_instances={"hey_mycroft": ww}
        )
        try:
            self.assertTrue(listener.detect_wakeword(b"\x00" * 512))
        finally:
            listener.shutdown()


# ---------------------------------------------------------------------------
# TestVADTest
# ---------------------------------------------------------------------------

class TestVADTest(unittest.TestCase):
    """VADTest declarative helper tests."""

    def test_expect_silence_passes(self):
        """VADTest passes when expect_silence matches."""
        VADTest(
            vad_instance=MockVADEngine(),
            audio_input=_SILENCE,
            expect_silence=True,
        ).execute()

    def test_expect_not_silence_passes(self):
        """VADTest passes when expect_silence=False and chunk has speech."""
        VADTest(
            vad_instance=MockVADEngine(),
            audio_input=_SPEECH,
            expect_silence=False,
        ).execute()

    def test_expect_silence_fails_on_speech(self):
        """VADTest raises AssertionError when silence expected but not found."""
        with self.assertRaises(AssertionError):
            VADTest(
                vad_instance=MockVADEngine(),
                audio_input=_SPEECH,
                expect_silence=True,
            ).execute()

    def test_expect_speech_bytes(self):
        """VADTest asserts extract_speech output."""
        VADTest(
            vad_instance=MockVADEngine(),
            audio_input=_SPEECH,
            expect_speech_bytes=_SPEECH,
        ).execute()

    def test_no_vad_raises(self):
        """VADTest without vad_instance or vad_plugin raises RuntimeError."""
        with self.assertRaises(RuntimeError):
            VADTest(audio_input=_SILENCE).execute()


# ---------------------------------------------------------------------------
# TestWakeWordTest
# ---------------------------------------------------------------------------

class TestWakeWordTest(unittest.TestCase):
    """WakeWordTest declarative helper tests."""

    def test_expect_detected_passes(self):
        """WakeWordTest passes when wake word detected as expected."""
        WakeWordTest(
            ww_instances={"hey_mycroft": MockHotWordEngine(trigger_after=2)},
            audio_chunks=[b"\x00" * 512] * 4,
            expect_detected=True,
            expected_detection_frame=1,
        ).execute()

    def test_expect_not_detected_passes(self):
        """WakeWordTest passes when no detection is expected and none occurs."""
        WakeWordTest(
            ww_instances={"hey_mycroft": MockHotWordEngine(trigger_after=10)},
            audio_chunks=[b"\x00" * 512] * 5,
            expect_detected=False,
        ).execute()

    def test_expect_detected_fails_when_no_detection(self):
        """WakeWordTest raises AssertionError when detection expected but absent."""
        with self.assertRaises(AssertionError):
            WakeWordTest(
                ww_instances={"hey_mycroft": MockHotWordEngine(trigger_after=100)},
                audio_chunks=[b"\x00" * 512] * 5,
                expect_detected=True,
            ).execute()

    def test_expected_detection_frame_mismatch_raises(self):
        """WakeWordTest raises AssertionError on wrong detection frame."""
        with self.assertRaises(AssertionError):
            WakeWordTest(
                ww_instances={"hey_mycroft": MockHotWordEngine(trigger_after=2)},
                audio_chunks=[b"\x00" * 512] * 5,
                expect_detected=True,
                expected_detection_frame=0,  # wrong — actually fires at 1
            ).execute()

    def test_no_engines_raises(self):
        """WakeWordTest without ww_instances or ww_plugin raises RuntimeError."""
        with self.assertRaises(RuntimeError):
            WakeWordTest(audio_chunks=[b"\x00" * 512] * 3).execute()


if __name__ == "__main__":
    unittest.main()
