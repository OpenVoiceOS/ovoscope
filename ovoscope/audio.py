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

"""Audio testing harnesses for ovoscope.

Provides mock implementations of AudioBackend and TTS, plus context-manager
harnesses that wire them into AudioService and PlaybackService running on a
FakeBus — enabling fast, dependency-free end-to-end audio service tests.

Classes:
    MockAudioBackend   -- no-op AudioBackend that tracks state
    AudioServiceHarness -- context manager wrapping AudioService + MockAudioBackend
    MockTTS            -- no-op TTS that records spoken utterances
    PlaybackServiceHarness -- context manager wrapping PlaybackService + MockTTS
    AudioCaptureSession -- records bus messages matching given prefixes
"""

import dataclasses
import struct
import threading
import time
from contextlib import contextmanager
from typing import ClassVar, Dict, Generator, List, Optional, Tuple
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_plugin_manager.templates.tts import TTS
from ovos_utils.fakebus import FakeBus


# ---------------------------------------------------------------------------
# MockAudioBackend
# ---------------------------------------------------------------------------

class MockAudioBackend(AudioBackend):
    """A no-op AudioBackend that records all state transitions for assertion.

    No actual audio is played. Every mutating method updates simple Python
    attributes so tests can inspect them without Mocks.

    Args:
        config: Backend configuration dict (may be empty).
        bus: FakeBus instance shared with the service under test.
        name: Logical name of the backend (used by AudioService.find_default).
    """

    def __init__(self, config: dict, bus: FakeBus, name: str = "mock") -> None:
        """Initialise the backend with clean state.

        Args:
            config: Configuration dict, forwarded to AudioBackend.__init__.
            bus: FakeBus used by the enclosing AudioService.
            name: Backend name that AudioService will use for selection.
        """
        super().__init__(config=config, bus=bus)
        self.name: str = name
        self.played_tracks: List[str] = []
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.current_track: Optional[str] = None
        self.lower_volume_calls: int = 0
        self.restore_volume_calls: int = 0

    # ------------------------------------------------------------------
    # AudioBackend abstract interface
    # ------------------------------------------------------------------

    def supported_uris(self) -> List[str]:
        """Return URI schemes supported by this backend.

        Returns:
            List of scheme strings, e.g. ``["file", "http", "https"]``.
        """
        return ["file", "http", "https"]

    def add_list(self, playlist: List[str]) -> None:
        """Record tracks in the playlist and set current_track.

        Args:
            playlist: List of track URIs to add.
        """
        self.played_tracks.extend(playlist)
        if playlist:
            self.current_track = playlist[0]

    def clear_list(self) -> None:
        """Clear the recorded playlist."""
        self.played_tracks.clear()
        self.current_track = None

    def play(self, repeat: bool = False) -> None:
        """Mark the backend as playing.

        Args:
            repeat: Whether to loop the playlist (not implemented).
        """
        self.is_playing = True
        self.is_paused = False

    def stop(self) -> bool:
        """Stop playback.

        Returns:
            True — AudioService._perform_stop() calls ``if self.current.stop()``
            so returning False would suppress the stop-handled bus message.
        """
        self.is_playing = False
        self.is_paused = False
        return True

    def pause(self) -> None:
        """Pause playback."""
        self.is_paused = True

    def resume(self) -> None:
        """Resume paused playback."""
        self.is_paused = False

    def next(self) -> None:
        """Skip to next track (no-op)."""

    def previous(self) -> None:
        """Skip to previous track (no-op)."""

    def lower_volume(self) -> None:
        """Duck volume (increments counter for assertions)."""
        self.lower_volume_calls += 1

    def restore_volume(self) -> None:
        """Restore ducked volume (increments counter for assertions)."""
        self.restore_volume_calls += 1

    def track_info(self) -> Dict[str, Optional[str]]:
        """Return info about the current track.

        Returns:
            Dict with ``"track"`` key containing current_track URI.
        """
        return {"track": self.current_track}

    def shutdown(self) -> None:
        """Shut down the backend (no-op)."""

    def get_track_length(self) -> int:
        """Return track duration in milliseconds.

        Returns:
            Always 0 — mock backend has no real audio.
        """
        return 0

    def get_track_position(self) -> int:
        """Return current playback position in milliseconds.

        Returns:
            Always 0 — mock backend has no real audio.
        """
        return 0

    def set_track_position(self, milliseconds: int) -> None:
        """Seek to position (no-op).

        Args:
            milliseconds: Target position in ms.
        """

    def seek_forward(self, seconds: int = 1) -> None:
        """Seek forward (no-op).

        Args:
            seconds: Number of seconds to seek forward.
        """

    def seek_backward(self, seconds: int = 1) -> None:
        """Seek backward (no-op).

        Args:
            seconds: Number of seconds to seek backward.
        """

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all recorded state back to initial values."""
        self.played_tracks.clear()
        self.is_playing = False
        self.is_paused = False
        self.current_track = None
        self.lower_volume_calls = 0
        self.restore_volume_calls = 0


# ---------------------------------------------------------------------------
# AudioServiceHarness
# ---------------------------------------------------------------------------

class AudioServiceHarness:
    """Context manager that runs AudioService on a FakeBus with MockAudioBackend.

    Usage::

        with AudioServiceHarness() as harness:
            harness.play(["http://example.com/song.mp3"])
            assert harness.backend.is_playing

    The harness uses ``autoload=False`` to prevent real plugin discovery, then
    manually injects the ``MockAudioBackend`` and calls ``load_services()`` with
    all external calls patched out.

    Args:
        backend_name: Name to register the mock backend under.
        validate_source: Passed to AudioService; set True to enable session checks.
        disable_ocp: Passed to AudioService; True disables OCP plugin loading.
    """

    def __init__(self, backend_name: str = "mock",
                 validate_source: bool = False,
                 disable_ocp: bool = True) -> None:
        """Initialise harness parameters.

        Args:
            backend_name: Name for the MockAudioBackend instance.
            validate_source: Enable source-session validation in AudioService.
            disable_ocp: Disable OCP plugin during tests.
        """
        self.backend_name: str = backend_name
        self.validate_source: bool = validate_source
        self.disable_ocp: bool = disable_ocp
        self.bus: Optional[FakeBus] = None
        self.service = None  # AudioService instance
        self.backend: Optional[MockAudioBackend] = None

    def __enter__(self) -> "AudioServiceHarness":
        """Start AudioService and inject MockAudioBackend.

        Returns:
            self
        """
        from ovos_audio.audio import AudioService

        self.bus = FakeBus()
        self.backend = MockAudioBackend(config={}, bus=self.bus,
                                        name=self.backend_name)

        # Create AudioService without autoload so no real plugins are discovered
        self.service = AudioService(self.bus, autoload=False,
                                    disable_ocp=self.disable_ocp,
                                    validate_source=self.validate_source)

        # Inject our mock backend as the only service and set it as default
        self.service.service = [self.backend]
        self.service.default = self.backend
        self.backend.set_track_start_callback(self.service.track_start)

        # Register bus event handlers (normally done inside load_services)
        self.bus.on("mycroft.audio.service.play", self.service._play)
        self.bus.on("mycroft.audio.service.queue", self.service._queue)
        self.bus.on("mycroft.audio.service.pause", self.service._pause)
        self.bus.on("mycroft.audio.service.resume", self.service._resume)
        self.bus.on("mycroft.audio.service.stop", self.service._stop)
        self.bus.on("mycroft.audio.service.next", self.service._next)
        self.bus.on("mycroft.audio.service.prev", self.service._prev)
        self.bus.on("mycroft.audio.service.track_info", self.service._track_info)
        self.bus.on("mycroft.audio.service.list_backends", self.service._list_backends)
        self.bus.on("mycroft.audio.service.set_track_position",
                    self.service._set_track_position)
        self.bus.on("mycroft.audio.service.get_track_position",
                    self.service._get_track_position)
        self.bus.on("mycroft.audio.service.get_track_length",
                    self.service._get_track_length)
        self.bus.on("mycroft.audio.service.seek_forward", self.service._seek_forward)
        self.bus.on("mycroft.audio.service.seek_backward", self.service._seek_backward)
        self.bus.on("recognizer_loop:audio_output_start",
                    self.service._lower_volume_on_speak)
        self.bus.on("recognizer_loop:audio_output_end",
                    self.service._restore_volume_on_speak)
        self.bus.on("recognizer_loop:record_begin",
                    self.service._lower_volume_on_record)
        self.bus.on("recognizer_loop:record_end",
                    self.service._restore_volume_after_record)
        self.bus.on("ovos.utterance.handled",
                    self.service._restore_volume_on_handled)
        self.service._loaded.set()

        return self

    def __exit__(self, *args) -> None:
        """Shut down AudioService and close the bus."""
        if self.service:
            self.service.shutdown()
        if self.bus:
            self.bus.close()

    # ------------------------------------------------------------------
    # Control methods
    # ------------------------------------------------------------------

    def play(self, tracks: List[str], backend: Optional[str] = None,
             repeat: bool = False) -> None:
        """Emit mycroft.audio.service.play and wait briefly for processing.

        Args:
            tracks: List of track URIs to play.
            backend: Optional preferred backend name.
            repeat: Whether to repeat the playlist.
        """
        data: Dict = {"tracks": tracks, "repeat": repeat}
        if backend:
            data["utterance"] = backend
        self.bus.emit(Message("mycroft.audio.service.play", data))
        time.sleep(0.05)

    def pause(self) -> None:
        """Emit mycroft.audio.service.pause."""
        self.bus.emit(Message("mycroft.audio.service.pause"))
        time.sleep(0.05)

    def resume(self) -> None:
        """Emit mycroft.audio.service.resume."""
        self.bus.emit(Message("mycroft.audio.service.resume"))
        time.sleep(0.05)

    def stop(self) -> None:
        """Emit mycroft.audio.service.stop and wait for processing."""
        self.bus.emit(Message("mycroft.audio.service.stop"))
        time.sleep(0.05)

    def queue(self, tracks: List[str]) -> None:
        """Emit mycroft.audio.service.queue.

        Args:
            tracks: List of track URIs to queue.
        """
        self.bus.emit(Message("mycroft.audio.service.queue", {"tracks": tracks}))
        time.sleep(0.05)

    def get_track_info(self, timeout: float = 2.0) -> Optional[Dict]:
        """Request track info via bus and return the response data.

        Uses a threading.Event to capture the synchronous in-process reply
        because FakeBus.wait_for_response does not work for in-process handlers.

        Args:
            timeout: Seconds to wait for the reply.

        Returns:
            Track info dict or None if no response within timeout.
        """
        result: Dict = {}
        done = threading.Event()

        def _on_reply(msg: Message) -> None:
            result.update(msg.data)
            done.set()

        self.bus.on("mycroft.audio.service.track_info_reply", _on_reply)
        try:
            self.bus.emit(Message("mycroft.audio.service.track_info"))
            done.wait(timeout)
        finally:
            self.bus.remove("mycroft.audio.service.track_info_reply", _on_reply)
        return result if done.is_set() else None

    def list_backends(self, timeout: float = 2.0) -> Optional[Dict]:
        """Request backend list via bus and return the response data.

        Uses a threading.Event to capture the synchronous in-process reply.

        Args:
            timeout: Seconds to wait for the reply.

        Returns:
            Dict mapping backend names to info dicts, or None on timeout.
        """
        result: Dict = {}
        done = threading.Event()

        def _on_reply(msg: Message) -> None:
            result.update(msg.data)
            done.set()

        reply_type = "mycroft.audio.service.list_backends.response"
        self.bus.on(reply_type, _on_reply)
        try:
            self.bus.emit(Message("mycroft.audio.service.list_backends"))
            done.wait(timeout)
        finally:
            self.bus.remove(reply_type, _on_reply)
        return result if done.is_set() else None

    # ------------------------------------------------------------------
    # Assertion helpers
    # ------------------------------------------------------------------

    def assert_playing(self) -> None:
        """Assert the mock backend is currently in playing state."""
        assert self.backend.is_playing, "Expected backend to be playing"

    def assert_paused(self) -> None:
        """Assert the mock backend is currently paused."""
        assert self.backend.is_paused, "Expected backend to be paused"

    def assert_stopped(self) -> None:
        """Assert the mock backend is neither playing nor paused."""
        assert not self.backend.is_playing, "Expected backend to be stopped (is_playing=True)"
        assert not self.backend.is_paused, "Expected backend to be stopped (is_paused=True)"

    def assert_volume_lowered(self) -> None:
        """Assert lower_volume was called at least once."""
        assert self.backend.lower_volume_calls > 0, \
            f"Expected lower_volume to be called, got {self.backend.lower_volume_calls}"

    def assert_volume_restored(self) -> None:
        """Assert restore_volume was called at least once."""
        assert self.backend.restore_volume_calls > 0, \
            f"Expected restore_volume to be called, got {self.backend.restore_volume_calls}"


# ---------------------------------------------------------------------------
# MockTTS
# ---------------------------------------------------------------------------

# 44-byte minimal valid WAV: RIFF header + fmt chunk + empty data chunk
_WAV_RIFF = b"RIFF"
_WAV_SIZE = struct.pack("<I", 36)          # file size - 8
_WAV_WAVE = b"WAVE"
_WAV_FMT  = b"fmt "
_WAV_FMTSZ = struct.pack("<I", 16)         # PCM fmt chunk size
_WAV_PCMTYPE = struct.pack("<H", 1)        # PCM = 1
_WAV_CHANNELS = struct.pack("<H", 1)       # mono
_WAV_SAMPLERATE = struct.pack("<I", 16000) # 16 kHz
_WAV_BYTERATE = struct.pack("<I", 32000)   # 16000 * 1 * 2
_WAV_BLOCKALIGN = struct.pack("<H", 2)     # 1 channel * 2 bytes
_WAV_BITSPERSAMPLE = struct.pack("<H", 16) # 16-bit
_WAV_DATA = b"data"
_WAV_DATASZ = struct.pack("<I", 0)         # 0 samples

SILENT_WAV: bytes = (
    _WAV_RIFF + _WAV_SIZE + _WAV_WAVE
    + _WAV_FMT + _WAV_FMTSZ + _WAV_PCMTYPE + _WAV_CHANNELS
    + _WAV_SAMPLERATE + _WAV_BYTERATE + _WAV_BLOCKALIGN + _WAV_BITSPERSAMPLE
    + _WAV_DATA + _WAV_DATASZ
)


class MockTTS(TTS):
    """A no-op TTS that writes a silent WAV and records spoken utterances.

    Designed to be injected into PlaybackService via ``tts=MockTTS()`` so
    that no real speech synthesis occurs during tests.

    Attributes:
        spoken_utterances: Accumulates every sentence passed to ``get_tts``.
    """

    SILENT_WAV: ClassVar[bytes] = SILENT_WAV

    def __init__(self, config: Optional[dict] = None) -> None:
        """Initialise the mock TTS engine.

        Args:
            config: Optional configuration dict; defaults to empty.
        """
        super().__init__(config=config or {})
        self.spoken_utterances: List[str] = []

    def get_tts(self, sentence: str, wav_file: str,
                lang: Optional[str] = None,
                voice: Optional[str] = None) -> Tuple[str, None]:
        """Synthesise speech as a silent WAV and record the sentence.

        Args:
            sentence: The text to synthesise.
            wav_file: Path where the WAV file should be written.
            lang: Language tag (ignored in mock).
            voice: Voice selection (ignored in mock).

        Returns:
            Tuple of ``(wav_file, None)`` — phoneme data is not produced.
        """
        with open(wav_file, "wb") as fh:
            fh.write(self.SILENT_WAV)
        self.spoken_utterances.append(sentence)
        return wav_file, None

    def reset(self) -> None:
        """Clear the list of recorded spoken utterances."""
        self.spoken_utterances.clear()


# ---------------------------------------------------------------------------
# PlaybackServiceHarness
# ---------------------------------------------------------------------------

class PlaybackServiceHarness:
    """Context manager wrapping PlaybackService with a MockTTS on a FakeBus.

    PlaybackService is a ``Thread``; this harness starts it and wires it to the
    provided FakeBus so tests can emit ``speak`` messages and observe the
    resulting ``recognizer_loop:audio_output_start/end`` events.

    The harness patches ``ovos_utils.sound.play_audio`` so no actual audio
    device is accessed. It also drains ``TTS.queue`` before construction to
    prevent state bleed between tests.

    Args:
        validate_source: Enable session-source validation in the service.
        disable_ocp: Disable legacy OCP in the encapsulated AudioService.
    """

    def __init__(self, validate_source: bool = False,
                 disable_ocp: bool = True) -> None:
        """Initialise harness parameters.

        Args:
            validate_source: Enable session-source validation.
            disable_ocp: Disable OCP audio plugin.
        """
        self.validate_source: bool = validate_source
        self.disable_ocp: bool = disable_ocp
        self.bus: Optional[FakeBus] = None
        self.svc = None  # PlaybackService instance
        self.mock_tts: Optional[MockTTS] = None
        self._play_audio_patcher = None
        self._audio_enabled_patcher = None
        self._audio_output_start = threading.Event()
        self._audio_output_end = threading.Event()
        self._mic_listen = threading.Event()

    def __enter__(self) -> "PlaybackServiceHarness":
        """Construct and start PlaybackService with MockTTS.

        Returns:
            self
        """
        from ovos_audio.service import PlaybackService
        from queue import Queue

        # Drain any leftover TTS queue from previous tests (class-level state)
        if TTS.queue is not None:
            while not TTS.queue.empty():
                try:
                    TTS.queue.get_nowait()
                except Exception:
                    break
        TTS.queue = Queue()

        self.bus = FakeBus()
        self.mock_tts = MockTTS()

        # Patch play_audio so no real audio device is accessed
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.wait.return_value = 0

        self._play_audio_patcher = patch(
            "ovos_audio.playback.play_audio", return_value=mock_proc
        )
        self._play_audio_patcher.start()

        try:
            # Build the service — passing tts= sets disable_reload = True
            self.svc = PlaybackService(
                bus=self.bus,
                tts=self.mock_tts,
                disable_ocp=self.disable_ocp,
                validate_source=self.validate_source,
            )
            # Wire mock_tts to the playback thread created by PlaybackService
            self.mock_tts.init(self.bus, self.svc.playback_thread)

            # Subscribe lifecycle events for synchronisation
            self.bus.on("recognizer_loop:audio_output_start",
                        lambda m: self._audio_output_start.set())
            self.bus.on("recognizer_loop:audio_output_end",
                        lambda m: self._audio_output_end.set())
            self.bus.on("mycroft.mic.listen",
                        lambda m: self._mic_listen.set())

        except Exception:
            if self.svc:
                try:
                    self.svc.shutdown()
                except Exception:
                    pass
            self._play_audio_patcher.stop()
            self.bus.close()
            raise

        return self

    def __exit__(self, *args) -> None:
        """Shut down PlaybackService and stop patches."""
        if self.svc:
            try:
                self.svc.shutdown()
            except Exception:
                pass
        if self._play_audio_patcher:
            try:
                self._play_audio_patcher.stop()
            except Exception:
                pass
        if self.bus:
            try:
                self.bus.close()
            except Exception:
                pass
    # ------------------------------------------------------------------
    # Control methods
    # ------------------------------------------------------------------

    def speak(self, utterance: str, expect_response: bool = False,
              timeout: float = 10.0) -> None:
        """Emit a ``speak`` message and wait for audio_output_end.

        Args:
            utterance: The text to speak.
            expect_response: If True, expect microphone listen after speech.
            timeout: Maximum seconds to wait for playback to finish.

        Raises:
            TimeoutError: If speech playback does not finish within timeout.
        """
        # Clear events BEFORE emitting the message
        self._audio_output_start.clear()
        self._audio_output_end.clear()
        self._mic_listen.clear()

        self.bus.emit(Message("speak", {
            "utterance": utterance,
            "lang": "en-US",
            "expect_response": expect_response,
        }))

        if not self._audio_output_end.wait(timeout):
            raise TimeoutError(
                f"Speech playback for '{utterance}' did not finish within {timeout}s"
            )

    def stop(self) -> None:
        """Emit mycroft.stop to halt TTS playback."""
        self.bus.emit(Message("mycroft.stop"))
        time.sleep(0.1)

    # ------------------------------------------------------------------
    # Assertion helpers
    # ------------------------------------------------------------------

    def assert_spoke(self, text: str) -> None:
        """Assert that the given text was synthesised by MockTTS.

        Args:
            text: The expected utterance string.
        """
        assert text in self.mock_tts.spoken_utterances, (
            f"Expected '{text}' in spoken_utterances, "
            f"got: {self.mock_tts.spoken_utterances}"
        )

    def assert_audio_output_started(self, timeout: float = 3.0) -> None:
        """Assert that recognizer_loop:audio_output_start was emitted.

        Args:
            timeout: Seconds to wait for the event.
        """
        assert self._audio_output_start.wait(timeout), \
            "recognizer_loop:audio_output_start was not emitted"

    def assert_audio_output_ended(self, timeout: float = 3.0) -> None:
        """Assert that recognizer_loop:audio_output_end was emitted.

        Args:
            timeout: Seconds to wait for the event.
        """
        assert self._audio_output_end.wait(timeout), \
            "recognizer_loop:audio_output_end was not emitted"

    def assert_mic_listen(self, timeout: float = 3.0) -> None:
        """Assert that mycroft.mic.listen was emitted after speech.

        Args:
            timeout: Seconds to wait for the event.
        """
        assert self._mic_listen.wait(timeout), \
            "mycroft.mic.listen was not emitted"


# ---------------------------------------------------------------------------
# AudioCaptureSession
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class AudioCaptureSession:
    """Records bus messages whose types match given prefixes.

    Designed as a lightweight companion to AudioServiceHarness and
    PlaybackServiceHarness for asserting that specific message sequences
    were emitted during an audio interaction.

    Args:
        bus: The FakeBus to subscribe to.
        track_prefixes: Message-type prefix strings to capture.

    Attributes:
        messages: All captured Message objects in emission order.
    """

    bus: FakeBus
    track_prefixes: List[str] = dataclasses.field(default_factory=lambda: [
        "mycroft.audio.",
        "recognizer_loop:audio_output",
        "mycroft.mic.listen",
    ])
    messages: List[Message] = dataclasses.field(default_factory=list)

    def _handle(self, msg: str) -> None:
        """Internal handler subscribed to the raw 'message' event.

        Args:
            msg: Serialized message string from FakeBus.
        """
        m = Message.deserialize(msg)
        for prefix in self.track_prefixes:
            if m.msg_type.startswith(prefix):
                self.messages.append(m)
                break

    def start(self) -> None:
        """Begin capturing messages."""
        self.messages.clear()
        self.bus.on("message", self._handle)

    def stop(self) -> None:
        """Stop capturing messages."""
        self.bus.remove("message", self._handle)

    def __enter__(self) -> "AudioCaptureSession":
        """Start capturing on context entry.

        Returns:
            self
        """
        self.start()
        return self

    def __exit__(self, *args) -> None:
        """Stop capturing on context exit."""
        self.stop()

    @property
    def message_types(self) -> List[str]:
        """Return the list of captured message type strings.

        Returns:
            List of msg_type strings in the order they were received.
        """
        return [m.msg_type for m in self.messages]

    def assert_sequence(self, *types: str) -> None:
        """Assert that captured messages contain all given types in order.

        Args:
            *types: Expected message type strings (subsequence check).

        Raises:
            AssertionError: If any type is missing or order is violated.
        """
        received = self.message_types
        pos = 0
        for t in types:
            found = False
            while pos < len(received):
                if received[pos] == t:
                    pos += 1
                    found = True
                    break
                pos += 1
            assert found, (
                f"Expected message '{t}' not found in sequence after position. "
                f"Full captured sequence: {received}"
            )
