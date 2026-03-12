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
"""Unit tests for ovoscope.media (MockOCPBackend, OCPCaptureSession, OCPPlayerHarness)."""

import pytest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus
from ovos_utils.ocp import MediaState

from ovoscope.media import MockOCPBackend, OCPCaptureSession


# ---------------------------------------------------------------------------
# MockOCPBackend tests
# ---------------------------------------------------------------------------

class TestMockOCPBackendInit:
    """Constructor and initial state."""

    def test_initial_state(self) -> None:
        """Backend starts with clean state."""
        bus = FakeBus()
        backend = MockOCPBackend(config={}, bus=bus)
        assert backend.is_playing is False
        assert backend.is_paused is False
        assert backend.current_uri is None
        assert backend.played_uris == []

    def test_namespace_default(self) -> None:
        """Default namespace is 'audio'."""
        bus = FakeBus()
        backend = MockOCPBackend(config={}, bus=bus)
        assert backend.namespace == "audio"

    def test_namespace_custom(self) -> None:
        """Custom namespace is stored."""
        bus = FakeBus()
        backend = MockOCPBackend(config={}, bus=bus, namespace="video")
        assert backend.namespace == "video"


class TestMockOCPBackendStateTransitions:
    """State mutation methods."""

    def setup_method(self) -> None:
        self.bus = FakeBus()
        self.backend = MockOCPBackend(config={}, bus=self.bus)

    def test_play_sets_playing(self) -> None:
        self.backend.play()
        assert self.backend.is_playing is True
        assert self.backend.is_paused is False

    def test_pause_sets_paused(self) -> None:
        self.backend.play()
        self.backend.pause()
        assert self.backend.is_paused is True

    def test_resume_clears_paused(self) -> None:
        self.backend.play()
        self.backend.pause()
        self.backend.resume()
        assert self.backend.is_paused is False

    def test_stop_clears_state(self) -> None:
        self.backend.play()
        result = self.backend.stop()
        assert self.backend.is_playing is False
        assert self.backend.is_paused is False
        assert result is True

    def test_load_track_sets_uri(self) -> None:
        self.backend.load_track("http://example.com/song.mp3")
        assert self.backend.current_uri == "http://example.com/song.mp3"
        assert "http://example.com/song.mp3" in self.backend.played_uris

    def test_load_track_emits_state_event(self) -> None:
        received: list = []
        self.bus.on(f"ovos.audio.service.media.state", lambda m: received.append(m))
        self.backend.load_track("http://example.com/song.mp3")
        assert len(received) == 1

    def test_add_list_records_uris(self) -> None:
        self.backend.add_list(["track1.mp3", "track2.mp3"])
        assert "track1.mp3" in self.backend.played_uris
        assert self.backend.current_uri == "track1.mp3"

    def test_clear_list(self) -> None:
        self.backend.add_list(["track1.mp3"])
        self.backend.clear_list()
        assert self.backend.played_uris == []
        assert self.backend.current_uri is None

    def test_reset(self) -> None:
        self.backend.play()
        self.backend.add_list(["track1.mp3"])
        self.backend.reset()
        assert self.backend.is_playing is False
        assert self.backend.is_paused is False
        assert self.backend.current_uri is None
        assert self.backend.played_uris == []

    def test_supported_uris(self) -> None:
        uris = self.backend.supported_uris()
        assert "file" in uris
        assert "http" in uris
        assert "https" in uris

    def test_track_info(self) -> None:
        self.backend.current_uri = "http://example.com/song.mp3"
        info = self.backend.track_info()
        assert info["track"] == "http://example.com/song.mp3"

    def test_get_track_length_returns_zero(self) -> None:
        assert self.backend.get_track_length() == 0

    def test_get_track_position_returns_zero(self) -> None:
        assert self.backend.get_track_position() == 0

    def test_simulate_end_emits_event(self) -> None:
        received: list = []
        self.bus.on("ovos.common_play.media.state", lambda m: received.append(m))
        self.backend.simulate_end()
        assert len(received) == 1
        assert self.backend.is_playing is False

    def test_simulate_invalid_stream(self) -> None:
        received: list = []
        self.bus.on("ovos.common_play.media.state", lambda m: received.append(m))
        self.backend.simulate_invalid_stream()
        assert len(received) == 1
        assert self.backend.is_playing is False


# ---------------------------------------------------------------------------
# OCPCaptureSession tests
# ---------------------------------------------------------------------------

class TestOCPCaptureSessionMessageAccumulation:
    """Message capture and filtering."""

    def setup_method(self) -> None:
        self.bus = FakeBus()

    def test_captures_matching_prefix(self) -> None:
        session = OCPCaptureSession(bus=self.bus)
        session.start()
        self.bus.emit(Message("ovos.common_play.play"))
        session.stop()
        assert "ovos.common_play.play" in session.message_types

    def test_does_not_capture_non_matching(self) -> None:
        session = OCPCaptureSession(bus=self.bus)
        session.start()
        self.bus.emit(Message("some.other.message"))
        session.stop()
        assert "some.other.message" not in session.message_types

    def test_start_clears_previous(self) -> None:
        session = OCPCaptureSession(bus=self.bus)
        session.start()
        self.bus.emit(Message("ovos.common_play.play"))
        session.stop()
        session.start()
        session.stop()
        assert session.messages == []

    def test_context_manager(self) -> None:
        with OCPCaptureSession(bus=self.bus) as session:
            self.bus.emit(Message("ovos.common_play.pause"))
        assert "ovos.common_play.pause" in session.message_types

    def test_assert_sequence_passes(self) -> None:
        with OCPCaptureSession(bus=self.bus) as session:
            self.bus.emit(Message("ovos.common_play.play"))
            self.bus.emit(Message("ovos.common_play.pause"))
        session.assert_sequence("ovos.common_play.play", "ovos.common_play.pause")

    def test_assert_sequence_fails_on_missing(self) -> None:
        with OCPCaptureSession(bus=self.bus) as session:
            self.bus.emit(Message("ovos.common_play.play"))
        with pytest.raises(AssertionError):
            session.assert_sequence("ovos.common_play.stop")

    def test_custom_prefixes(self) -> None:
        session = OCPCaptureSession(bus=self.bus, track_prefixes=["custom.prefix."])
        session.start()
        self.bus.emit(Message("custom.prefix.event"))
        self.bus.emit(Message("ovos.common_play.play"))  # should not be captured
        session.stop()
        assert session.message_types == ["custom.prefix.event"]
