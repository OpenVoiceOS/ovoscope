"""Loud guards for the intent-topic legacy-compat contract.

The canonical intent dispatch topic is ``<skill_id>:<intent_name>`` — no
``.intent`` suffix, that suffix is authoring-file leakage from
``register_intent_file`` (see ``ovos_workshop.skills.ovos.OVOSSkill.
register_intent_file``, which today builds the bus subscription name as
``f'{self.skill_id}:{intent_file}'`` where ``intent_file`` still carries the
``.intent`` suffix).

Latest ovos-workshop is spec-pure: it dispatches (and registers) only the
canonical form. ALL backwards compat for still-running old-workshop
consumers lives in ovos-spec-tools:

* registration normalization — a handler registered under the suffixed
  legacy name is normalized to canonical and deduped against a handler
  already registered under the canonical name.
* an ``emit_legacy``-gated re-emission of the ``.intent``-suffixed twin,
  alias-driven: only for intents that were actually registered under the
  legacy name, so old containerized skills subscribing to ``X:Y.intent``
  over the wire keep working.

None of that lives in ovos-spec-tools / ovos-workshop yet (the PR pair is
in preparation). Every assertion that depends on it is marked
``xfail(strict=True)`` so:

* right now the suite is green (the not-yet-implemented behavior is an
  *expected* failure), and
* the moment the PR pair lands, the assertion starts passing, ``strict=True``
  turns that XPASS into a hard failure, and that loud failure is the signal
  to delete the xfail marker and promote the test to a permanent compat
  guard — the guard that must catch a *later* silent removal of the compat.

Cases that are already true of the *current* (pre-migration) stack are
asserted plainly, without xfail — they don't need the PR pair, they need
the plumbing that already exists today.
"""
import time
from types import SimpleNamespace

import pytest

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_workshop.skills.ovos import OVOSSkill

from ovoscope import get_minicroft

SKILL_ID = "ovoscope-intent-legacy-compat.test"
INTENT_NAME = "LegacyIntent"
CANONICAL_TOPIC = f"{SKILL_ID}:{INTENT_NAME}"
LEGACY_TOPIC = f"{CANONICAL_TOPIC}.intent"

_XFAIL_REASON = ("pending ovos-spec-tools intent-topic compat helpers "
                 "(PR pair)")


class LegacyRegisteredSkill(OVOSSkill):
    """A stand-in for an old, un-migrated containerized skill: it registers
    its intent handler under the suffixed ``.intent`` topic, exactly what
    ``register_intent_file`` does on the currently installed ovos-workshop.
    We wire it with ``add_event`` directly (skipping the padatious resource
    file) so the fixture stays a MiniCroft boot, not a full skill-resource
    fixture."""

    def initialize(self):
        self.add_event(LEGACY_TOPIC, self.handle_legacy,
                       'mycroft.skill.handler', activation=True,
                       is_intent=True)

    def handle_legacy(self, message: Message):
        pass


def _enable_emit_legacy():
    """Best-effort toggle for the (not-yet-existing) ``emit_legacy`` compat
    knob. Until ovos-spec-tools ships it this is a no-op — the re-emitted
    twin below simply never appears, which is exactly the behavior
    ``test_legacy_twin_reemitted_when_compat_enabled`` pins as xfail."""
    try:
        from ovos_config.config import Configuration
        Configuration().setdefault("intent_topic_compat", {})["emit_legacy"] = True
    except Exception:
        pass


def _disable_emit_legacy():
    try:
        from ovos_config.config import Configuration
        Configuration().setdefault("intent_topic_compat", {})["emit_legacy"] = False
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. Re-emission of the suffixed twin (real emission path, MiniCroft)
# ---------------------------------------------------------------------------
@pytest.mark.timeout(600)  # boots a real MiniCroft (slow shutdown)
class TestLegacyTwinReemission:
    """One MiniCroft boot, shared by all methods below — a legacy-registered
    consumer skill is loaded once and each test observes the bus around a
    canonical dispatch."""

    @classmethod
    def setup_class(cls):
        LOG.set_level("ERROR")
        cls.mc = get_minicroft([SKILL_ID],
                               extra_skills={SKILL_ID: LegacyRegisteredSkill})

    @classmethod
    def teardown_class(cls):
        cls.mc.stop()
        LOG.set_level("CRITICAL")

    def test_direct_legacy_dispatch_still_fires_the_handler(self):
        """Sanity / positive control: today's plumbing already delivers a
        message straight to the suffixed topic a legacy consumer listens
        on — no compat needed for this, it's the plain current wiring."""
        hits = []
        self.mc.bus.on(LEGACY_TOPIC, hits.append)
        try:
            self.mc.bus.emit(Message(LEGACY_TOPIC, {"food": "tacos"}))
            time.sleep(0.3)
            assert len(hits) == 1
            assert hits[0].data == {"food": "tacos"}
        finally:
            self.mc.bus.remove(LEGACY_TOPIC, hits.append)

    @pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
    def test_legacy_twin_reemitted_when_compat_enabled(self):
        """A canonical dispatch must re-emit the suffixed ``.intent`` twin
        for the still-registered legacy consumer, carrying identical data
        and context, exactly once."""
        _enable_emit_legacy()
        twin_hits = []
        self.mc.bus.on(LEGACY_TOPIC, twin_hits.append)
        try:
            msg = Message(CANONICAL_TOPIC, {"food": "tacos"},
                         {"session": "legacy-twin-session"})
            self.mc.bus.emit(msg)
            time.sleep(0.5)
            assert len(twin_hits) == 1, (
                f"expected exactly one re-emitted legacy twin on "
                f"{LEGACY_TOPIC!r}, got {len(twin_hits)}"
            )
            assert twin_hits[0].data == msg.data
            assert twin_hits[0].context.get("session") == "legacy-twin-session"
        finally:
            self.mc.bus.remove(LEGACY_TOPIC, twin_hits.append)
            _disable_emit_legacy()

    def test_no_twin_when_compat_disabled(self):
        """Paired negative control for the case above: with the compat knob
        off (its default — nothing implements ``emit_legacy`` yet), only
        the canonical topic is observed. The canonical listener firing is
        the positive control that proves the dispatch actually happened;
        the suffixed twin must NOT appear."""
        _disable_emit_legacy()
        canonical_hits = []
        twin_hits = []
        self.mc.bus.on(CANONICAL_TOPIC, canonical_hits.append)
        self.mc.bus.on(LEGACY_TOPIC, twin_hits.append)
        try:
            msg = Message(CANONICAL_TOPIC, {"food": "burritos"})
            self.mc.bus.emit(msg)
            time.sleep(0.3)
            assert len(canonical_hits) == 1, "canonical dispatch did not arrive"
            assert twin_hits == [], (
                "a legacy .intent twin was emitted even though compat is off"
            )
        finally:
            self.mc.bus.remove(CANONICAL_TOPIC, canonical_hits.append)
            self.mc.bus.remove(LEGACY_TOPIC, twin_hits.append)


# ---------------------------------------------------------------------------
# 2. Registration normalization + dedup (spec-tools unit level, FakeBus)
# ---------------------------------------------------------------------------
class TestRegistrationNormalizationDedup:
    """Registering a handler for ``X:Y.intent`` through the current stack
    must still fire on a canonical ``X:Y`` dispatch — and firing twice
    (once registered suffixed, once canonical) must not double-fire.
    Lightest fixture: FakeBus only, no MiniCroft boot needed since this
    pins a pure normalization/dedup helper, not the wire-level emission
    path exercised above."""

    @pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
    def test_legacy_registration_fires_on_canonical_dispatch(self):
        from ovos_spec_tools.intent_compat import normalize_intent_registration

        bus = FakeBus()
        hits = []
        name = normalize_intent_registration(LEGACY_TOPIC)
        assert name == CANONICAL_TOPIC, (
            f"legacy registration name was not normalized to canonical: "
            f"{name!r}"
        )
        bus.on(name, hits.append)
        bus.emit(Message(CANONICAL_TOPIC, {"x": 1}))
        assert len(hits) == 1

    @pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
    def test_dual_registration_does_not_double_fire(self):
        """Registering both the canonical and the legacy-suffixed form for
        the same intent must dedupe to a single dispatch."""
        from ovos_spec_tools.intent_compat import normalize_intent_registration

        bus = FakeBus()
        hits = []
        bus.on(normalize_intent_registration(CANONICAL_TOPIC), hits.append)
        bus.on(normalize_intent_registration(LEGACY_TOPIC), hits.append)
        bus.emit(Message(CANONICAL_TOPIC, {"x": 1}))
        assert len(hits) == 1, (
            "registering both the canonical and legacy forms caused a "
            "double dispatch"
        )


if __name__ == "__main__":
    import unittest
    unittest.main()
