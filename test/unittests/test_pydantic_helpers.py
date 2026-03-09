"""Unit tests for ovoscope.pydantic_helpers.

All tests require ovos-pydantic-models (ovoscope[pydantic]).
The suite is skipped as a whole if that optional dependency is missing.
"""
import json
import tempfile
import unittest
from pathlib import Path

from ovos_bus_client.message import Message
from ovos_utils.log import LOG

try:
    from ovos_pydantic_models import (
        RecognizerLoopUtteranceData,
        RecognizerLoopUtteranceMessage,
        SpeakData,
        SpeakMessage,
    )
    from ovos_pydantic_models.message import OpenVoiceOSMessage
    from pydantic import ValidationError
    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False

from ovoscope.pydantic_helpers import (
    from_bus_message,
    to_bus_message,
    validate_fixture,
)


@unittest.skipUnless(_PYDANTIC_AVAILABLE, "ovos-pydantic-models not installed")
class TestToBusMessage(unittest.TestCase):
    """Tests for to_bus_message()."""

    def setUp(self) -> None:
        LOG.set_level("ERROR")

    def test_msg_type_is_set(self) -> None:
        """msg_type on the returned Message must match the pydantic model's message_type."""
        model = SpeakMessage(data=SpeakData(utterance="hello"))
        msg = to_bus_message(model)
        self.assertEqual(msg.msg_type, "speak")

    def test_data_fields_are_preserved(self) -> None:
        """Data fields from the pydantic model must appear in Message.data."""
        model = SpeakMessage(data=SpeakData(utterance="hello world"))
        msg = to_bus_message(model)
        self.assertEqual(msg.data["utterance"], "hello world")

    def test_returns_message_instance(self) -> None:
        """Return type must be ovos_bus_client.message.Message."""
        model = SpeakMessage(data=SpeakData(utterance="hi"))
        result = to_bus_message(model)
        self.assertIsInstance(result, Message)

    def test_utterance_message_type(self) -> None:
        """recognizer_loop:utterance message type is preserved."""
        model = RecognizerLoopUtteranceMessage(
            data=RecognizerLoopUtteranceData(utterances=["hello"], lang="en-us")
        )
        msg = to_bus_message(model)
        self.assertEqual(msg.msg_type, "recognizer_loop:utterance")
        self.assertEqual(msg.data["utterances"], ["hello"])

    def test_empty_context_defaults_to_dict(self) -> None:
        """Context must be a dict even when the model has no context fields set."""
        model = SpeakMessage(data=SpeakData(utterance="hi"))
        msg = to_bus_message(model)
        self.assertIsInstance(msg.context, dict)

    def test_roundtrip_preserves_utterance(self) -> None:
        """to_bus_message followed by from_bus_message yields the same utterance."""
        original = SpeakMessage(data=SpeakData(utterance="round trip"))
        bus_msg = to_bus_message(original)
        recovered = from_bus_message(bus_msg, SpeakMessage)
        self.assertEqual(recovered.data.utterance, "round trip")


@unittest.skipUnless(_PYDANTIC_AVAILABLE, "ovos-pydantic-models not installed")
class TestFromBusMessage(unittest.TestCase):
    """Tests for from_bus_message()."""

    def setUp(self) -> None:
        LOG.set_level("ERROR")

    def test_valid_speak_message(self) -> None:
        """A well-formed speak Message parses into SpeakMessage without errors."""
        bus_msg = Message("speak", {"utterance": "hello", "lang": "en-us"}, {})
        result = from_bus_message(bus_msg, SpeakMessage)
        self.assertIsInstance(result, SpeakMessage)
        self.assertEqual(result.data.utterance, "hello")

    def test_valid_utterance_message(self) -> None:
        """A well-formed recognizer_loop:utterance parses into the typed model."""
        bus_msg = Message(
            "recognizer_loop:utterance",
            {"utterances": ["what time is it"], "lang": "en-us"},
            {},
        )
        result = from_bus_message(bus_msg, RecognizerLoopUtteranceMessage)
        self.assertEqual(result.data.utterances, ["what time is it"])

    def test_returns_correct_model_type(self) -> None:
        """The returned object must be an instance of the requested model class."""
        bus_msg = Message("speak", {"utterance": "test"}, {})
        result = from_bus_message(bus_msg, SpeakMessage)
        self.assertIsInstance(result, SpeakMessage)

    def test_invalid_message_raises_validation_error(self) -> None:
        """A message whose data violates the schema must raise ValidationError."""
        # RecognizerLoopUtteranceMessage requires 'utterances' to be a list, not a string
        bus_msg = Message(
            "recognizer_loop:utterance",
            {"utterances": "not-a-list", "lang": "en-us"},
            {},
        )
        with self.assertRaises(ValidationError):
            from_bus_message(bus_msg, RecognizerLoopUtteranceMessage)

    def test_base_model_accepts_any_well_formed_message(self) -> None:
        """OpenVoiceOSMessage accepts any message_type + dict data."""
        bus_msg = Message("custom.event", {"key": "value"}, {})
        result = from_bus_message(bus_msg, OpenVoiceOSMessage)
        self.assertEqual(result.message_type, "custom.event")


@unittest.skipUnless(_PYDANTIC_AVAILABLE, "ovos-pydantic-models not installed")
class TestValidateFixture(unittest.TestCase):
    """Tests for validate_fixture()."""

    def setUp(self) -> None:
        LOG.set_level("ERROR")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _write_fixture(self, data: dict) -> Path:
        """Write data as JSON to a temp file and return its Path."""
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(data, f)
        f.close()
        return Path(f.name)

    def _valid_fixture(self) -> dict:
        """Minimal valid fixture dict matching End2EndTest.serialize() format."""
        return {
            "skill_ids": ["test-skill.author"],
            "source_message": [
                {
                    "type": "recognizer_loop:utterance",
                    "data": {"utterances": ["hello"], "lang": "en-us"},
                    "context": {},
                }
            ],
            "expected_messages": [
                {
                    "type": "speak",
                    "data": {"utterance": "Hello!", "lang": "en-us"},
                    "context": {},
                }
            ],
            "eof_msgs": ["ovos.utterance.handled"],
            "flip_points": [],
            "test_msg_type": True,
            "test_msg_data": True,
            "test_msg_context": False,
            "test_routing": False,
        }

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------
    def test_valid_fixture_returns_dict(self) -> None:
        """validate_fixture returns the raw fixture dict on success."""
        fixture = self._valid_fixture()
        path = self._write_fixture(fixture)
        result = validate_fixture(path)
        self.assertEqual(result["skill_ids"], ["test-skill.author"])

    def test_valid_fixture_source_preserved(self) -> None:
        """source_message entries are preserved verbatim in the returned dict."""
        fixture = self._valid_fixture()
        path = self._write_fixture(fixture)
        result = validate_fixture(path)
        self.assertEqual(
            result["source_message"][0]["type"],
            "recognizer_loop:utterance",
        )

    def test_valid_fixture_expected_preserved(self) -> None:
        """expected_messages entries are preserved verbatim in the returned dict."""
        fixture = self._valid_fixture()
        path = self._write_fixture(fixture)
        result = validate_fixture(path)
        self.assertEqual(result["expected_messages"][0]["data"]["utterance"], "Hello!")

    def test_missing_file_raises_file_not_found(self) -> None:
        """validate_fixture raises FileNotFoundError for a non-existent path."""
        with self.assertRaises(FileNotFoundError):
            validate_fixture("/tmp/ovoscope_nonexistent_fixture_xyz.json")

    def test_malformed_source_message_raises_value_error(self) -> None:
        """A source_message without any type key must raise ValueError.

        validate_fixture uses OpenVoiceOSMessage which requires 'message_type'.
        When both 'type' and 'message_type' are absent the field is missing
        and pydantic raises ValidationError, which is chained into ValueError.
        """
        fixture = self._valid_fixture()
        # Remove both 'type' and 'message_type' — normalised dict will be missing
        # the required 'message_type' field and pydantic will reject it.
        fixture["source_message"][0] = {"data": {"utterances": ["hi"]}, "context": {}}
        path = self._write_fixture(fixture)
        with self.assertRaises(ValueError) as ctx:
            validate_fixture(path)
        self.assertIn("source_message[0]", str(ctx.exception))

    def test_malformed_expected_message_raises_value_error(self) -> None:
        """A malformed expected_message must raise ValueError with section info."""
        fixture = self._valid_fixture()
        # context must be a dict — providing a non-dict triggers MessageContext
        # validation error inside OpenVoiceOSMessage, which is chained into ValueError.
        fixture["expected_messages"][0] = {
            "type": "speak",
            "data": {"utterance": "hi"},
            "context": "not-a-dict",
        }
        path = self._write_fixture(fixture)
        with self.assertRaises(ValueError) as ctx:
            validate_fixture(path)
        self.assertIn("expected_messages[0]", str(ctx.exception))

    def test_error_chains_validation_error(self) -> None:
        """The ValueError raised must chain the original pydantic ValidationError."""
        fixture = self._valid_fixture()
        # Remove both type keys so message_type is missing from normalised dict
        fixture["source_message"][0] = {"data": {"utterances": ["hi"]}, "context": {}}
        path = self._write_fixture(fixture)
        with self.assertRaises(ValueError) as ctx:
            validate_fixture(path)
        self.assertIsInstance(ctx.exception.__cause__, ValidationError)

    def test_accepts_message_type_key(self) -> None:
        """validate_fixture accepts both 'type' and 'message_type' as the key."""
        fixture = self._valid_fixture()
        # Use 'message_type' instead of 'type'
        msg = fixture["source_message"][0]
        msg["message_type"] = msg.pop("type")
        path = self._write_fixture(fixture)
        result = validate_fixture(path)
        self.assertIsNotNone(result)

    def test_empty_messages_lists_pass(self) -> None:
        """Fixtures with empty source/expected lists must pass validation."""
        fixture = self._valid_fixture()
        fixture["source_message"] = []
        fixture["expected_messages"] = []
        path = self._write_fixture(fixture)
        result = validate_fixture(path)
        self.assertEqual(result["source_message"], [])


if __name__ == "__main__":
    unittest.main()
