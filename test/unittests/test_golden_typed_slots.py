"""OVOS-INTENT-1 §5.6: the golden runner passes the typed-slot map.

"An engine MAY use the map to constrain where ``{type:name}`` matches —
preferring or requiring a span the map lists for that type — and MAY
report the corresponding normalized value alongside the match."

A golden suite can only prove that MAY if the runner (a) tells the
fighter which slots are typed, the way a skill registration does
(``slot_types``), and (b) puts the map ovos-typed-slots-transformer
computes into ``recognizer_loop:utterance`` ``data['typed_slots']``,
the way the real intent service does. ovos-padatious 2.2 binds from the
map; padacioso does not read it (conformant under the MAY).
"""
import tempfile
from pathlib import Path
from unittest import TestCase

from ovoscope.golden import (FIGHTERS, GenericOPMAdapter, GoldenRow,
                              build_engine_intents, build_engine_slot_types,
                              compute_typed_slots, run_golden_suite,
                              typed_slots_available)

SKILL_ID = "typed-skill.test"
LANG = "en-US"
TEMPLATE = "set the brightness to {number:b}\n"
UTTERANCE = "set the brightness to twenty five please"


def _resources():
    td = tempfile.TemporaryDirectory()
    lang_dir = Path(td.name) / LANG
    lang_dir.mkdir(parents=True)
    (lang_dir / "brightness.intent").write_text(TEMPLATE, encoding="utf-8")
    return td


class TestBuildEngineSlotTypes(TestCase):
    def test_declared_types_come_from_the_raw_lines(self):
        with _resources() as td:
            intents = build_engine_intents(Path(td), LANG)
            slot_types = build_engine_slot_types(Path(td), LANG)
        # the expanded lines are bare (the §3.4 degrade)...
        self.assertEqual(intents, {"brightness": ["set the brightness to {b}"]})
        # ...and the declared types survive beside them
        self.assertEqual(slot_types, {"brightness": {"b": "number"}})


class TestTransformerMap(TestCase):
    def test_transformer_is_installed_in_this_venv(self):
        self.assertTrue(typed_slots_available())

    def test_compute_typed_slots_lists_the_number_span(self):
        typed = compute_typed_slots(UTTERANCE, LANG, frozenset({"number"}))
        self.assertIn("number", typed)
        entry = typed["number"][0]
        self.assertEqual(UTTERANCE[entry["span"][0]:entry["span"][1]], entry["surface"])
        self.assertEqual(entry["value"], 25)

    def test_no_declared_types_gives_no_map(self):
        self.assertEqual(compute_typed_slots(UTTERANCE, LANG, frozenset()), {})


class TestPadatiousBindsFromTheMap(TestCase):
    """A template with nothing after the slot binds ``twenty five
    please``. With ``slot_types`` registered and the map on the message,
    padatious prefers the listed span ``twenty five``, and the typed
    value is reported beside the surface. This is the row that tells the
    §5.6 MAY apart from the §3.4 degrade."""

    def setUp(self):
        with _resources() as td:
            self.intents = build_engine_intents(Path(td), LANG)
            self.slot_types = build_engine_slot_types(Path(td), LANG)
        self.adapter = GenericOPMAdapter(FIGHTERS["padatious-medium"])
        ok, reason = self.adapter.available()
        self.assertTrue(ok, reason)

    def test_match_carries_the_map_to_the_plugin(self):
        container = self.adapter.build(self.intents, skill_id=SKILL_ID, lang=LANG,
                                       slot_types=self.slot_types)
        typed = compute_typed_slots(UTTERANCE, LANG, frozenset({"number"}))
        name, _, _, slots = self.adapter.match(container, UTTERANCE, LANG,
                                               typed_slots=typed)
        self.assertEqual(name, "brightness")
        self.assertEqual(slots, {"b": "twenty five"})

    def test_run_golden_suite_reports_surface_and_typed_value(self):
        rows = [GoldenRow(utterance=UTTERANCE, lang=LANG, skill_id=SKILL_ID,
                          expected_intent="brightness", core=True)]
        engines = {"padatious-medium": self.adapter}
        scoreboard, predictions = run_golden_suite(
            rows, {(SKILL_ID, LANG): self.intents},
            slot_types_by_group={(SKILL_ID, LANG): self.slot_types},
            engines=engines, gating_engines=frozenset({"padatious-medium"}))
        self.assertTrue(scoreboard["padatious-medium"]["gate_passed"])
        row = predictions[0]
        self.assertEqual(row.predicted_slots, {"b": "twenty five"})
        self.assertEqual(row.typed_slots,
                         {"b": {"type": "number", "surface": "twenty five",
                                     "value": 25}})

    def test_without_the_map_the_template_guess_stands(self):
        container = self.adapter.build(self.intents, skill_id=SKILL_ID, lang=LANG,
                                       slot_types=self.slot_types)
        name, _, _, slots = self.adapter.match(container, UTTERANCE, LANG)
        self.assertEqual(name, "brightness")
        self.assertEqual(slots, {"b": "twenty five please"})

    def test_without_slot_types_the_row_has_no_typed_value(self):
        rows = [GoldenRow(utterance=UTTERANCE, lang=LANG, skill_id=SKILL_ID,
                          expected_intent="brightness", core=True)]
        _, predictions = run_golden_suite(
            rows, {(SKILL_ID, LANG): self.intents},
            engines={"padatious-medium": self.adapter},
            gating_engines=frozenset({"padatious-medium"}))
        self.assertIsNone(predictions[0].typed_slots)
