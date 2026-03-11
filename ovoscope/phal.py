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
"""PHAL plugin test harness for ovoscope.

PHAL (Plugin Hardware Abstraction Layer) plugins communicate exclusively
via the MessageBus, so ``FakeBus`` injection works without real hardware.

Example::

    from ovos_utils.messagebus import FakeMessage as Message
    from ovoscope.phal import MiniPHAL, PHALTest

    with MiniPHAL(plugin_ids=["ovos-PHAL-plugin-connectivity-events.openvoiceos"]) as phal:
        phal.emit(Message("network.connected"))
        msg = phal.assert_emitted("mycroft.internet.connected", timeout=2.0)
        assert msg.data.get("connected") is True

Plugins that require physical hardware (alsa, mk1, dotstar) are out of scope
and should be tested with hardware-in-the-loop integration tests instead.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ovos_utils.fakebus import FakeBus
from ovos_utils.messagebus import Message


class MiniPHAL:
    """Context manager that loads PHAL plugins on a :class:`FakeBus`.

    PHAL plugins accept a ``bus`` argument directly so ``FakeBus`` injection
    is transparent — no real MessageBus server is required.

    Args:
        plugin_ids: OPM entry-point IDs of the PHAL plugins to load.
        plugin_instances: Pre-built or mocked plugin instances keyed by plugin_id.
            When provided the corresponding entry in *plugin_ids* is skipped.
        config: Per-plugin configuration overrides keyed by plugin_id.

    Example::

        with MiniPHAL(
            plugin_ids=["ovos-PHAL-plugin-system.openvoiceos"],
            config={"ovos-PHAL-plugin-system.openvoiceos": {"shutdown_timeout": 0}},
        ) as phal:
            phal.emit(Message("system.reboot"))
            phal.assert_emitted("system.reboot.confirmed")
    """

    def __init__(
        self,
        plugin_ids: Optional[List[str]] = None,
        plugin_instances: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.plugin_ids: List[str] = plugin_ids or []
        self.plugin_instances: Dict[str, Any] = plugin_instances or {}
        self.config: Dict[str, Dict[str, Any]] = config or {}
        self._bus: FakeBus = FakeBus()
        self._captured: List[Message] = []
        self._loaded: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Context manager interface
    # ------------------------------------------------------------------

    def __enter__(self) -> "MiniPHAL":
        """Start the harness and load all specified PHAL plugins."""
        self._bus.on("message", self._capture)
        self._load_plugins()
        return self

    def __exit__(self, *_: Any) -> None:
        """Shut down all loaded plugins and close the bus."""
        for plugin in self._loaded.values():
            try:
                plugin.shutdown()
            except Exception:
                pass
        self._bus.remove("message", self._capture)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _capture(self, message: Any) -> None:
        """Capture every message emitted on the bus."""
        if isinstance(message, str):
            try:
                message = Message.deserialize(message)
            except Exception:
                return
        self._captured.append(message)

    def _load_plugins(self) -> None:
        """Load PHAL plugins via OPM or use pre-built instances."""
        for plugin_id in self.plugin_ids:
            if plugin_id in self.plugin_instances:
                instance = self.plugin_instances[plugin_id]
            else:
                instance = self._instantiate_plugin(plugin_id)
            if instance is not None:
                self._loaded[plugin_id] = instance

    def _instantiate_plugin(self, plugin_id: str) -> Optional[Any]:
        """Instantiate a PHAL plugin by its OPM entry-point ID.

        Args:
            plugin_id: The OPM entry-point identifier for the plugin.

        Returns:
            The instantiated plugin object, or None if loading fails.
        """
        try:
            from ovos_plugin_manager.phal import OVOSPHALPlugin  # type: ignore
            cfg = self.config.get(plugin_id, {})
            plugin = OVOSPHALPlugin(bus=self._bus, config=cfg, plugin_id=plugin_id)
            return plugin
        except Exception as exc:
            import warnings
            warnings.warn(f"Failed to load PHAL plugin {plugin_id!r}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def emit(self, msg: Message, wait: float = 0.05) -> None:
        """Emit a message on the internal bus and wait briefly for handlers.

        Args:
            msg: The message to emit.
            wait: Seconds to wait after emission for async handlers to fire.
        """
        self._bus.emit(msg)
        if wait > 0:
            time.sleep(wait)

    def assert_emitted(self, msg_type: str, timeout: float = 2.0) -> Message:
        """Assert that a message of *msg_type* was (or will be) emitted.

        Polls the captured message list up to *timeout* seconds.

        Args:
            msg_type: The ``type`` field to look for.
            timeout: Maximum seconds to wait.

        Returns:
            The first matching :class:`Message`.

        Raises:
            AssertionError: If no matching message is captured within *timeout*.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg in self._captured:
                if msg.msg_type == msg_type:
                    return msg
            time.sleep(0.05)
        captured_types = [m.msg_type for m in self._captured]
        raise AssertionError(
            f"Expected message type {msg_type!r} was not emitted within {timeout}s. "
            f"Captured: {captured_types}"
        )

    def assert_not_emitted(self, msg_type: str, wait: float = 0.2) -> None:
        """Assert that a message of *msg_type* is NOT emitted.

        Waits *wait* seconds then checks captured messages.

        Args:
            msg_type: The ``type`` field that must NOT appear.
            wait: Seconds to observe before asserting absence.

        Raises:
            AssertionError: If a matching message was captured.
        """
        time.sleep(wait)
        for msg in self._captured:
            if msg.msg_type == msg_type:
                raise AssertionError(
                    f"Message type {msg_type!r} was emitted but was not expected."
                )

    def clear_captured(self) -> None:
        """Clear the captured message list, useful between assertions."""
        self._captured.clear()


@dataclass
class PHALTest:
    """Declarative PHAL plugin test.

    Fields:
        plugin_ids: OPM entry-point IDs of the PHAL plugins under test.
        trigger_message: The :class:`Message` to emit as the test stimulus.
        expected_types: Message types that MUST appear in the capture.
        forbidden_types: Message types that MUST NOT appear.
        plugin_instances: Pre-built plugin instances (keyed by plugin_id).
        config: Per-plugin config overrides.
        timeout: Maximum seconds to wait for expected messages (default 5.0).

    Example::

        from ovos_utils.messagebus import FakeMessage as Message
        from ovoscope.phal import PHALTest

        result = PHALTest(
            plugin_ids=["ovos-PHAL-plugin-connectivity-events.openvoiceos"],
            trigger_message=Message("network.connected"),
            expected_types=["mycroft.internet.connected"],
            forbidden_types=["mycroft.internet.disconnected"],
        ).execute()
    """

    plugin_ids: List[str]
    trigger_message: Message
    expected_types: List[str] = field(default_factory=list)
    forbidden_types: List[str] = field(default_factory=list)
    plugin_instances: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timeout: float = 5.0

    def execute(self) -> List[Message]:
        """Run the test: load plugins, emit trigger, assert expectations.

        Returns:
            All messages captured during the test.

        Raises:
            AssertionError: If an expected type is missing or a forbidden type appears.
        """
        with MiniPHAL(
            plugin_ids=self.plugin_ids,
            plugin_instances=self.plugin_instances,
            config=self.config,
        ) as phal:
            phal.emit(self.trigger_message, wait=0.1)

            for msg_type in self.expected_types:
                phal.assert_emitted(msg_type, timeout=self.timeout)

            for msg_type in self.forbidden_types:
                phal.assert_not_emitted(msg_type, wait=0.1)

            return list(phal._captured)
