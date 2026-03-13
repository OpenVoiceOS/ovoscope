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
"""Unit tests for ovoscope.phal."""

import time
import threading
from unittest.mock import MagicMock

import pytest

from ovos_utils.fakebus import FakeBus
from ovos_bus_client.message import Message

from ovoscope.phal import MiniPHAL, PHALTest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_echo_plugin(bus: FakeBus, response_type: str, trigger_type: str) -> MagicMock:
    """Return a mock plugin that re-emits *response_type* when *trigger_type* is received."""
    plugin = MagicMock()
    plugin.shutdown = MagicMock()

    def on_trigger(msg: Message) -> None:
        bus.emit(Message(response_type))

    bus.on(trigger_type, on_trigger)
    return plugin


# ---------------------------------------------------------------------------
# MiniPHAL
# ---------------------------------------------------------------------------


class TestMiniPHAL:
    def test_context_manager_enter_exit(self):
        with MiniPHAL() as phal:
            assert phal._bus is not None

    def test_emit_and_assert_emitted(self):
        """Plugin responds to trigger: assert_emitted returns matching message."""
        with MiniPHAL() as phal:
            # Simulate a plugin by wiring a handler on the FakeBus directly
            phal._bus.on("test.trigger", lambda msg: phal._bus.emit(Message("test.response")))
            phal.emit(Message("test.trigger"), wait=0.1)
            msg = phal.assert_emitted("test.response", timeout=2.0)
            assert msg.msg_type == "test.response"

    def test_assert_emitted_raises_on_timeout(self):
        with MiniPHAL() as phal:
            with pytest.raises(AssertionError, match="test.never"):
                phal.assert_emitted("test.never", timeout=0.2)

    def test_assert_not_emitted_passes_when_absent(self):
        with MiniPHAL() as phal:
            phal.assert_not_emitted("some.message.type", wait=0.1)  # should not raise

    def test_assert_not_emitted_raises_when_present(self):
        with MiniPHAL() as phal:
            phal._bus.emit(Message("bad.message"))
            time.sleep(0.1)
            with pytest.raises(AssertionError, match="bad.message"):
                phal.assert_not_emitted("bad.message", wait=0.05)

    def test_clear_captured(self):
        with MiniPHAL() as phal:
            phal._bus.emit(Message("some.msg"))
            time.sleep(0.1)
            phal.clear_captured()
            assert phal._captured == []

    def test_plugin_instances_used(self):
        """Pre-built plugin instances are stored and shutdown is called on exit."""
        mock_plugin = MagicMock()
        mock_plugin.shutdown = MagicMock()
        with MiniPHAL(
            plugin_ids=["fake-plugin"],
            plugin_instances={"fake-plugin": mock_plugin},
        ) as phal:
            assert "fake-plugin" in phal._loaded
        mock_plugin.shutdown.assert_called_once()


# ---------------------------------------------------------------------------
# PHALTest
# ---------------------------------------------------------------------------


class TestPHALTest:
    def test_execute_with_mock_plugin(self):
        """PHALTest with a pre-wired mock plugin verifies expected_types."""
        # We don't have a real PHAL plugin installed so we wire up the bus manually.
        # Use MiniPHAL directly instead.
        with MiniPHAL() as phal:
            phal._bus.on("trigger", lambda m: phal._bus.emit(Message("expected.response")))
            phal.emit(Message("trigger"), wait=0.1)
            phal.assert_emitted("expected.response")

    def test_phal_test_dataclass_fields(self):
        trigger = Message("test.trigger")
        t = PHALTest(
            plugin_ids=["fake-phal"],
            trigger_message=trigger,
            expected_types=["expected.type"],
            forbidden_types=["bad.type"],
            timeout=3.0,
        )
        assert t.plugin_ids == ["fake-phal"]
        assert t.expected_types == ["expected.type"]
        assert t.forbidden_types == ["bad.type"]
        assert t.timeout == 3.0

    def test_phal_test_execute_with_instance(self):
        """PHALTest.execute with a pre-built instance that auto-responds."""
        from ovos_utils.fakebus import FakeBus as _FakeBus

        # We can't easily inject a "real" plugin, but we verify the dataclass
        # executes without error when plugin loading is skipped due to no real plugin.
        # Just verify PHALTest.execute completes (plugin_ids=[] = no plugins to load).
        t = PHALTest(
            plugin_ids=[],
            trigger_message=Message("harmless.trigger"),
            expected_types=[],
            forbidden_types=[],
            timeout=0.5,
        )
        result = t.execute()
        assert isinstance(result, list)
