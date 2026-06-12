# Copyright 2024 OpenVoiceOS
# Licensed under the Apache License, Version 2.0
"""MiniClassicListener — drive mycroft-classic-listener for bus-sequence testing.

``mycroft-classic-listener`` is an alternative OVOS listener service built around
a ``RecognizerLoop`` (a ``pyee`` ``EventEmitter``) running an energy-based
``ResponsiveRecognizer`` across producer/consumer threads.  Its service layer
bridges the loop's internal events (``recognizer_loop:record_begin``,
``…:wakeword``, ``…:record_end``, ``…:utterance``,
``…:speech.recognition.unknown``) onto the OVOS messagebus.

Two pieces are provided:

* :func:`bridge_recognizer_loop_to_bus` — the reusable event→bus bridge (mirrors
  the classic listener's ``service.py``).  Wire any ``RecognizerLoop`` to a
  ``FakeBus`` and assert on the captured sequence.
* :class:`MiniClassicListener` — a best-effort, file-driven harness that injects
  a :class:`FileAudioSource` and mock wake-word/STT into a ``RecognizerLoop`` and
  runs it to completion, sharing the assertion helpers of
  :class:`ovoscope.voice_loop.ListenerHarness`.

The classic pipeline is energy-threshold based; the file drive is best-effort.
Use :func:`classic_listener_available` to gate tests on the environment.

Example — event bridge::

    from ovoscope.classic_listener import bridge_recognizer_loop_to_bus
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus()
    bridge_recognizer_loop_to_bus(loop, bus)  # loop = a RecognizerLoop
    # ... drive `loop` with real audio; assert on `bus`
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, List, Optional, Union

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovoscope.voice_loop import (
    ListenerHarness,
    MockHotWordEngine,
    MockStreamingSTT,
    _read_audio,
)


# ---------------------------------------------------------------------------
# Event → bus bridge (mirrors mycroft_classic_listener/service.py)
# ---------------------------------------------------------------------------

def bridge_recognizer_loop_to_bus(loop: Any, bus: FakeBus) -> Any:
    """Forward a ``RecognizerLoop``'s internal events onto a ``FakeBus``.

    Registers handlers on *loop* (any object with an ``on(event, handler)``
    EventEmitter API) that re-emit the listener events as bus :class:`Message`
    objects, exactly as the classic listener's service layer does.

    Args:
        loop: A ``RecognizerLoop`` (or compatible ``EventEmitter``).
        bus: The :class:`FakeBus` to emit translated messages on.

    Returns:
        *loop*, for chaining.
    """
    ctx = {"client_name": "mycroft_listener", "source": "audio"}

    loop.on(
        "recognizer_loop:record_begin",
        lambda *a: bus.emit(Message("recognizer_loop:record_begin", context=ctx)),
    )
    loop.on(
        "recognizer_loop:record_end",
        lambda *a: bus.emit(Message("recognizer_loop:record_end", context=ctx)),
    )
    loop.on(
        "recognizer_loop:wakeword",
        lambda event=None, *a: bus.emit(
            Message("recognizer_loop:wakeword", event or {})
        ),
    )
    loop.on(
        "recognizer_loop:utterance",
        lambda event=None, *a: bus.emit(Message(
            "recognizer_loop:utterance",
            event or {},
            {**ctx, "destination": ["skills"]},
        )),
    )
    loop.on(
        "recognizer_loop:speech.recognition.unknown",
        lambda *a: bus.emit(
            Message("recognizer_loop:speech.recognition.unknown", context=ctx)
        ),
    )
    loop.on(
        "recognizer_loop:awoken",
        lambda *a: bus.emit(Message("mycroft.awoken", context=ctx)),
    )
    return loop


# ---------------------------------------------------------------------------
# File-backed audio source (classic Microphone subclass)
# ---------------------------------------------------------------------------

class _FileStream:
    """Minimal stream serving file PCM then silence, frame by frame.

    Mirrors the read contract the classic ``ResponsiveRecognizer`` expects from
    a microphone stream: ``read(num_frames, of_exc)`` returns
    ``num_frames * sample_width`` bytes.

    Args:
        pcm: Raw PCM bytes of the audio.
        sample_width: Bytes per sample.
        tail_silence_bytes: Trailing silence appended after the audio.
    """

    def __init__(self, pcm: bytes, sample_width: int, tail_silence_bytes: int) -> None:
        self._data: bytes = pcm + (b"\x00" * tail_silence_bytes)
        self._sample_width: int = sample_width
        self._pos: int = 0

    def read(self, num_frames: int, of_exc: bool = False) -> bytes:
        """Return ``num_frames`` of audio, padding with silence past EOF."""
        nbytes = num_frames * self._sample_width
        chunk = self._data[self._pos:self._pos + nbytes]
        self._pos += len(chunk)
        if len(chunk) < nbytes:
            chunk = chunk + b"\x00" * (nbytes - len(chunk))
        return chunk

    def close(self) -> None:
        """No-op close."""

    def stop_stream(self) -> None:
        """No-op stop."""

    def is_stopped(self) -> bool:
        return False


def _make_file_audio_source(
    audio: Union[bytes, str, Path],
    chunk_size: int,
    tail_silence_seconds: float,
) -> Any:
    """Build a classic ``Microphone`` whose stream reads from *audio*.

    Bypasses ``Microphone.__init__`` (which opens PyAudio and needs a real input
    device) while still satisfying the ``isinstance(source, Microphone)`` check
    in ``ResponsiveRecognizer.listen``.
    """
    from mycroft_classic_listener.mic import Microphone

    pcm, sr, sw, _ch = _read_audio(audio, 16000, 2, 1)

    class FileAudioSource(Microphone):
        """File-backed classic microphone (no PyAudio)."""

        def __init__(self) -> None:
            self.device_index = None
            self.format = 8  # pyaudio.paInt16
            self.SAMPLE_WIDTH = sw
            self.SAMPLE_RATE = sr
            self.CHUNK = chunk_size
            self.muted = False
            self.audio = None
            self.stream = None
            self._pcm = pcm
            self._tail = int(tail_silence_seconds * sr * sw)

        def __enter__(self):
            self.stream = _FileStream(self._pcm, self.SAMPLE_WIDTH, self._tail)
            return self

        def __exit__(self, *_):
            self.stream = None

        def restart(self):
            self.stream = _FileStream(self._pcm, self.SAMPLE_WIDTH, self._tail)

        def duration_to_bytes(self, sec):
            return int(sec * self.SAMPLE_RATE * self.SAMPLE_WIDTH)

        def mute(self):
            self.muted = True

        def unmute(self):
            self.muted = False

        def is_muted(self):
            return self.muted

    return FileAudioSource()


def _build_recognizer_loop(file_source: Any, wakeword: Any, stt: Any) -> Any:
    """Build a ``RecognizerLoop`` with mocks injected, bypassing plugin/hardware.

    Subclasses ``RecognizerLoop`` to replace ``_load_config`` (which would open
    PyAudio and load real wake-word plugins) and ``start_async`` (which would
    create a real STT) with the injected file source, wake-word engine, and STT.
    """
    from mycroft_classic_listener.listener import (
        AudioConsumer,
        AudioProducer,
        RecognizerLoop,
        RecognizerLoopState,
        ResponsiveRecognizer,
    )
    try:
        from queue import Queue
    except ImportError:  # pragma: no cover
        from Queue import Queue  # type: ignore

    class _InjectedRecognizerLoop(RecognizerLoop):
        def __init__(self) -> None:
            super(RecognizerLoop, self).__init__()  # EventEmitter.__init__
            self._watchdog = lambda: None
            self.mute_calls = 0
            self.lang = "en-us"
            self.config = {}
            self.microphone = file_source
            self.wakeword_recognizer = wakeword
            self.wakeup_recognizer = MockHotWordEngine("wake_up", trigger_after=10**9)
            self.responsive_recognizer = ResponsiveRecognizer(
                self.wakeword_recognizer, self._watchdog
            )
            self.state = RecognizerLoopState()
            self._config_hash = None

        def start_async(self) -> None:
            self.state.running = True
            self.producer = AudioProducer(
                self.state, Queue(), self.microphone,
                self.responsive_recognizer, self, None,
            )
            # share one queue between producer and consumer
            queue = self.producer.queue
            self.producer.start()
            self.consumer = AudioConsumer(
                self.state, queue, self, stt,
                self.wakeup_recognizer, self.wakeword_recognizer,
            )
            self.consumer.start()

        def stop(self) -> None:
            self.state.running = False
            try:
                self.producer.stop()
                self.producer.join(timeout=2.0)
                self.consumer.join(timeout=2.0)
            except Exception:
                pass

    return _InjectedRecognizerLoop()


def classic_listener_available() -> bool:
    """Return ``True`` if mycroft-classic-listener can be imported here."""
    import importlib.util

    try:
        return all(
            importlib.util.find_spec(mod) is not None
            for mod in (
                "mycroft_classic_listener.listener",
                "mycroft_classic_listener.mic",
            )
        )
    except ModuleNotFoundError:
        return False


# ---------------------------------------------------------------------------
# MiniClassicListener
# ---------------------------------------------------------------------------

class MiniClassicListener(ListenerHarness):
    """Best-effort in-process mycroft-classic-listener harness.

    Wires a ``RecognizerLoop`` (built with a file audio source + mock wake-word /
    STT, or one supplied by the caller) to a ``FakeBus`` via
    :func:`bridge_recognizer_loop_to_bus`, then drives it over an audio file.

    Args:
        recognizer_loop: A pre-built ``RecognizerLoop`` (or compatible
            EventEmitter).  When provided, only the bus bridge is wired and the
            caller drives the loop; :meth:`feed_file` is unavailable.
        wakeword: Wake-word engine for the built loop (defaults to a
            :class:`MockHotWordEngine`).
        stt_instance: STT engine for the built loop (defaults to
            :class:`MockStreamingSTT`).
        bus: Optional :class:`FakeBus` to capture on.

    Raises:
        RuntimeError: If *recognizer_loop* is ``None`` and
            mycroft-classic-listener is not importable.
    """

    def __init__(
        self,
        recognizer_loop: Optional[Any] = None,
        *,
        wakeword: Optional[Any] = None,
        stt_instance: Optional[Any] = None,
        bus: Optional[FakeBus] = None,
    ) -> None:
        super().__init__(bus)
        self._built = recognizer_loop is None
        self._wakeword = wakeword
        self._stt = stt_instance

        if recognizer_loop is not None:
            self.loop: Any = recognizer_loop
            bridge_recognizer_loop_to_bus(self.loop, self.bus)
        else:
            if not classic_listener_available():
                raise RuntimeError(
                    "mycroft-classic-listener is required to build a "
                    "MiniClassicListener. Install it with: "
                    "pip install mycroft-classic-listener"
                )
            self.loop = None  # built per-run in feed_file (needs the audio)

    def feed_file(
        self,
        audio: Union[bytes, str, Path],
        *,
        tail_silence_seconds: float = 2.0,
        chunk_size: int = 1024,
        timeout: float = 15.0,
    ) -> List[Message]:
        """Run the classic loop over an audio file and capture bus events.

        Builds a fresh ``RecognizerLoop`` with a :class:`FileAudioSource`, bridges
        it to the bus, runs it until a command finishes
        (``recognizer_loop:record_end``) or *timeout* elapses, then stops it.

        Args:
            audio: Path to a ``.wav`` file, WAV bytes, or raw PCM bytes.
            tail_silence_seconds: Trailing silence appended after the audio so
                the energy recogniser can end the command.
            chunk_size: Frames per microphone read.
            timeout: Maximum seconds to wait for the command to finish.

        Returns:
            The list of :class:`Message` objects emitted during the run.

        Raises:
            RuntimeError: If this harness was constructed with an external loop.
        """
        if not self._built:
            raise RuntimeError(
                "feed_file is only available when MiniClassicListener builds the "
                "RecognizerLoop. Drive the supplied loop yourself and assert on "
                ".bus instead."
            )

        wakeword = self._wakeword or MockHotWordEngine("hey_mycroft", trigger_after=1)
        stt = self._stt or MockStreamingSTT()
        source = _make_file_audio_source(audio, chunk_size, tail_silence_seconds)

        self.loop = _build_recognizer_loop(source, wakeword, stt)
        bridge_recognizer_loop_to_bus(self.loop, self.bus)

        self._messages.clear()
        self.loop.start_async()
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._has(self._messages, "recognizer_loop:record_end"):
                    break
                time.sleep(0.02)
        finally:
            self.loop.stop()

        self._last_messages = list(self._messages)
        return list(self._messages)

    def shutdown(self) -> None:
        """Stop the loop if the harness owns it."""
        if self._built and self.loop is not None:
            try:
                self.loop.stop()
            except Exception:
                pass
