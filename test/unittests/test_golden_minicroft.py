"""``ovoscope golden``: the shared golden-utterance runner on a real MiniCroft.

A throw-away skill is written to a temporary directory and imported from
there, so its ``root_dir`` is that directory. It ships one Adapt intent in
two locales (en-US and pt-PT). The gold file holds a row per locale plus a
null-expected negative and a ``needs_manual`` row.

Two constraints get a failing control each:

- root_dir (T-3351): the same skill measured from a directory that is not
  the ``--checkout`` must fail the run, not pass silently.
- per-row lang (T-3308): the pt-PT row matches only when its own ``lang``
  reaches the Session; a runner that forces en-US misses it.
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from ovos_utils.log import LOG

from ovoscope import get_minicroft, is_pipeline_available, LEAN_DEFAULT_PIPELINE
from ovoscope.golden_minicroft import (RootDirMismatch, collect_rows,
                                       run_golden, run_rows, scoreboard)

SKILL_ID = "ovoscope-unittest-golden.test"
SKILL_SRC = textwrap.dedent('''
    from ovos_bus_client.message import Message
    from ovos_workshop.decorators import intent_handler
    from ovos_workshop.intents import IntentBuilder
    from ovos_workshop.skills.ovos import OVOSSkill


    class GoldenFixtureSkill(OVOSSkill):
        @intent_handler(IntentBuilder("HelloIntent").require("hello"))
        def handle_hello(self, message: Message):
            self.speak("hi", wait=False)
''')
VOC = {"en-US": "hello\nhi there\n", "pt-PT": "olá\nbom dia\n"}


def _write_skill(root: Path, module_name: str):
    (root / "locale").mkdir(parents=True)
    for lang, words in VOC.items():
        (root / "locale" / lang).mkdir()
        (root / "locale" / lang / "hello.voc").write_text(words, encoding="utf-8")
    (root / f"{module_name}.py").write_text(SKILL_SRC, encoding="utf-8")
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(module_name)
    finally:
        sys.path.remove(str(root))
    return module.GoldenFixtureSkill


ROWS = [
    {"utterance": "hello", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "HelloIntent"},
    {"utterance": "bom dia", "lang": "pt-PT", "skill_id": SKILL_ID,
     "expected_intent": "HelloIntent"},
    {"utterance": "what is the weather", "lang": "en-US",
     "skill_id": SKILL_ID, "expected_intent": None},
    {"utterance": "needs a human", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "HelloIntent", "needs_manual": True},
]


def _write_rows(path: Path, rows=ROWS):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@unittest.skipUnless(is_pipeline_available(LEAN_DEFAULT_PIPELINE),
                     "lean pipeline plugins not installed")
class TestGoldenMiniCroft(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_skill(cls.checkout, "golden_fixture_skill")
        cls.rows_path = cls.checkout / "test" / "end2end" / "golden_utterances_all.jsonl"
        _write_rows(cls.rows_path)

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("golden_fixture_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _factory(self, force_lang=None):
        skill_cls = self.skill_cls

        def factory(skill_id, lang, pipeline):
            return get_minicroft([skill_id], lang=force_lang or lang,
                                 extra_skills={skill_id: skill_cls})
        return factory

    def test_two_locales_match_with_their_own_lang(self):
        rows = collect_rows([str(self.rows_path)])
        results = run_rows(rows, SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        by_utt = {r.utterance: r for r in results}
        self.assertTrue(by_utt["hello"].matched, by_utt["hello"].fired)
        self.assertTrue(by_utt["bom dia"].matched, by_utt["bom dia"].fired)
        self.assertTrue(by_utt["what is the weather"].matched,
                        by_utt["what is the weather"].fired)
        self.assertTrue(by_utt["needs a human"].skipped)
        board = scoreboard(results, SKILL_ID)[f"minicroft:{SKILL_ID}"]
        self.assertEqual((board["total"], board["matched"], board["skipped"]),
                         (3, 3, 1))
        self.assertTrue(board["gate_passed"])

    def test_the_pt_row_needs_its_own_lang(self):
        """Control for T-3308: a runner that boots en-US for every row and
        never puts the row's lang on the Session misses the pt-PT row."""
        rows = [r for r in collect_rows([str(self.rows_path)]) if r.lang == "pt-PT"]
        results = run_rows(rows, SKILL_ID, self.checkout,
                           minicroft_factory=self._factory(force_lang="en-US"))
        # the MiniCroft was booted en-US; the runner still put pt-PT on the
        # Session, so the pt-PT vocabulary must be loaded for this to match
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].lang, "pt-PT")
        # the en-US only boot did not load the pt-PT vocabulary
        self.assertFalse(results[0].matched, results[0].fired)

    def test_a_skill_outside_the_checkout_fails_the_run(self):
        """T-3351: the skill loaded from somewhere else than --checkout."""
        other = self.tmp / "elsewhere"
        other.mkdir(exist_ok=True)
        rows = collect_rows([str(self.rows_path)], locales=["en-US"])
        with self.assertRaises(RootDirMismatch) as ctx:
            run_rows(rows, SKILL_ID, other, minicroft_factory=self._factory())
        self.assertIn(str(self.checkout.resolve()), str(ctx.exception))
        self.assertIn(str(other.resolve()), str(ctx.exception))

    def test_run_golden_exit_codes_and_files(self):
        out = self.tmp / "out"
        lines = []
        code = run_golden([str(self.rows_path)], SKILL_ID, str(self.checkout),
                          locales=["en-US"], out_dir=str(out),
                          minicroft_factory=self._factory(), echo=lines.append)
        self.assertEqual(code, 0, lines)
        board = json.loads((out / "scoreboard.json").read_text())
        self.assertEqual(board[f"minicroft:{SKILL_ID}"]["total"], 2)
        self.assertEqual(len((out / "predictions.jsonl").read_text().splitlines()), 3)
        # a miss exits 1 and names the row
        miss = self.tmp / "miss.jsonl"
        _write_rows(miss, [{"utterance": "hello", "lang": "en-US",
                            "skill_id": SKILL_ID, "expected_intent": "OtherIntent"}])
        lines = []
        code = run_golden([str(miss)], SKILL_ID, str(self.checkout),
                          minicroft_factory=self._factory(), echo=lines.append)
        self.assertEqual(code, 1)
        self.assertTrue(any(l.startswith("MISS [en-US] 'hello'") for l in lines), lines)
        # no rows at all exits 2
        self.assertEqual(run_golden([str(self.tmp / "none*.jsonl")], SKILL_ID,
                                    str(self.checkout), echo=lines.append), 2)


class TestCollectRows(unittest.TestCase):

    def test_locales_filter_and_glob(self):
        tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-rows-"))
        try:
            _write_rows(tmp / "golden_utterances_en.jsonl", ROWS[:1])
            _write_rows(tmp / "golden_utterances_pt.jsonl", ROWS[1:2])
            rows = collect_rows([str(tmp / "golden_utterances_*.jsonl")])
            self.assertEqual({r.lang for r in rows}, {"en-US", "pt-PT"})
            rows = collect_rows([str(tmp / "golden_utterances_*.jsonl")], ["pt-PT"])
            self.assertEqual([r.utterance for r in rows], ["bom dia"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
