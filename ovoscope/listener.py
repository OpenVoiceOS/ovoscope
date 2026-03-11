# Copyright 2024 OpenVoiceOS
# Licensed under the Apache License, Version 2.0
"""MiniListener — in-process listener pipeline for ovoscope.

Wraps ``AudioTransformersService`` (and optionally an STT plugin) on a
``FakeBus`` so that the full listener pipeline can be tested end-to-end
without a real microphone or a running ``ovos-dinkum-listener`` process.

Two usage patterns are supported:

**1. Audio transformer testing** (e.g. ggwave) — feed raw audio chunks and
assert on the bus messages emitted by the transformer plugins::

    from ovoscope.listener import get_mini_listener
    from ovos_audio_transformer_plugin_ggwave import GGWavePlugin
    from unittest.mock import MagicMock, patch
    import ggwave

    with patch.object(ggwave, "decode", MagicMock(return_value=b"UTT:turn on the lights")):
        plugin = GGWavePlugin(config={"start_enabled": True})
        listener = get_mini_listener(
            plugin_instances={"ovos-audio-transformer-plugin-ggwave": plugin}
        )
        msgs = listener.feed_audio(b"\\x00" * 1024)
        assert any(m.msg_type == "recognizer_loop:utterance" for m in msgs)
        listener.shutdown()

**2. Full pipeline testing** (audio transformers → STT) — feed a real WAV
file and assert that a ``recognizer_loop:utterance`` is emitted::

    from ovoscope.listener import get_mini_listener
    from unittest.mock import MagicMock

    stt = MagicMock()
    stt.execute.return_value = "ask not what your country can do for you"

    listener = get_mini_listener(stt_instance=stt)
    msgs = listener.listen("path/to/jfk.wav", language="en-us")
    assert any(m.msg_type == "recognizer_loop:utterance" for m in msgs)
    listener.shutdown()
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _wav_to_audio_data(audio: Union[bytes, str, Path],
                       sample_rate: int = 16000,
                       sample_width: int = 2) -> Any:
    """Convert WAV bytes or a WAV file path to an ``AudioData`` object.

    Uses ``AudioData.from_file()`` — `ovos_plugin_manager/utils/audio.py:34`
    — when a file path is given, which handles WAV/AIFF/FLAC automatically.

    For raw bytes, parses the WAV header via the ``wave`` stdlib module to
    extract sample_rate and sample_width.

    Args:
        audio: Raw WAV bytes **or** a path to a WAV/AIFF/FLAC file.
        sample_rate: Fallback sample rate when the WAV header cannot be parsed.
        sample_width: Fallback sample width (bytes) when header cannot be
            parsed.

    Returns:
        ``AudioData(frame_data, sample_rate, sample_width)``
    """
    from ovos_plugin_manager.utils.audio import AudioData

    if isinstance(audio, (str, Path)):
        return AudioData.from_file(str(audio))

    # bytes path: parse WAV header to get sample_rate / sample_width
    try:
        with wave.open(io.BytesIO(audio)) as wf:
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            frame_data = wf.readframes(wf.getnframes())
    except Exception:
        # Not a WAV file or corrupt header — treat as raw PCM
        frame_data = audio

    return AudioData(frame_data, sample_rate, sample_width)


class MiniListener:
    """In-process listener pipeline for integration testing.

    Wraps ``AudioTransformersService`` — `ovos_dinkum_listener/transformers.py` —
    on a ``FakeBus`` so transformer plugins and the STT plugin can be exercised
    without real hardware or a running ``ovos-dinkum-listener`` process.

    All ``Message`` objects emitted on the bus during any feed / transform /
    listen call are captured and returned.

    Args:
        config: Full OVOS config dict. Must contain at minimum::

            {"listener": {"audio_transformers": {}}}

        plugin_instances: Optional mapping of plugin name → already-instantiated
            audio transformer plugin object.  Each plugin will be bound to the
            internal FakeBus and injected into the ``AudioTransformersService``.
        stt_instance: Optional STT plugin object with an
            ``execute(audio_data, language) -> str`` method. Stored as the
            default STT provider for ``listen()``.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        plugin_instances: Optional[Dict[str, Any]] = None,
        stt_instance: Optional[Any] = None,
    ) -> None:
        self.bus: FakeBus = FakeBus()
        self._messages: List[Message] = []
        self._stt_instance: Optional[Any] = stt_instance

        # Capture every message emitted on the bus.
        def _capture(msg: Any) -> None:
            if isinstance(msg, str):
                try:
                    msg = Message.deserialize(msg)
                except Exception:
                    return
            self._messages.append(msg)

        self.bus.on("message", _capture)

        from ovos_dinkum_listener.transformers import AudioTransformersService

        self.transformers: AudioTransformersService = AudioTransformersService(
            self.bus, config
        )

        # Inject pre-instantiated plugins directly, bypassing OPM discovery.
        if plugin_instances:
            for name, plugin in plugin_instances.items():
                plugin.bind(self.bus)
                self.transformers.loaded_plugins[name] = plugin

    # ------------------------------------------------------------------
    # Audio feed methods
    # ------------------------------------------------------------------

    def feed_audio(self, chunk: bytes) -> List[Message]:
        """Feed non-speech audio to all loaded plugins; return emitted messages.

        Calls ``AudioTransformersService.feed_audio()`` —
        `ovos_dinkum_listener/transformers.py:84` — which in turn calls
        ``feed_audio_chunk()`` on every loaded plugin.

        Args:
            chunk: Raw PCM bytes (content does not matter for tests that mock
                the codec).

        Returns:
            List of ``Message`` objects emitted on the bus during this call.
        """
        self._messages.clear()
        self.transformers.feed_audio(chunk)
        return list(self._messages)

    def feed_speech(self, chunk: bytes) -> List[Message]:
        """Feed speech audio to all loaded plugins; return emitted messages.

        Calls ``AudioTransformersService.feed_speech()`` —
        `ovos_dinkum_listener/transformers.py:100`.

        Args:
            chunk: Raw PCM bytes.

        Returns:
            List of ``Message`` objects emitted on the bus during this call.
        """
        self._messages.clear()
        self.transformers.feed_speech(chunk)
        return list(self._messages)

    def transform(self, chunk: bytes) -> tuple[bytes, dict, List[Message]]:
        """Run the full transform pipeline; return audio, context, and messages.

        Calls ``AudioTransformersService.transform()`` —
        `ovos_dinkum_listener/transformers.py:111`.

        Args:
            chunk: Raw PCM bytes to transform.

        Returns:
            Tuple of ``(transformed_audio, context_dict, emitted_messages)``.
        """
        self._messages.clear()
        audio, ctx = self.transformers.transform(chunk)
        return audio, ctx, list(self._messages)

    def listen(
        self,
        audio: Union[bytes, str, Path],
        language: str = "en-us",
        stt_instance: Optional[Any] = None,
        sample_rate: int = 16000,
        sample_width: int = 2,
    ) -> List[Message]:
        """Full pipeline: audio → transformers → STT → ``recognizer_loop:utterance``.

        This is the primary method for end-to-end listener pipeline tests.
        Feed a real WAV file (or raw PCM bytes), run it through the loaded
        audio transformer plugins, then optionally through an STT plugin.
        If the STT plugin returns a non-empty transcript, a
        ``recognizer_loop:utterance`` message is emitted on the FakeBus.

        The complete sequence::

            audio bytes / WAV file
              │
              ▼ AudioTransformersService.transform()
            transformed audio + context
              │
              ▼ stt_instance.execute(AudioData, language)   [if provided]
            transcript string
              │
              ▼ bus.emit("recognizer_loop:utterance")       [if non-empty]
              │
              ▼ captured messages

        Args:
            audio: Raw WAV/PCM bytes **or** a path to a ``.wav`` file.
                The WAV header is parsed automatically to extract sample_rate
                and sample_width.
            language: BCP-47 language code forwarded to the STT plugin and
                embedded in the emitted utterance message.
            stt_instance: Optional STT plugin object with an
                ``execute(audio_data, language) -> str`` method.  When
                provided, ``AudioData`` is built from the (transformed) audio
                and passed to the plugin.  If ``None``, the ``stt_instance``
                passed to the constructor is used. If both are ``None``, no
                STT step is performed.
            sample_rate: Fallback sample rate used when *audio* is raw PCM
                (i.e. has no WAV header).
            sample_width: Fallback sample width in bytes when *audio* is raw
                PCM.

        Returns:
            All ``Message`` objects emitted on the FakeBus during this call,
            including any messages from transformer plugins **and** the
            ``recognizer_loop:utterance`` from the STT step.

        Example::

            from ovoscope.listener import get_mini_listener
            from unittest.mock import MagicMock

            stt = MagicMock()
            stt.execute.return_value = "ask not what your country can do for you"

            listener = get_mini_listener(stt_instance=stt)
            msgs = listener.listen("tests/jfk.wav", language="en-us")
            assert any(m.msg_type == "recognizer_loop:utterance" for m in msgs)
            utt = next(m for m in msgs if m.msg_type == "recognizer_loop:utterance")
            assert utt.data["lang"] == "en-us"
            listener.shutdown()
        """
        self._messages.clear()

        # Resolve file path to bytes so the transformer pipeline receives bytes.
        if isinstance(audio, (str, Path)):
            with open(audio, "rb") as fh:
                audio_bytes: bytes = fh.read()
        else:
            audio_bytes = audio

        # Run audio through the transformer pipeline (always, even if no
        # plugins are loaded — transform() initialises the context dict).
        transformed, ctx = self.transformers.transform(audio_bytes)

        # STT step (optional)
        stt_instance = stt_instance or self._stt_instance
        if stt_instance is not None:
            # Convert (possibly transformer-modified) bytes to AudioData.
            # Use the WAV-aware helper so sample_rate / sample_width are
            # read from the WAV header rather than hard-coded.
            audio_data = _wav_to_audio_data(
                transformed, sample_rate=sample_rate, sample_width=sample_width
            )
            raw = stt_instance.execute(audio_data, language)
            transcript = raw.strip() if isinstance(raw, str) else ""

            if transcript:
                self.bus.emit(Message(
                    "recognizer_loop:utterance",
                    {"utterances": [transcript], "lang": language},
                    {**ctx, "destination": ["skills"]},
                ))

        return list(self._messages)

    def shutdown(self) -> None:
        """Shut down all loaded transformer plugins gracefully."""
        self.transformers.shutdown()


def get_mini_listener(
    transformer_plugins: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
    plugin_instances: Optional[Dict[str, Any]] = None,
    stt_instance: Optional[Any] = None,
) -> MiniListener:
    """Factory: create a ready-to-use :class:`MiniListener`.

    There are two usage modes:

    **Mode A — OPM discovery** (plugin is installed and registered via entry
    points)::

        listener = get_mini_listener(
            transformer_plugins=["ovos-audio-transformer-plugin-ggwave"]
        )

    **Mode B — direct injection** (plugin is not yet registered via OPM, or
    you need precise control over the plugin's config)::

        from ovos_audio_transformer_plugin_ggwave import GGWavePlugin
        plugin = GGWavePlugin(config={"start_enabled": True})
        listener = get_mini_listener(
            plugin_instances={"ovos-audio-transformer-plugin-ggwave": plugin}
        )

    Args:
        transformer_plugins: Plugin names to enable via OPM discovery.  Ignored
            when *config* is provided.
        config: Full config dict.  When provided, *transformer_plugins* is
            ignored.  Must include the ``listener.audio_transformers`` key.
        plugin_instances: Pre-instantiated audio-transformer plugin objects
            keyed by plugin name.  Injected directly into the
            ``AudioTransformersService`` after it is initialised, bypassing
            OPM entry-point discovery.
        stt_instance: STT plugin object with an
            ``execute(audio_data, language) -> str`` method. Stored as the
            default STT provider for the created ``MiniListener``.

    Returns:
        A fully initialised :class:`MiniListener` instance ready to receive
        audio.
    """
    if config is None:
        config = {
            "listener": {
                "audio_transformers": {
                    name: {} for name in (transformer_plugins or [])
                }
            }
        }
    return MiniListener(config,
                        plugin_instances=plugin_instances,
                        stt_instance=stt_instance)


@dataclass
class ListenerTest:
    """Declarative end-to-end test for audio transformer plugins.

    Mirrors :class:`ovoscope.End2EndTest` for the listener pipeline.

    Example::

        from ovoscope.listener import ListenerTest
        from ovos_audio_transformer_plugin_ggwave import GGWavePlugin
        from ovos_bus_client.message import Message

        plugin = GGWavePlugin(config={"start_enabled": True})
        test = ListenerTest(
            plugin_instances={"ovos-audio-transformer-plugin-ggwave": plugin},
            audio_input=b"\\x00" * 1024,
            expected_types=["recognizer_loop:utterance"],
        )
        test.execute()
    """

    plugin_instances: Dict[str, Any] = field(default_factory=dict)
    """Pre-instantiated plugin objects, keyed by plugin name."""

    transformer_plugins: List[str] = field(default_factory=list)
    """Plugin names to load via OPM discovery (alternative to plugin_instances)."""

    config: Dict[str, Any] = field(default_factory=dict)
    """Full OVOS config dict.  If empty, built from transformer_plugins."""

    audio_input: bytes = field(default=b"\x00" * 1024)
    """Raw audio bytes to inject into the pipeline."""

    feed_method: str = "feed_audio"
    """Which feed method to call: ``"feed_audio"``, ``"feed_speech"``, or
    ``"transform"``."""

    expected_types: List[str] = field(default_factory=list)
    """Message types that MUST appear in the captured output."""

    forbidden_types: List[str] = field(default_factory=list)
    """Message types that MUST NOT appear in the captured output."""

    stt_instance: Optional[Any] = None
    """Optional STT plugin object for full pipeline testing."""

    def execute(self) -> List[Message]:
        """Run the test and assert expected / forbidden messages.

        Returns:
            The list of captured :class:`ovos_bus_client.message.Message` objects.

        Raises:
            AssertionError: If any expected type is absent or any forbidden type
                is present.
        """
        listener = get_mini_listener(
            transformer_plugins=self.transformer_plugins or None,
            config=self.config or None,
            plugin_instances=self.plugin_instances or None,
            stt_instance=self.stt_instance,
        )
        try:
            method = getattr(listener, self.feed_method)
            # handle listen() signature
            if self.feed_method == "listen":
                messages = listener.listen(self.audio_input)
            else:
                result = method(self.audio_input)
                # transform() returns (audio, ctx, messages)
                if self.feed_method == "transform":
                    messages: List[Message] = result[2]
                else:
                    messages = result

            captured_types = {m.msg_type for m in messages}
            for expected in self.expected_types:
                assert expected in captured_types, (
                    f"Expected message type '{expected}' not found in captured "
                    f"messages: {captured_types}"
                )
            for forbidden in self.forbidden_types:
                assert forbidden not in captured_types, (
                    f"Forbidden message type '{forbidden}' was emitted: "
                    f"{captured_types}"
                )
            return messages
        finally:
            listener.shutdown()
