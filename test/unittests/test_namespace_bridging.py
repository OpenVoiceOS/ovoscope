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

"""End-to-end tests for the FakeBus legacy<->ovos.* namespace migration.

The ovoscope harness runs components on a :class:`ovos_utils.fakebus.FakeBus`
that mirrors ``MessageBusClient``'s namespace migration (ovos-utils #381): with
``modernize``/``emit_legacy`` on (the defaults), emitting a topic on one
namespace ALSO dispatches its counterpart on the other, and a handler subscribed
to both topics fires once. These tests pin that behaviour through the harness bus
so an ovoscope test can deliberately exercise EITHER namespace, BOTH, or a single
isolated namespace.

The pairs come from ``ovos_spec_tools.MIGRATION_MAP`` (legacy -> SpecMessage),
e.g. ``speak`` <-> ``ovos.utterance.speak`` and
``recognizer_loop:utterance`` <-> ``ovos.utterance.handle``.
"""

import threading
import time
import unittest

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus
from ovos_spec_tools import SpecMessage
from ovos_spec_tools.messages import MIGRATION_MAP


# Representative migrating pairs (legacy topic, spec topic).
LEGACY_SPEAK = "speak"
SPEC_SPEAK = str(SpecMessage.SPEAK)               # ovos.utterance.speak
LEGACY_UTTERANCE = "recognizer_loop:utterance"
SPEC_UTTERANCE = str(SpecMessage.UTTERANCE)       # ovos.utterance.handle


def _collect(bus, topic):
    """Subscribe a counting handler on ``topic``; return its list of payloads."""
    received = []
    bus.on(topic, lambda m: received.append(m))
    return received


class TestFakeBusNamespaceBridging(unittest.TestCase):
    """Both-namespace e2e coverage through the ovoscope harness FakeBus."""

    def test_migration_map_is_populated(self) -> None:
        """Sanity: the spec pairs this suite asserts on are actually migrated."""
        self.assertEqual(MIGRATION_MAP[LEGACY_SPEAK], SpecMessage.SPEAK)
        self.assertEqual(MIGRATION_MAP[LEGACY_UTTERANCE], SpecMessage.UTTERANCE)

    # -- modernize: legacy producer reaches a spec listener -----------------

    def test_legacy_emit_reaches_spec_listener(self) -> None:
        """A component emitting a LEGACY topic is received on the ovos.* SPEC
        topic (modernize bridging)."""
        bus = FakeBus()  # both flags default on
        spec_seen = _collect(bus, SPEC_SPEAK)

        bus.emit(Message(LEGACY_SPEAK, {"utterance": "hello"}))

        self.assertEqual(len(spec_seen), 1)
        self.assertEqual(spec_seen[0].msg_type, SPEC_SPEAK)
        self.assertEqual(spec_seen[0].data["utterance"], "hello")

    def test_legacy_utterance_reaches_spec_listener(self) -> None:
        """recognizer_loop:utterance is delivered on ovos.utterance.handle."""
        bus = FakeBus()
        spec_seen = _collect(bus, SPEC_UTTERANCE)

        bus.emit(Message(LEGACY_UTTERANCE, {"utterances": ["turn on the light"]}))

        self.assertEqual(len(spec_seen), 1)
        self.assertEqual(spec_seen[0].data["utterances"], ["turn on the light"])

    # -- emit_legacy: spec producer reaches a legacy listener ---------------

    def test_spec_emit_reaches_legacy_listener(self) -> None:
        """A component emitting the SPEC topic is received by a LEGACY listener
        (emit_legacy bridging)."""
        bus = FakeBus()
        legacy_seen = _collect(bus, LEGACY_SPEAK)

        bus.emit(Message(SPEC_SPEAK, {"utterance": "goodbye"}))

        self.assertEqual(len(legacy_seen), 1)
        self.assertEqual(legacy_seen[0].msg_type, LEGACY_SPEAK)
        self.assertEqual(legacy_seen[0].data["utterance"], "goodbye")

    # -- dedup: a handler on BOTH topics fires once -------------------------

    def test_handler_on_both_topics_fires_once(self) -> None:
        """A handler subscribed to BOTH the legacy and the spec topic fires once
        per real event (the mirror is dropped)."""
        bus = FakeBus()
        calls = []

        def handler(message=None):
            calls.append(message.msg_type)

        bus.on(LEGACY_SPEAK, handler)
        bus.on(SPEC_SPEAK, handler)

        bus.emit(Message(LEGACY_SPEAK, {"utterance": "once"}))

        self.assertEqual(len(calls), 1,
                         f"dual-subscribed handler fired {len(calls)}x: {calls}")

    def test_two_genuine_events_each_fire(self) -> None:
        """Dedup must not swallow two genuine events. A SINGLE handler on both
        topics fires exactly once per real event, never zero."""
        bus = FakeBus()
        calls = []

        def handler(message=None):
            calls.append(message.data.get("utterance"))

        bus.on(LEGACY_SPEAK, handler)
        bus.on(SPEC_SPEAK, handler)

        bus.emit(Message(LEGACY_SPEAK, {"utterance": "first"}))
        bus.emit(Message(LEGACY_SPEAK, {"utterance": "second"}))

        # shared mirror-guard dedupes each event's counterpart -> two calls
        self.assertEqual(calls, ["first", "second"])

    # -- single-namespace isolation (no bridging) ---------------------------

    def test_no_bridging_isolates_namespaces(self) -> None:
        """FakeBus(modernize=False, emit_legacy=False) keeps each namespace
        isolated, proving the harness can exercise ONE namespace explicitly."""
        bus = FakeBus(modernize=False, emit_legacy=False)
        spec_seen = _collect(bus, SPEC_SPEAK)
        legacy_seen = _collect(bus, LEGACY_SPEAK)

        bus.emit(Message(LEGACY_SPEAK, {"utterance": "legacy only"}))
        bus.emit(Message(SPEC_SPEAK, {"utterance": "spec only"}))

        # legacy listener saw only the legacy emit; spec listener only the spec
        self.assertEqual([m.data["utterance"] for m in legacy_seen], ["legacy only"])
        self.assertEqual([m.data["utterance"] for m in spec_seen], ["spec only"])

    def test_modernize_only_does_not_emit_legacy(self) -> None:
        """modernize=True, emit_legacy=False: legacy->spec bridges but spec->legacy
        does not."""
        bus = FakeBus(modernize=True, emit_legacy=False)
        spec_seen = _collect(bus, SPEC_SPEAK)
        legacy_seen = _collect(bus, LEGACY_SPEAK)

        bus.emit(Message(LEGACY_SPEAK, {"utterance": "x"}))   # bridges -> spec
        bus.emit(Message(SPEC_SPEAK, {"utterance": "y"}))     # must NOT -> legacy

        self.assertEqual([m.data["utterance"] for m in spec_seen], ["x", "y"])
        self.assertEqual([m.data["utterance"] for m in legacy_seen], ["x"])


if __name__ == "__main__":
    unittest.main()
