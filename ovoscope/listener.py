# Copyright 2024 OpenVoiceOS
# Licensed under the Apache License, Version 2.0
"""MiniListener — in-process audio transformer pipeline for ovoscope.

Wraps ``AudioTransformersService`` on a ``FakeBus`` so that audio
transformer plugins can be tested end-to-end without a real microphone
or a running ``ovos-dinkum-listener`` process.

Example::

    from ovoscope.listener import get_mini_listener
    from ovos_audio_transformer_plugin_ggwave import GGWavePlugin
    from unittest.mock import MagicMock
    import ggwave

    ggwave.decode = MagicMock(return_value=b"UTT:turn on the lights")
    plugin = GGWavePlugin(config={"start_enabled": True})
    listener = get_mini_listener(plugin_instances={"ovos-audio-transformer-plugin-ggwave": plugin})
    msgs = listener.feed_audio(b"\\x00" * 1024)
    assert any(m.msg_type == "recognizer_loop:utterance" for m in msgs)
    listener.shutdown()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus


class MiniListener:
    """In-process audio transformer pipeline for integration testing.

    Wraps ``AudioTransformersService`` — `ovos_dinkum_listener/transformers.py` —
    on a ``FakeBus`` so transformer plugins can be exercised without hardware.

    All ``Message`` objects emitted on the bus during a ``feed_audio`` /
    ``feed_speech`` / ``transform`` call are captured and returned.

    Args:
        config: Full OVOS config dict. Must contain at minimum::

            {"listener": {"audio_transformers": {}}}

        plugin_instances: Optional mapping of plugin name → already-instantiated
            plugin object.  Use this when the plugin is not (yet) registered via
            an OPM entry point, or when you need direct control over the
            plugin config.  Each plugin will be bound to the internal FakeBus
            and injected into the ``AudioTransformersService``.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        plugin_instances: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.bus: FakeBus = FakeBus()
        self._messages: List[Message] = []

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

    def shutdown(self) -> None:
        """Shut down all loaded transformer plugins gracefully."""
        self.transformers.shutdown()


def get_mini_listener(
    transformer_plugins: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
    plugin_instances: Optional[Dict[str, Any]] = None,
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
        plugin_instances: Pre-instantiated plugin objects keyed by plugin name.
            Injected directly into the ``AudioTransformersService`` after it
            is initialised, bypassing OPM entry-point discovery.

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
    return MiniListener(config, plugin_instances=plugin_instances)


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
        )
        try:
            method = getattr(listener, self.feed_method)
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
