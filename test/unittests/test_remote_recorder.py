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
"""Unit tests for ovoscope.remote_recorder.RemoteRecorder."""

import threading
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

from ovos_bus_client.message import Message

from ovoscope.remote_recorder import RemoteRecorder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(messages_to_emit: List[Message]) -> MagicMock:
    """Build a mock MessageBusClient that emits *messages_to_emit* when subscribed."""
    client = MagicMock()
    client.connected_event = threading.Event()
    client.connected_event.set()

    handlers: dict = {}

    def on_side_effect(event_type: str, handler: Any) -> None:
        handlers.setdefault(event_type, []).append(handler)

    def remove_side_effect(event_type: str, handler: Any) -> None:
        if event_type in handlers:
            try:
                handlers[event_type].remove(handler)
            except ValueError:
                pass

    def emit_side_effect(msg: Message) -> None:
        # Deliver mocked response messages to subscribed handlers
        for m in messages_to_emit:
            for h in list(handlers.get("message", [])):
                h(m.serialize())

    client.on.side_effect = on_side_effect
    client.remove.side_effect = remove_side_effect
    client.emit.side_effect = emit_side_effect

    return client


# ---------------------------------------------------------------------------
# Constructor / config
# ---------------------------------------------------------------------------


class TestRemoteRecorderConstructor:
    """Constructor and default field values."""

    def test_default_url(self) -> None:
        r = RemoteRecorder()
        assert r.bus_url == "ws://localhost:8181/core"

    def test_custom_url(self) -> None:
        r = RemoteRecorder(bus_url="ws://192.168.1.5:8181/core")
        assert r.bus_url == "ws://192.168.1.5:8181/core"

    def test_initial_state(self) -> None:
        r = RemoteRecorder()
        assert r._client is None
        assert r._captured == []


# ---------------------------------------------------------------------------
# _parse_url
# ---------------------------------------------------------------------------


class TestParseUrl:
    """URL parsing helper."""

    def test_full_ws_url(self) -> None:
        host, port, path = RemoteRecorder._parse_url("ws://localhost:8181/core")
        assert host == "localhost"
        assert port == 8181
        assert path == "/core"

    def test_no_port(self) -> None:
        host, port, path = RemoteRecorder._parse_url("ws://myhost/core")
        assert host == "myhost"
        assert port == 8181
        assert path == "/core"

    def test_no_path(self) -> None:
        host, port, path = RemoteRecorder._parse_url("ws://localhost:8181")
        assert host == "localhost"
        assert port == 8181
        assert path == "/core"

    def test_wss_scheme(self) -> None:
        host, port, path = RemoteRecorder._parse_url("wss://secure.host:443/bus")
        assert host == "secure.host"
        assert port == 443
        assert path == "/bus"


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    """Connection lifecycle."""

    def test_connect_sets_client(self) -> None:
        r = RemoteRecorder()
        mock_client = MagicMock()
        mock_client.connected_event = threading.Event()
        mock_client.connected_event.set()
        with patch("ovoscope.remote_recorder.RemoteRecorder._parse_url", return_value=("localhost", 8181, "/core")):
            with patch("ovos_bus_client.client.MessageBusClient", return_value=mock_client):
                r.connect()
        assert r._client is not None

    def test_disconnect_clears_client(self) -> None:
        r = RemoteRecorder()
        mock_client = MagicMock()
        mock_client.connected_event = threading.Event()
        mock_client.connected_event.set()
        with patch("ovoscope.remote_recorder.RemoteRecorder._parse_url", return_value=("localhost", 8181, "/core")):
            with patch("ovos_bus_client.client.MessageBusClient", return_value=mock_client):
                r.connect()
        r.disconnect()
        assert r._client is None

    def test_disconnect_without_connect_is_safe(self) -> None:
        r = RemoteRecorder()
        r.disconnect()  # should not raise


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------


class TestRecord:
    """record() method with mocked bus client."""

    def test_record_requires_connect(self) -> None:
        r = RemoteRecorder()
        with pytest.raises(RuntimeError, match="connect"):
            r.record("hello")

    def test_record_returns_end2endtest(self) -> None:
        """record() returns an End2EndTest when an EOF message is emitted."""
        eof_msg = Message("ovos.utterance.handled")
        speak_msg = Message("speak", {"utterance": "hello world"})
        mock_client = _make_mock_client([speak_msg, eof_msg])

        r = RemoteRecorder()
        r._client = mock_client

        result = r.record("hello", timeout=5.0)

        from ovoscope import End2EndTest
        assert isinstance(result, End2EndTest)

    def test_record_captures_messages(self) -> None:
        """record() captures all messages before the EOF signal."""
        eof_msg = Message("ovos.utterance.handled")
        speak_msg = Message("speak", {"utterance": "greetings"})
        mock_client = _make_mock_client([speak_msg, eof_msg])

        r = RemoteRecorder()
        r._client = mock_client

        result = r.record("greetings", timeout=5.0)
        types = [m.msg_type for m in result.expected_messages]
        assert "speak" in types

    def test_record_timeout_raises(self) -> None:
        """record() raises TimeoutError when no EOF arrives."""
        mock_client = _make_mock_client([])  # no messages → never completes

        r = RemoteRecorder()
        r._client = mock_client

        with pytest.raises(TimeoutError):
            r.record("silent utterance", timeout=0.1)

    def test_record_passes_skill_id_in_context(self) -> None:
        """record() attaches skill_id to the emitted source message context."""
        eof_msg = Message("ovos.utterance.handled")
        mock_client = _make_mock_client([eof_msg])

        r = RemoteRecorder()
        r._client = mock_client
        result = r.record("hello", skill_id="ovos-skill-hello-world.openvoiceos", timeout=5.0)
        assert result.skill_ids == ["ovos-skill-hello-world.openvoiceos"]


# ---------------------------------------------------------------------------
# Fixture serialization
# ---------------------------------------------------------------------------


class TestFixtureSerialization:
    """Output format of record()."""

    def test_source_message_is_utterance(self) -> None:
        eof_msg = Message("ovos.utterance.handled")
        mock_client = _make_mock_client([eof_msg])

        r = RemoteRecorder()
        r._client = mock_client
        result = r.record("what time is it", timeout=5.0)

        # source_message may be stored as a list or a single Message
        src = result.source_message
        if isinstance(src, list):
            src = src[0]
        assert src.msg_type == "recognizer_loop:utterance"
        assert "what time is it" in src.data["utterances"]

    def test_save_produces_json(self, tmp_path) -> None:
        """Fixture can be saved to JSON without errors."""
        import json
        eof_msg = Message("ovos.utterance.handled")
        mock_client = _make_mock_client([eof_msg])

        r = RemoteRecorder()
        r._client = mock_client
        result = r.record("hello", timeout=5.0)

        out = tmp_path / "fixture.json"
        result.save(str(out))
        payload = json.loads(out.read_text())
        assert "expected_messages" in payload
