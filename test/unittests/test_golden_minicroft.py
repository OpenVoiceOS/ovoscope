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
from unittest import mock

from ovos_utils.log import LOG

from ovoscope import (get_minicroft, get_m2v_minicroft, is_pipeline_available,
                      m2v_model_labels, LEAN_DEFAULT_PIPELINE,
                      M2V_DUAL_PIPELINE, M2V_PROTOTYPE_PIPELINE,
                      M2V_PUBLISHED_MODEL)
from ovoscope.golden_minicroft import (EXIT_ALL_SKIPPED, EXIT_PRESET,
                                       PresetUnavailable, RootDirMismatch,
                                       assert_root_dir, collect_rows,
                                       preset_factory, preset_unavailable,
                                       resolve_pipeline, run_golden, run_rows,
                                       scoreboard)

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

    def test_an_installed_copy_inside_the_checkout_fails_the_run(self):
        """Review of #212, gap 1: a venv inside the checkout holds a
        non-editable copy of the skill under site-packages. It is on disk
        under --checkout and is still not the checkout's source."""
        nested = self.checkout / ".venv" / "lib" / "python3.11" / "site-packages" / "golden_fixture_installed"
        shutil.copytree(self.checkout / "locale", nested / "locale")
        shutil.copy(self.checkout / "golden_fixture_skill.py",
                    nested / "golden_fixture_installed.py")
        sys.path.insert(0, str(nested))
        try:
            installed_cls = importlib.import_module("golden_fixture_installed").GoldenFixtureSkill
        finally:
            sys.path.remove(str(nested))
        rows = collect_rows([str(self.rows_path)], locales=["en-US"])

        def factory(skill_id, lang, pipeline):
            return get_minicroft([skill_id], lang=lang,
                                 extra_skills={skill_id: installed_cls})
        try:
            with self.assertRaises(RootDirMismatch) as ctx:
                run_rows(rows, SKILL_ID, self.checkout, minicroft_factory=factory)
        finally:
            sys.modules.pop("golden_fixture_installed", None)
        self.assertIn("site-packages", str(ctx.exception))
        self.assertIn(str(nested.resolve()), str(ctx.exception))

    def test_every_row_needs_manual_exits_its_own_code(self):
        """Review of #212, gap 2: an all-manual file measured nothing and
        exited 0 like a passing suite."""
        manual = self.tmp / "manual.jsonl"
        _write_rows(manual, [dict(ROWS[0], needs_manual=True),
                             dict(ROWS[2], needs_manual=True)])
        lines = []
        code = run_golden([str(manual)], SKILL_ID, str(self.checkout),
                          minicroft_factory=self._factory(), echo=lines.append)
        self.assertEqual(code, EXIT_ALL_SKIPPED, lines)
        self.assertEqual(code, 4)
        self.assertTrue(any(l.startswith("ALL SKIPPED: 2 row(s)") for l in lines), lines)

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


class TestAssertRootDirSegments(unittest.TestCase):
    """The path check alone, no MiniCroft: which roots pass for a checkout."""

    class _Loader:
        def __init__(self, root):
            self.instance = type("S", (), {"root_dir": str(root)})()

    def _mc(self, root):
        return type("MC", (), {"plugin_skills": {SKILL_ID: self._Loader(root)}})()

    def test_segments(self):
        checkout = Path(tempfile.mkdtemp(prefix="ovoscope-rootdir-"))
        try:
            good = checkout / "ovos_skill_x"
            good.mkdir()
            self.assertEqual(assert_root_dir(self._mc(good), SKILL_ID, checkout),
                             good.resolve())
            self.assertEqual(assert_root_dir(self._mc(checkout), SKILL_ID, checkout),
                             checkout.resolve())
            for seg in ("site-packages", "dist-packages", ".venv", "venv"):
                bad = checkout / seg / "ovos_skill_x"
                bad.mkdir(parents=True)
                with self.assertRaises(RootDirMismatch, msg=seg):
                    assert_root_dir(self._mc(bad), SKILL_ID, checkout)
            with self.assertRaises(RootDirMismatch):
                assert_root_dir(self._mc(checkout.parent), SKILL_ID, checkout)
        finally:
            shutil.rmtree(checkout, ignore_errors=True)


PRESET_SKILL_ID = "ovoscope-unittest-golden-presets.test"
PRESET_SKILL_SRC = textwrap.dedent('''
    from ovos_bus_client.message import Message
    from ovos_workshop.decorators import intent_handler
    from ovos_workshop.skills.ovos import OVOSSkill


    class PresetFixtureSkill(OVOSSkill):
        @intent_handler("greet.intent")
        def handle_greet(self, message: Message):
            self.speak("hi", wait=False)
''')
INTENT = {"en-US": "say hello to me\ngreet me\ngive me a greeting\n",
          "pt-PT": "diz olá\ncumprimenta-me\ndá-me uma saudação\n"}
PRESET_ROWS = [
    {"utterance": "greet me", "lang": "en-US", "skill_id": PRESET_SKILL_ID,
     "expected_intent": "greet.intent"},
    {"utterance": "cumprimenta-me", "lang": "pt-PT",
     "skill_id": PRESET_SKILL_ID, "expected_intent": "greet.intent"},
]


def _write_preset_skill(root: Path, module_name: str):
    (root / "locale").mkdir(parents=True)
    for lang, lines in INTENT.items():
        (root / "locale" / lang).mkdir()
        (root / "locale" / lang / "greet.intent").write_text(lines, encoding="utf-8")
    (root / f"{module_name}.py").write_text(PRESET_SKILL_SRC, encoding="utf-8")
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(module_name)
    finally:
        sys.path.remove(str(root))
    return module.PresetFixtureSkill


class TestPipelinePresets(unittest.TestCase):
    """``--pipeline`` presets: ``repo`` resolves to the checkout's own list,
    the m2v presets boot through ``get_m2v_minicroft`` on the published
    model, and a preset that cannot boot here exits 5 with its reason."""

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-presets-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_preset_skill(cls.checkout, "preset_fixture_skill")
        cls.rows_path = cls.checkout / "test" / "end2end" / "golden_utterances_all.jsonl"
        _write_rows(cls.rows_path, PRESET_ROWS)

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("preset_fixture_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_repo_preset_is_the_checkout_declaration(self):
        # no pyproject: the repo preset leaves the pipeline to MiniCroft
        self.assertEqual(resolve_pipeline(None, self.checkout), (None, None))
        self.assertEqual(resolve_pipeline(["repo"], self.checkout), (None, None))
        declared = ["ovos-padatious-pipeline-plugin-high",
                    "ovos-padacioso-pipeline-plugin-high"]
        (self.checkout / "pyproject.toml").write_text(
            '[project]\nname = "x"\n[tool.ovoscope]\npipeline = [\n'
            + "".join(f'  "{s}",\n' for s in declared) + "]\n",
            encoding="utf-8")
        try:
            self.assertEqual(resolve_pipeline(None, self.checkout), (None, declared))
            # an explicit list wins over the declaration
            self.assertEqual(resolve_pipeline(["a", "b"], self.checkout),
                             (None, ["a", "b"]))
            # a preset stands alone
            with self.assertRaises(PresetUnavailable):
                resolve_pipeline(["repo", "a"], self.checkout)
            # the declared list is what the boot and every Session receive
            seen = []

            def factory(skill_id, lang, pipe):
                seen.append(list(pipe))
                return get_minicroft([skill_id], lang=lang,
                                     default_pipeline=list(pipe),
                                     extra_skills={skill_id: self.skill_cls})
            lines = []
            code = run_golden([str(self.rows_path)], PRESET_SKILL_ID,
                              str(self.checkout), locales=["en-US"],
                              minicroft_factory=factory, echo=lines.append)
            self.assertEqual(code, 0, lines)
            self.assertEqual(seen, [declared])
            self.assertIn(f"pipeline: {declared}", lines)
        finally:
            (self.checkout / "pyproject.toml").unlink()

    def test_a_bad_declaration_is_named(self):
        (self.checkout / "pyproject.toml").write_text(
            '[tool.ovoscope]\npipeline = "not-a-list"\n', encoding="utf-8")
        try:
            lines = []
            code = run_golden([str(self.rows_path)], PRESET_SKILL_ID,
                              str(self.checkout), echo=lines.append)
            self.assertEqual(code, EXIT_PRESET, lines)
            self.assertTrue(lines[0].startswith("PRESET UNAVAILABLE: [tool.ovoscope]"), lines)
        finally:
            (self.checkout / "pyproject.toml").unlink()

    def test_an_unavailable_preset_exits_5_with_the_reason(self):
        with mock.patch("ovoscope.golden_minicroft.preset_unavailable",
                        return_value="preset 'm2v-dual': model is not reachable: probe"):
            lines = []
            code = run_golden([str(self.rows_path)], PRESET_SKILL_ID,
                              str(self.checkout), pipeline=["m2v-dual"],
                              echo=lines.append)
        self.assertEqual(code, EXIT_PRESET)
        self.assertEqual(code, 5)
        self.assertEqual(lines, ["PRESET UNAVAILABLE: preset 'm2v-dual': model "
                                 "is not reachable: probe"])

    def _run_preset(self, preset):
        reason = preset_unavailable(preset)
        if reason:
            self.skipTest(reason)
        booted = []

        def factory(skill_id, lang, pipe):
            mc = preset_factory(preset, extra_skills={skill_id: self.skill_cls})(
                skill_id, lang, pipe)
            booted.append(mc)
            return mc
        rows = collect_rows([str(self.rows_path)])
        results = run_rows(rows, PRESET_SKILL_ID, self.checkout, preset=preset,
                           minicroft_factory=factory)
        return booted, {r.utterance: r for r in results}

    def test_m2v_prototype_preset_matches_both_locales(self):
        booted, by_utt = self._run_preset("m2v-prototype")
        self.assertEqual(len(booted), 2)
        for mc in booted:
            self.assertEqual(mc.pipeline, M2V_PROTOTYPE_PIPELINE)
            self.assertNotIn("ovos-m2v-pipeline", mc.intents.pipeline_plugins)
            proto = mc.intents.pipeline_plugins["ovos-m2v-prototype-pipeline"]
            self.assertEqual(proto.config.get("model"), M2V_PUBLISHED_MODEL)
            self.assertEqual(list(proto.ignore_labels), [])
        self.assertTrue(by_utt["greet me"].matched, by_utt["greet me"].fired)
        self.assertTrue(by_utt["cumprimenta-me"].matched, by_utt["cumprimenta-me"].fired)

    def test_m2v_dual_preset_matches_both_locales(self):
        booted, by_utt = self._run_preset("m2v-dual")
        self.assertEqual(len(booted), 2)
        for mc in booted:
            self.assertEqual(mc.pipeline, M2V_DUAL_PIPELINE)
            classifier = mc.intents.pipeline_plugins["ovos-m2v-pipeline"]
            proto = mc.intents.pipeline_plugins["ovos-m2v-prototype-pipeline"]
            self.assertEqual(classifier.config.get("model"), M2V_PUBLISHED_MODEL)
            # the label mask is the published model's own label list
            self.assertEqual(set(proto.ignore_labels),
                             set(m2v_model_labels(M2V_PUBLISHED_MODEL)))
            self.assertNotIn(f"{PRESET_SKILL_ID}:greet", proto.ignore_labels)
        self.assertTrue(by_utt["greet me"].matched, by_utt["greet me"].fired)
        self.assertTrue(by_utt["cumprimenta-me"].matched, by_utt["cumprimenta-me"].fired)

    def test_a_boot_with_no_m2v_stage_is_refused(self):
        with self.assertRaises(ValueError):
            get_m2v_minicroft([PRESET_SKILL_ID], prototype=False, classifier=False)
