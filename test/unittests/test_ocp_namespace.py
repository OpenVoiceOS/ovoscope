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
"""Namespace-bridging tests for the OCP harness (ovoscope.ocp.OCPTest).

OCPTest drives the OCP query flow by emitting the LEGACY
``recognizer_loop:utterance`` topic into a MiniCroft. These tests pin that the
harness FakeBus bridges that topic to/from the ovos.* SPEC topic
(``ovos.utterance.handle``) so an OCP test can deliberately exercise EITHER
namespace, and that disabling the bridge isolates a single namespace.

The OCP query/response path itself is covered elsewhere; here we assert only the
namespace plumbing OCPTest threads into the harness, driving the SAME real
utterance topic OCPTest emits.
"""

import importlib.util
import threading
import unittest

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage

from ovoscope.ocp import OCPTest

# OCPTest spins up a full MiniCroft; gate on ovos-core being importable.
CORE_AVAILABLE = importlib.util.find_spec("ovos_core") is not None

LEGACY_UTTERANCE = "recognizer_loop:utterance"
SPEC_UTTERANCE = str(SpecMessage.UTTERANCE)  # ovos.utterance.handle


class TestOCPTestNamespaceFields(unittest.TestCase):
    """The bridging flags are exposed on OCPTest and default on (no extra deps)."""

    def test_defaults_on(self) -> None:
        t = OCPTest(skill_ids=[], utterance="play jazz")
        self.assertTrue(t.modernize)
        self.assertTrue(t.emit_legacy)

    def test_flags_settable(self) -> None:
        t = OCPTest(skill_ids=[], utterance="play jazz",
                    modernize=False, emit_legacy=False)
        self.assertFalse(t.modernize)
        self.assertFalse(t.emit_legacy)


@unittest.skipUnless(CORE_AVAILABLE, "ovos-core not installed")
class TestOCPTestNamespaceBridging(unittest.TestCase):
    """Drive the real OCP utterance topic on a harness MiniCroft and assert the
    legacy<->spec bridge OCPTest relies on."""

    def _make_mc(self, **kwargs):
        from ovoscope import get_minicroft
        return get_minicroft([], lang="en-US", max_wait=60, **kwargs)

    def _emit_and_collect(self, mc, emit_topic, watch_topic, *, timeout=3.0):
        seen = []
        got = threading.Event()

        def _on(msg):
            if isinstance(msg, str):
                msg = Message.deserialize(msg)
            seen.append(msg)
            got.set()

        mc.bus.on(watch_topic, _on)
        try:
            mc.bus.emit(Message(
                emit_topic,
                data={"utterances": ["play some jazz"], "lang": "en-US"},
            ))
            got.wait(timeout)
        finally:
            mc.bus.remove(watch_topic, _on)
        return seen

    def test_legacy_utterance_observed_on_spec_topic(self) -> None:
        """Default (bridging on): OCPTest's legacy recognizer_loop:utterance is
        observed on the spec ovos.utterance.handle topic (modernize)."""
        mc = self._make_mc()  # modernize/emit_legacy default on
        try:
            seen = self._emit_and_collect(mc, LEGACY_UTTERANCE, SPEC_UTTERANCE)
            self.assertTrue(seen, "legacy utterance was not bridged to the spec topic")
            self.assertEqual(seen[0].data["utterances"], ["play some jazz"])
        finally:
            mc.stop()

    def test_spec_utterance_reaches_legacy_listener(self) -> None:
        """An utterance emitted on the SPEC topic reaches a LEGACY listener
        (emit_legacy) — the OCP query path keys off the legacy topic."""
        mc = self._make_mc()
        try:
            seen = self._emit_and_collect(mc, SPEC_UTTERANCE, LEGACY_UTTERANCE)
            self.assertTrue(seen, "spec utterance was not bridged to the legacy topic")
            self.assertEqual(seen[0].data["utterances"], ["play some jazz"])
        finally:
            mc.stop()

    def test_no_bridging_isolates_legacy_from_spec(self) -> None:
        """With bridging OFF, a legacy emit does NOT reach a spec-only
        subscriber — OCPTest(modernize=False, emit_legacy=False) exercises a
        single namespace."""
        mc = self._make_mc(modernize=False, emit_legacy=False)
        try:
            seen = self._emit_and_collect(mc, LEGACY_UTTERANCE, SPEC_UTTERANCE,
                                          timeout=0.5)
            self.assertEqual(seen, [],
                             "legacy emit must not reach the spec topic when bridging is off")
        finally:
            mc.stop()


if __name__ == "__main__":
    unittest.main()
