"""End-to-end test scaffolding for ConfidenceMatcherPipeline plugins.

Most pipeline plugins (Adapt, Padatious, Padacioso, Nebulento, Palavreado, …)
need the same end-to-end shape:

1. Mutate ``Configuration()["intents"][<config_key>]`` with a per-test config.
2. Spin up a ``MiniCroft`` pinned to that one pipeline.
3. Drive the bus with utterances and capture the dispatched intent message
   (or the ``complete_intent_failure`` signal).
4. Tear everything down without leaking state into the next test class.

This module factors out that shape so a plugin only has to subclass
``E2EPipelineHarness`` and declare a handful of class attributes.  It also
exposes the standalone bus helpers (``wait_for_match``,
``make_utterance_message``, …) and engine-family registration shims
(``register_padatious_intent``, ``register_adapt_intent``, …) for the cases
where pytest-style tests are preferred over ``unittest``.
"""
from __future__ import annotations

import threading
import time
import unittest
from typing import Any, ClassVar, Dict, List, Optional

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_config.config import Configuration


# ---------------------------------------------------------------------------
# Standalone bus helpers (work with any FakeBus / MessageBusClient)
# ---------------------------------------------------------------------------

def make_session(
    session_id: str = "ovoscope-test",
    *,
    pipeline: Optional[List[str]] = None,
    blacklisted_intents: Optional[List[str]] = None,
    blacklisted_skills: Optional[List[str]] = None,
    lang: str = "en-US",
) -> Session:
    """Build a ``Session`` with the most common overrides preset."""
    kwargs: Dict[str, Any] = {"session_id": session_id, "lang": lang}
    if pipeline is not None:
        kwargs["pipeline"] = pipeline
    if blacklisted_intents is not None:
        kwargs["blacklisted_intents"] = blacklisted_intents
    if blacklisted_skills is not None:
        kwargs["blacklisted_skills"] = blacklisted_skills
    return Session(**kwargs)


def make_utterance_message(
    utterance: str,
    *,
    lang: str = "en-US",
    session: Optional[Session] = None,
) -> Message:
    """Build a ``recognizer_loop:utterance`` Message, optional Session override."""
    ctx: Dict[str, Any] = {}
    if session is not None:
        ctx["session"] = session.serialize()
    return Message(
        "recognizer_loop:utterance",
        data={"utterances": [utterance], "lang": lang},
        context=ctx,
    )


def wait_for_match(
    bus,
    expected_types: List[str],
    *,
    timeout: float = 5.0,
) -> Optional[Message]:
    """Subscribe to ``expected_types`` and ``complete_intent_failure``; return
    the first match Message, or ``None`` on failure / timeout.

    The caller is responsible for emitting the utterance *after* calling this
    helper if used in a pytest style — for the ``unittest`` style use
    :meth:`E2EPipelineHarness.send_and_capture` which emits internally.
    """
    got: List[Message] = []
    done = threading.Event()
    failed = threading.Event()

    def _on_match(msg: Message) -> None:
        got.append(msg)
        done.set()

    def _on_fail(_msg: Message) -> None:
        failed.set()
        done.set()

    for t in expected_types:
        bus.on(t, _on_match)
    bus.on("complete_intent_failure", _on_fail)
    try:
        done.wait(timeout=timeout)
    finally:
        for t in expected_types:
            bus.remove(t, _on_match)
        bus.remove("complete_intent_failure", _on_fail)
    if failed.is_set() and not got:
        return None
    return got[0] if got else None


def wait_for_failure(bus, *, timeout: float = 2.0) -> bool:
    """Wait for a ``complete_intent_failure`` Message; return whether one fired."""
    failed = threading.Event()

    def _on_fail(_msg: Message) -> None:
        failed.set()

    bus.on("complete_intent_failure", _on_fail)
    try:
        failed.wait(timeout=timeout)
    finally:
        bus.remove("complete_intent_failure", _on_fail)
    return failed.is_set()


# ---------------------------------------------------------------------------
# Intent-registration shims — emit the bus event a given engine family expects
# ---------------------------------------------------------------------------
#
# Padatious family (padatious, padacioso, nebulento, …) — registers intents by
# emitting ``padatious:register_intent`` with inline ``samples``.
# Adapt family (adapt, palavreado, …) — registers vocab + IntentBuilder.

def register_padatious_intent(
    bus, name: str, samples: List[str], *, lang: str = "en-US",
    settle: float = 0.1,
) -> None:
    bus.emit(Message("padatious:register_intent", {
        "name": name, "samples": samples, "lang": lang,
    }))
    if settle:
        time.sleep(settle)


def register_padatious_entity(
    bus, name: str, samples: List[str], *, lang: str = "en-US",
    settle: float = 0.1,
) -> None:
    bus.emit(Message("padatious:register_entity", {
        "name": name, "samples": samples, "lang": lang,
    }))
    if settle:
        time.sleep(settle)


def register_adapt_vocab(
    bus, entity_type: str, words: List[str], *, lang: str = "en-US",
    settle: float = 0.1,
) -> None:
    for word in words:
        bus.emit(Message("register_vocab", {
            "entity_value": word, "entity_type": entity_type, "lang": lang,
        }))
    if settle:
        time.sleep(settle)


def register_adapt_intent(bus, builder, *, lang: str = "en-US",
                          settle: float = 0.1) -> None:
    """Register an Adapt intent.

    ``builder`` may be an ``IntentBuilder`` (will be ``.build()``-ed) or an
    already-built intent with a ``__dict__`` payload.
    """
    intent = builder.build() if hasattr(builder, "build") else builder
    msg = Message("register_intent", intent.__dict__)
    msg.context["lang"] = lang
    bus.emit(msg)
    if settle:
        time.sleep(settle)


def detach_intent(bus, intent_name: str, *, settle: float = 0.1) -> None:
    bus.emit(Message("detach_intent", {"intent_name": intent_name}))
    if settle:
        time.sleep(settle)


def detach_skill(bus, skill_id: str, *, settle: float = 0.1) -> None:
    bus.emit(Message("detach_skill", {"skill_id": skill_id}))
    if settle:
        time.sleep(settle)


# ---------------------------------------------------------------------------
# unittest.TestCase harness
# ---------------------------------------------------------------------------

class E2EPipelineHarness(unittest.TestCase):
    """Base class for end-to-end tests of a single pipeline plugin.

    Subclass and set the four class attributes:

    ``PIPELINE_ID``
        OPM ``opm.pipeline`` entry-point name to pin MiniCroft to
        (e.g. ``"ovos-nebulento-pipeline-plugin"``).
    ``CONFIG_KEY``
        Key under ``Configuration()["intents"]`` for plugin config.
    ``PLUGIN_CONFIG``
        Dict merged into ``Configuration()["intents"][CONFIG_KEY]`` before
        MiniCroft starts.  Restored on teardown.
    ``SKILL_ID``
        Skill id used by helpers when registering intents.  Detached in
        ``setUp`` to keep tests isolated.

    The harness then exposes:

    - ``self.mc``           — the running ``MiniCroft``
    - ``self.bus``          — shortcut to ``self.mc.bus``
    - ``self.pipeline``     — the loaded pipeline plugin instance
    - ``self.send_and_capture(utterance, expected_types, …)``
    - ``self.expect_no_match(utterance, …)``
    - ``self.make_utterance(utterance, session=…)``
    """

    PIPELINE_ID: ClassVar[str] = ""
    CONFIG_KEY: ClassVar[str] = ""
    PLUGIN_CONFIG: ClassVar[Dict[str, Any]] = {}
    SKILL_ID: ClassVar[str] = "test_skill_ovoscope"
    DEFAULT_LANG: ClassVar[str] = "en-US"
    STARTUP_MAX_WAIT: ClassVar[float] = 60.0

    mc: ClassVar[Any]
    pipeline: ClassVar[Any]
    _orig_intents_cfg: ClassVar[Any] = None

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.PIPELINE_ID or not cls.CONFIG_KEY:
            raise unittest.SkipTest(
                f"{cls.__name__} must set PIPELINE_ID and CONFIG_KEY"
            )
        # Import here so importing this module does not pull in MiniCroft.
        from ovoscope import get_minicroft

        cfg = Configuration()
        intents_cfg = cfg.setdefault("intents", {})
        cls._orig_intents_cfg = intents_cfg.get(cls.CONFIG_KEY)
        intents_cfg[cls.CONFIG_KEY] = dict(cls.PLUGIN_CONFIG or {})

        cls.mc = get_minicroft(
            skill_ids=[],
            lang=cls.DEFAULT_LANG,
            default_pipeline=[cls.PIPELINE_ID],
            max_wait=cls.STARTUP_MAX_WAIT,
        )
        cls.pipeline = cls.mc.intents.pipeline_plugins[cls.PIPELINE_ID]

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.mc.stop()
        finally:
            cfg = Configuration()
            intents_cfg = cfg.get("intents", {})
            if cls._orig_intents_cfg is None:
                intents_cfg.pop(cls.CONFIG_KEY, None)
            else:
                intents_cfg[cls.CONFIG_KEY] = cls._orig_intents_cfg

    @property
    def bus(self):
        return self.mc.bus

    def setUp(self) -> None:
        # Isolate tests by detaching this skill_id's registrations.
        detach_skill(self.bus, self.SKILL_ID)

    # -- helpers --------------------------------------------------------

    def make_utterance(self, utterance: str, *,
                       session: Optional[Session] = None) -> Message:
        return make_utterance_message(
            utterance, lang=self.DEFAULT_LANG, session=session
        )

    def send_and_capture(
        self,
        utterance: str,
        expected_types: List[str],
        *,
        timeout: float = 5.0,
        session: Optional[Session] = None,
    ) -> Optional[Message]:
        """Emit ``utterance`` and return the first match Message (or None)."""
        got: List[Message] = []
        done = threading.Event()
        failed = threading.Event()

        def _on_match(msg: Message) -> None:
            got.append(msg)
            done.set()

        def _on_fail(_msg: Message) -> None:
            failed.set()
            done.set()

        for t in expected_types:
            self.bus.on(t, _on_match)
        self.bus.on("complete_intent_failure", _on_fail)
        try:
            self.bus.emit(self.make_utterance(utterance, session=session))
            done.wait(timeout=timeout)
        finally:
            for t in expected_types:
                self.bus.remove(t, _on_match)
            self.bus.remove("complete_intent_failure", _on_fail)
        if failed.is_set() and not got:
            return None
        return got[0] if got else None

    def expect_no_match(
        self,
        utterance: str,
        *,
        timeout: float = 2.0,
        session: Optional[Session] = None,
    ) -> None:
        """Assert that emitting ``utterance`` produces a ``complete_intent_failure``."""
        failed = threading.Event()

        def _on_fail(_msg: Message) -> None:
            failed.set()

        self.bus.on("complete_intent_failure", _on_fail)
        try:
            self.bus.emit(self.make_utterance(utterance, session=session))
            failed.wait(timeout=timeout)
        finally:
            self.bus.remove("complete_intent_failure", _on_fail)
        self.assertTrue(
            failed.is_set(),
            f"Expected no match for {utterance!r} but no "
            f"complete_intent_failure was emitted.",
        )


__all__ = [
    # bus helpers
    "make_session",
    "make_utterance_message",
    "wait_for_match",
    "wait_for_failure",
    # registration shims
    "register_padatious_intent",
    "register_padatious_entity",
    "register_adapt_vocab",
    "register_adapt_intent",
    "detach_intent",
    "detach_skill",
    # harness
    "E2EPipelineHarness",
]
