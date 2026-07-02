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
"""Pipeline plugin test harness for ovoscope.

Tests intent / pipeline plugins in isolation — no full skill is needed.
The harness loads the specified pipeline stages on a :class:`MiniCroft`
that has a single internal sink skill to absorb matched intents.

Example::

    from ovoscope.pipeline import PipelineHarness

    with PipelineHarness(pipeline=["ovos-adapt-pipeline-plugin.openvoiceos"]) as harness:
        msg = harness.assert_matches("turn on the lights", intent_type="LightsOnIntent")
        harness.assert_no_match("garbled nonsense xyz 123")
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ovos_utils.messagebus import Message


class _SinkSkill:
    """Internal catch-all fallback skill so matched intents have somewhere to route.

    This is injected into MiniCroft as ``__ovoscope_sink__`` and registers a
    handler that captures the incoming message so ``PipelineHarness`` can
    return it from :meth:`match`.
    """

    def __init__(self, bus: Optional[Any] = None, skill_id: str = "__ovoscope_sink__") -> None:
        from ovos_utils.fakebus import FakeBus

        self.skill_id = skill_id
        self._last_match: Optional[Message] = None
        self._bus: Any = bus if bus is not None else FakeBus()
        self._bus.on("intent.service.skills.activated", self._handle)
        self._bus.on("intent_failure", self._handle_failure)

    @property
    def bus(self) -> Any:
        return self._bus

    @bus.setter
    def bus(self, new_bus: Any) -> None:
        if new_bus is None:
            raise ValueError("_SinkSkill.bus cannot be None; pass a real bus or omit to default to FakeBus.")
        # Detach handlers from the previous bus before rebinding.
        try:
            self._bus.remove("intent.service.skills.activated", self._handle)
            self._bus.remove("intent_failure", self._handle_failure)
        except Exception:
            pass
        self._bus = new_bus
        new_bus.on("intent.service.skills.activated", self._handle)
        new_bus.on("intent_failure", self._handle_failure)

    def _handle(self, message: Any) -> None:
        """Capture matched intent messages."""
        if isinstance(message, str):
            try:
                message = Message.deserialize(message)
            except Exception:
                return
        self._last_match = message

    def _handle_failure(self, message: Any) -> None:
        """Record explicit intent failures."""
        if isinstance(message, str):
            try:
                message = Message.deserialize(message)
            except Exception:
                return
        # Failures are tracked by absence of _last_match.


class PipelineHarness:
    """Load pipeline plugins and assert utterance matching without skills.

    Args:
        pipeline: List of OPM pipeline stage IDs to load.
        pipeline_config: Per-stage config overrides keyed by stage ID.
        lang: Language tag (default ``"en-US"``).
        modernize: Forwarded to the harness ``MiniCroft`` / ``FakeBus``. When
            on (default), emitting a LEGACY topic also dispatches its ovos.*
            spec counterpart (legacy producer -> spec listener). Utterances are
            injected via ``recognizer_loop:utterance``; bridging lets them also
            drive / be observed on ``ovos.utterance.handle``.
        emit_legacy: Forwarded to the harness. When on (default), emitting an
            ovos.* spec topic also dispatches the legacy one (spec producer ->
            legacy listener). Set BOTH False to exercise a single namespace
            with no cross-namespace bridging.

    Example::

        with PipelineHarness(
            pipeline=["ovos-padatious-pipeline-plugin.openvoiceos"],
            lang="en-US",
        ) as harness:
            msg = harness.assert_matches("what time is it")
            harness.assert_no_match("frobble zorp snork")
    """

    def __init__(
        self,
        pipeline: Optional[List[str]] = None,
        pipeline_config: Optional[Dict[str, Dict[str, Any]]] = None,
        lang: str = "en-US",
        modernize: bool = True,
        emit_legacy: bool = True,
    ) -> None:
        self.pipeline: List[str] = pipeline or []
        self.pipeline_config: Dict[str, Dict[str, Any]] = pipeline_config or {}
        self.lang: str = lang
        self.modernize: bool = modernize
        self.emit_legacy: bool = emit_legacy
        self._mc: Any = None

    # ------------------------------------------------------------------
    # Context manager interface
    # ------------------------------------------------------------------

    def __enter__(self) -> "PipelineHarness":
        """Start MiniCroft with the specified pipeline and no skills."""
        from ovoscope import get_minicroft

        # Inject internal sink skill to capture matched intents.
        # Constructed with a default FakeBus; rebound to MiniCroft's real bus below.
        sink_skill = _SinkSkill()

        self._mc = get_minicroft(
            skill_ids=[],
            lang=self.lang,
            default_pipeline=self.pipeline or None,
            extra_skills={"__ovoscope_sink__": sink_skill},
            max_wait=60,
            modernize=self.modernize,
            emit_legacy=self.emit_legacy,
        )

        # Update sink skill's bus reference now that MiniCroft is created
        if self._mc is not None:
            sink_skill.bus = self._mc.bus

        return self

    def __exit__(self, *_: Any) -> None:
        """Shut down MiniCroft."""
        if self._mc is not None:
            self._mc.stop()
            self._mc = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match(self, utterance: str, timeout: float = 5.0) -> Optional[Message]:
        """Send *utterance* through the pipeline and return the matched message.

        Args:
            utterance: Text utterance to send.
            timeout: Seconds to wait for a match (default 5.0).

        Returns:
            The ``recognizer_loop:utterance`` response message if a match occurs,
            otherwise ``None``.
        """
        if self._mc is None:
            raise RuntimeError("PipelineHarness must be used as a context manager.")

        import threading

        captured: List[Message] = []
        _matched = threading.Event()
        _failed = threading.Event()

        success_type = "intent.service.skills.activated"
        failure_types = ["intent_failure", "mycroft.skill.handler.start"]

        def _on_success(msg: Any) -> None:
            if isinstance(msg, str):
                try:
                    msg = Message.deserialize(msg)
                except Exception:
                    return
            captured.append(msg)
            _matched.set()

        def _on_failure(msg: Any) -> None:
            _failed.set()

        self._mc.bus.on(success_type, _on_success)
        for et in failure_types:
            self._mc.bus.on(et, _on_failure)

        src = Message(
            "recognizer_loop:utterance",
            data={"utterances": [utterance], "lang": self.lang},
        )
        self._mc.bus.emit(src)

        # Wait for either a match or a failure signal
        import threading as _threading
        done = _threading.Event()

        def _wait_either() -> None:
            while not _matched.is_set() and not _failed.is_set():
                _matched.wait(timeout=0.05)
                if _matched.is_set() or _failed.is_set():
                    break
            done.set()

        watcher = _threading.Thread(target=_wait_either, daemon=True)
        watcher.start()
        timed_out = not done.wait(timeout=timeout)

        self._mc.bus.remove(success_type, _on_success)
        for et in failure_types:
            self._mc.bus.remove(et, _on_failure)

        if timed_out:
            return None
        if _failed.is_set():
            return None
        return captured[0] if captured else None

    def assert_matches(
        self,
        utterance: str,
        intent_type: Optional[str] = None,
        timeout: float = 5.0,
    ) -> Message:
        """Assert that *utterance* is matched by the pipeline.

        Args:
            utterance: Text utterance to test.
            intent_type: If provided, the matched intent ``type`` must contain
                this substring.
            timeout: Seconds to wait for a match.

        Returns:
            The matched :class:`Message`.

        Raises:
            AssertionError: If no match is found or the intent type is wrong.
        """
        msg = self.match(utterance, timeout=timeout)
        assert msg is not None, (
            f"Expected utterance {utterance!r} to be matched by the pipeline, but no match occurred."
        )
        if intent_type is not None:
            assert intent_type in (msg.msg_type or ""), (
                f"Expected intent type to contain {intent_type!r}, got {msg.msg_type!r}"
            )
        return msg

    def assert_no_match(self, utterance: str, timeout: float = 2.0) -> None:
        """Assert that *utterance* is NOT matched by the pipeline.

        Args:
            utterance: Text utterance that should produce no match.
            timeout: Seconds to observe before asserting absence (default 2.0).

        Raises:
            AssertionError: If a match is unexpectedly found.
        """
        msg = self.match(utterance, timeout=timeout)
        if msg is not None and msg.msg_type != "intent_failure":
            raise AssertionError(
                f"Utterance {utterance!r} was unexpectedly matched: {msg.msg_type!r}"
            )
