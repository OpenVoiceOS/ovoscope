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
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from ovos_utils.log import LOG

from ovoscope import (get_minicroft, get_m2v_minicroft, is_pipeline_available,
                      m2v_model_labels, LEAN_DEFAULT_PIPELINE,
                      M2V_DUAL_PIPELINE, M2V_PROTOTYPE_PIPELINE,
                      M2V_PUBLISHED_MODEL)
from ovoscope.golden import GoldenRow
from ovoscope.golden_minicroft import (EXIT_ALL_GAPS, EXIT_ALL_SKIPPED,
                                       EXIT_MISS, EXIT_PRESET,
                                       PresetUnavailable, RootDirMismatch,
                                       assert_res_dir, assert_root_dir,
                                       collect_rows,
                                       locale_resources, missing_resource,
                                       _own_locale_roots, own_package,
                                       NO_PACKAGE, WIDE_BOUND_NOTE,
                                       _mark_coverage_gaps, RowResult,
                                       WORKER_BOOT_ALLOWANCE, WORKER_MODULE,
                                       preset_factory, preset_unavailable,
                                       worker_timeout,
                                       resolve_pipeline, run_golden, run_rows,
                                       run_rows_per_locale, scoreboard)

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


HOOK_SRC = textwrap.dedent('''
    """A stand-in minicroft_factory for the golden worker, named by
    OVOSCOPE_GOLDEN_FACTORY. It records the pid of every boot."""
    import os

    from ovoscope import get_minicroft
    from golden_fixture_skill import GoldenFixtureSkill


    def factory(preset):
        def boot(skill_id, lang, pipeline):
            with open(os.environ["OVOSCOPE_GOLDEN_PIDFILE"], "a") as fh:
                fh.write(f"{lang} {os.getpid()}\\n")
            if os.environ.get("OVOSCOPE_GOLDEN_RAISE"):
                raise RuntimeError("weights download failed after warm-up")
            hang = float(os.environ.get("OVOSCOPE_GOLDEN_SLEEP") or 0)
            if hang:
                import time
                time.sleep(hang)
            return get_minicroft([skill_id], lang=lang,
                                 extra_skills={skill_id: GoldenFixtureSkill})
        return boot
''')


@unittest.skipUnless(is_pipeline_available(LEAN_DEFAULT_PIPELINE),
                     "lean pipeline plugins not installed")
class TestGoldenBootFailureAndProcesses(unittest.TestCase):
    """T-3630: a boot that fails exits 5, and a locale can own its process."""

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-boot-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_skill(cls.checkout, "golden_fixture_skill")
        cls.rows_path = cls.checkout / "test" / "end2end" / "golden_utterances_all.jsonl"
        _write_rows(cls.rows_path)
        (cls.checkout / "golden_worker_hook.py").write_text(HOOK_SRC,
                                                            encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("golden_fixture_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _child_env(self, **extra):
        """The environment the worker children inherit: the hook, the pid
        file, and the fixture skill on the import path."""
        self.pidfile = self.tmp / f"pids-{self.id().rsplit('.', 1)[-1]}.txt"
        path = os.pathsep.join([str(self.checkout),
                                os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        env = {"OVOSCOPE_GOLDEN_FACTORY": "golden_worker_hook:factory",
               "OVOSCOPE_GOLDEN_PIDFILE": str(self.pidfile),
               "PYTHONPATH": path}
        env.update(extra)
        return mock.patch.dict(os.environ, env)

    def test_a_factory_that_raises_after_the_check_exits_5(self):
        """The preset check passed; the boot itself failed. Exit 5, not 1:
        a miss is a corpus result and this run measured nothing."""
        def factory(skill_id, lang, pipe):
            raise RuntimeError("weights download failed after warm-up")

        lines = []
        with mock.patch("ovoscope.golden_minicroft.preset_unavailable",
                        return_value=None):
            code = run_golden([str(self.rows_path)], SKILL_ID,
                              str(self.checkout), pipeline=["m2v-dual"],
                              minicroft_factory=factory, echo=lines.append)
        self.assertEqual(code, EXIT_PRESET, lines)
        self.assertEqual(code, 5)
        reason = [l for l in lines if l.startswith("PRESET UNAVAILABLE:")]
        self.assertEqual(len(reason), 1, lines)
        self.assertIn("could not boot for en-US", reason[0])
        self.assertIn("weights download failed after warm-up", reason[0])

    def test_a_boot_failure_with_no_preset_exits_5_too(self):
        """Exit 5 means "could not boot" on every path, preset or not."""
        def factory(skill_id, lang, pipe):
            raise RuntimeError("no audio backend")

        lines = []
        code = run_golden([str(self.rows_path)], SKILL_ID, str(self.checkout),
                          minicroft_factory=factory, echo=lines.append)
        self.assertEqual(code, EXIT_PRESET, lines)
        self.assertIn("the MiniCroft boot could not boot for en-US",
                      lines[-1])

    def test_each_locale_boots_in_its_own_process(self):
        """The memory of a stopped MiniCroft comes back at process exit, so
        a many-locale run boots one interpreter per locale (T-3533)."""
        lines = []
        with self._child_env():
            code = run_golden([str(self.rows_path)], SKILL_ID,
                              str(self.checkout), out_dir=str(self.tmp / "out"),
                              echo=lines.append, per_locale_process=True)
        self.assertEqual(code, 0, lines)
        board = json.loads((self.tmp / "out" / "scoreboard.json")
                           .read_text(encoding="utf-8"))[f"minicroft:{SKILL_ID}"]
        self.assertEqual((board["total"], board["matched"], board["skipped"]),
                         (3, 3, 1))
        booted = [l.split() for l in
                  self.pidfile.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(l for l, _ in booted), ["en-US", "pt-PT"])
        pids = {pid for _, pid in booted}
        self.assertEqual(len(pids), 2, booted)
        self.assertNotIn(str(os.getpid()), pids)

    def test_a_boot_failure_in_a_worker_reaches_the_caller_as_exit_5(self):
        lines = []
        with self._child_env(OVOSCOPE_GOLDEN_RAISE="1"):
            code = run_golden([str(self.rows_path)], SKILL_ID,
                              str(self.checkout), echo=lines.append,
                              per_locale_process=True)
        self.assertEqual(code, EXIT_PRESET, lines)
        self.assertIn("weights download failed after warm-up", lines[-1])


class TestGoldenWorkerFailures(unittest.TestCase):
    """T-3688: a worker that hangs, or that writes a result nobody can read,
    is a boot failure like any other: exit 5 naming the locale."""

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-worker-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_skill(cls.checkout, "golden_fixture_skill")
        cls.rows_path = cls.checkout / "test" / "end2end" / "golden_utterances_all.jsonl"
        _write_rows(cls.rows_path)
        (cls.checkout / "golden_worker_hook.py").write_text(HOOK_SRC,
                                                            encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("golden_fixture_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, echo_lines, **env):
        path = os.pathsep.join([str(self.checkout),
                                os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        base = {"OVOSCOPE_GOLDEN_FACTORY": "golden_worker_hook:factory",
                "OVOSCOPE_GOLDEN_PIDFILE": str(self.tmp / "pids.txt"),
                "PYTHONPATH": path}
        base.update(env)
        with mock.patch.dict(os.environ, base):
            return run_golden([str(self.rows_path)], SKILL_ID,
                              str(self.checkout), echo=echo_lines.append,
                              per_locale_process=True)

    def test_the_derived_bound_covers_the_boot_and_every_row(self):
        self.assertEqual(worker_timeout(3, 20.0),
                         WORKER_BOOT_ALLOWANCE + 60.0)
        # a locale with no active row still gets the boot allowance
        self.assertEqual(worker_timeout(0, 20.0),
                         WORKER_BOOT_ALLOWANCE + 20.0)

    def test_the_environment_sets_the_bound(self):
        with mock.patch.dict(os.environ, {"OVOSCOPE_WORKER_TIMEOUT": "7.5"}):
            self.assertEqual(worker_timeout(100, 20.0), 7.5)
        with mock.patch.dict(os.environ, {"OVOSCOPE_WORKER_TIMEOUT": "soon"}):
            self.assertEqual(worker_timeout(1, 20.0),
                             WORKER_BOOT_ALLOWANCE + 20.0)

    def test_a_worker_that_hangs_is_killed_and_exits_5(self):
        lines = []
        code = self._run(lines, OVOSCOPE_GOLDEN_SLEEP="300",
                         OVOSCOPE_WORKER_TIMEOUT="3")
        self.assertEqual(code, EXIT_PRESET, lines)
        self.assertIn("did not finish in 3s", lines[-1])
        self.assertIn("en-US", lines[-1])

    def _with_worker_writing(self, text, returncode=-9):
        """Run with a stubbed worker that writes *text* as its result."""
        real_run = subprocess.run

        def fake_run(args, **kwargs):
            if len(args) > 3 and args[1:3] == ["-m", WORKER_MODULE]:
                Path(args[4]).write_text(text, encoding="utf-8")
                return subprocess.CompletedProcess(args, returncode)
            return real_run(args, **kwargs)  # pragma: no cover - not used

        lines = []
        with mock.patch("subprocess.run", side_effect=fake_run):
            code = run_golden([str(self.rows_path)], SKILL_ID,
                              str(self.checkout), echo=lines.append,
                              per_locale_process=True)
        return code, lines

    def test_a_truncated_result_file_exits_5(self):
        code, lines = self._with_worker_writing('{"results": [{"utteranc')
        self.assertEqual(code, EXIT_PRESET, lines)
        self.assertIn("cannot be read", lines[-1])
        self.assertIn("exit code -9", lines[-1])
        self.assertIn("en-US", lines[-1])

    def test_a_result_file_without_rows_exits_5(self):
        code, lines = self._with_worker_writing("{}", returncode=0)
        self.assertEqual(code, EXIT_PRESET, lines)
        self.assertIn("wrong shape", lines[-1])
        self.assertIn("en-US", lines[-1])

    def test_a_result_row_of_the_wrong_shape_exits_5(self):
        code, lines = self._with_worker_writing('{"results": [{"nope": 1}]}',
                                                returncode=0)
        self.assertEqual(code, EXIT_PRESET, lines)
        self.assertIn("wrong shape", lines[-1])


GAP_ROWS = [
    {"utterance": "hello", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "HelloIntent"},
    # machine-drafted, and the name it expects is a dialog the locale ships:
    # a native speaker has not confirmed the phrase yet
    {"utterance": "who made you", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "who_is", "machine_generated": True},
    # machine-drafted, and the name is the pre-rename spelling nobody ships
    {"utterance": "who are you", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "who.is", "machine_generated": True},
]


@unittest.skipUnless(is_pipeline_available(LEAN_DEFAULT_PIPELINE),
                     "lean pipeline plugins not installed")
class TestMachineDraftedRowsNameRealResources(unittest.TestCase):
    """T-3714: a wrong expected name is not a coverage gap.

    Nine machine-drafted rows on ovos-skill-fallback-unknown#69 named dotted
    pre-rename dialogs that do not exist, and the runner turned every
    mismatch into an expected failure, so the run stayed green on a name the
    skill had never shipped.
    """

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-gap-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_skill(cls.checkout, "golden_gap_skill")
        # the skill ships who_is.dialog for en-US, and nothing dotted
        (cls.checkout / "locale" / "en-US" / "who_is.dialog").write_text(
            "i am a test skill\n", encoding="utf-8")
        cls.rows_path = cls.checkout / "test" / "end2end" / "golden_utterances_all.jsonl"
        _write_rows(cls.rows_path, GAP_ROWS)

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("golden_gap_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _factory(self):
        skill_cls = self.skill_cls

        def factory(skill_id, lang, pipeline):
            return get_minicroft([skill_id], lang=lang,
                                 extra_skills={skill_id: skill_cls})
        return factory

    def test_locale_resources_read_the_names_as_written(self):
        names = locale_resources(self.checkout, "en-US")
        self.assertIn("who_is", names)
        self.assertIn("hello", names)
        self.assertNotIn("who.is", names)
        self.assertEqual(locale_resources(self.checkout, "kab"), set())

    def test_a_name_the_locale_ships_is_a_coverage_gap(self):
        rows = collect_rows([str(self.rows_path)])
        results = run_rows(rows, SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        by_utt = {r.utterance: r for r in results}
        gap = by_utt["who made you"]
        self.assertFalse(gap.matched)
        self.assertTrue(gap.gap)
        self.assertIn("coverage-gap", gap.reason)

    def test_a_name_nobody_ships_stays_a_miss_that_says_so(self):
        rows = collect_rows([str(self.rows_path)])
        results = run_rows(rows, SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        by_utt = {r.utterance: r for r in results}
        wrong = by_utt["who are you"]
        self.assertFalse(wrong.matched)
        self.assertFalse(wrong.gap, "a wrong name is not a coverage gap")
        self.assertIn("who.is", wrong.reason)
        self.assertIn("en-US ships no resource", wrong.reason)

    def test_the_run_fails_on_the_wrong_name_and_not_on_the_gap(self):
        lines = []
        code = run_golden([str(self.rows_path)], SKILL_ID, str(self.checkout),
                          minicroft_factory=self._factory(),
                          out_dir=str(self.tmp / "out"), echo=lines.append)
        self.assertEqual(code, EXIT_MISS, lines)
        board = json.loads((self.tmp / "out" / "scoreboard.json")
                           .read_text(encoding="utf-8"))[f"minicroft:{SKILL_ID}"]
        self.assertEqual(board["coverage_gap"], 1)
        self.assertEqual(board["total"], 2)
        self.assertEqual(board["matched"], 1)
        self.assertFalse(board["gate_passed"])
        failures = board["failures"]
        self.assertEqual([f["expected"] for f in failures], ["who.is"])
        self.assertIn("who.is", failures[0]["reason"])
        self.assertTrue(any("COVERAGE GAP" in line for line in lines), lines)

    def test_an_intent_no_file_declares_is_not_a_missing_resource(self):
        """The run itself fired the label, so the name is real: an Adapt
        intent built in code ships no resource file."""
        rows = [r for r in collect_rows([str(self.rows_path)])
                if r.utterance == "hello"]
        rows.append(GoldenRow(utterance="hi there", lang="en-US",
                              skill_id=SKILL_ID, expected_intent="HelloIntent",
                              provenance={"machine_generated": True}))
        # a second row whose utterance the skill does not know: it misses,
        # and its label was fired by the first row
        rows.append(GoldenRow(utterance="greetings to you", lang="en-US",
                              skill_id=SKILL_ID, expected_intent="HelloIntent",
                              provenance={"machine_generated": True}))
        results = run_rows(rows, SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        missed = [r for r in results if not r.matched]
        self.assertEqual([r.utterance for r in missed], ["greetings to you"])
        self.assertTrue(missed[0].gap)
        self.assertIn("coverage-gap", missed[0].reason)

    def test_the_rule_the_skill_repos_ship_tolerates_both_rows(self):
        """Fail-before control. The per-repo runners xfail on
        `row["machine_generated"] and not matched` alone, which covers the
        wrong name as well as the real gap. The resource check is the whole
        difference."""
        rows = collect_rows([str(self.rows_path)])
        results = run_rows(rows, SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        drafted = {r.utterance: r for r in results
                   if not r.matched and r.expected in ("who_is", "who.is")}
        # the old predicate: both misses are machine-drafted
        self.assertEqual(sorted(drafted), ["who are you", "who made you"])
        # this runner: only the one whose name exists is a gap
        self.assertTrue(drafted["who made you"].gap)
        self.assertFalse(drafted["who are you"].gap)

    def test_missing_resource_names_the_name(self):
        rows = collect_rows([str(self.rows_path)])
        by_utt = {r.utterance: r for r in rows}
        self.assertIsNone(missing_resource(by_utt["who made you"], SKILL_ID,
                                           self.checkout))
        self.assertEqual(missing_resource(by_utt["who are you"], SKILL_ID,
                                          self.checkout), "who.is")
        # a label the run fired is real even where no file declares it
        self.assertIsNone(missing_resource(by_utt["who are you"], SKILL_ID,
                                           self.checkout,
                                           known_labels={f"{SKILL_ID}:who.is"}))


GAP_HOOK_SRC = textwrap.dedent('''
    """A stand-in minicroft_factory for the golden worker of the gap
    fixture, named by OVOSCOPE_GOLDEN_FACTORY."""
    from ovoscope import get_minicroft
    from golden_wgap_skill import GoldenFixtureSkill


    def factory(preset):
        def boot(skill_id, lang, pipeline):
            return get_minicroft([skill_id], lang=lang,
                                 extra_skills={skill_id: GoldenFixtureSkill})
        return boot
''')
#: every row is machine-drafted, names a resource the locale ships, and
#: misses. Nothing is needs_manual, so nothing is skipped.
ALL_GAP_ROWS = [
    {"utterance": "who made you", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "hello", "machine_generated": True},
    {"utterance": "tell me a story", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "hello", "machine_generated": True},
]


@unittest.skipUnless(is_pipeline_available(LEAN_DEFAULT_PIPELINE),
                     "lean pipeline plugins not installed")
class TestCoverageGapsAreNotSkips(unittest.TestCase):
    """T-3735: a run whose every row is a coverage gap is not an empty
    corpus.

    ``run_golden`` tested ``total == 0`` alone, and ``scoreboard`` takes
    the gaps out of ``scored`` as well as the skips. So two loaded rows
    and two gaps printed "ALL SKIPPED: 0 row(s) loaded, every one
    needs_manual, nothing measured", exited 4, and returned above the
    COVERAGE GAP lines: three false statements and no mention of the two
    rows a native speaker must confirm.
    """

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-allgap-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_skill(cls.checkout, "golden_allgap_skill")
        cls.rows_path = cls.checkout / "test" / "end2end" / "golden_utterances_all.jsonl"
        _write_rows(cls.rows_path, ALL_GAP_ROWS)

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("golden_allgap_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _factory(self):
        skill_cls = self.skill_cls

        def factory(skill_id, lang, pipeline):
            return get_minicroft([skill_id], lang=lang,
                                 extra_skills={skill_id: skill_cls})
        return factory

    def test_an_all_gaps_run_prints_the_gaps_and_exits_6(self):
        lines = []
        code = run_golden([str(self.rows_path)], SKILL_ID, str(self.checkout),
                          minicroft_factory=self._factory(),
                          out_dir=str(self.tmp / "out"), echo=lines.append)
        self.assertEqual(code, EXIT_ALL_GAPS, lines)
        self.assertNotEqual(code, EXIT_ALL_SKIPPED)
        gap_lines = [l for l in lines if l.startswith("COVERAGE GAP")]
        self.assertEqual(len(gap_lines), 2, lines)
        self.assertTrue(any(l.startswith("ALL GAPS: 2 row(s) measured")
                            for l in lines), lines)
        self.assertFalse([l for l in lines if "ALL SKIPPED" in l], lines)

    def test_the_board_of_an_all_gaps_run_says_two_rows_loaded(self):
        lines = []
        run_golden([str(self.rows_path)], SKILL_ID, str(self.checkout),
                   minicroft_factory=self._factory(),
                   out_dir=str(self.tmp / "board"), echo=lines.append)
        board = json.loads((self.tmp / "board" / "scoreboard.json")
                           .read_text(encoding="utf-8"))[f"minicroft:{SKILL_ID}"]
        self.assertEqual(board["total"], 0)
        self.assertEqual(board["skipped"], 0)
        self.assertEqual(board["coverage_gap"], 2)
        self.assertEqual(len(board["gaps"]), 2)

    def test_an_empty_corpus_still_reads_as_all_skipped(self):
        """The control the fix must not move: no gaps and every row
        needs_manual is still exit 4 with the ALL SKIPPED line."""
        path = self.tmp / "skipped.jsonl"
        _write_rows(path, [dict(r, machine_generated=False, needs_manual=True)
                           for r in ALL_GAP_ROWS])
        lines = []
        code = run_golden([str(path)], SKILL_ID, str(self.checkout),
                          minicroft_factory=self._factory(),
                          echo=lines.append)
        self.assertEqual(code, EXIT_ALL_SKIPPED, lines)
        self.assertTrue(any("ALL SKIPPED: 2 row(s) loaded" in l
                            for l in lines), lines)


class TestLocaleResourcesAreTheSkillsOwn(unittest.TestCase):
    """T-3735: the name set is the skill's tree, not the whole checkout.

    ``locale_resources`` globbed ``<checkout>/**/locale/<lang>/*``, so any
    other skill's file under the checkout answered for this skill. A
    ``ovoscope golden --checkout .`` in a repo that holds a ``.venv``
    reads every installed skill's locale tree, and the name set becomes
    fleet-wide: that reopens the T-3140 mask this rule exists to close.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-scope-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "checkout"
        # the skill's own two layouts: the legacy top-level tree and a
        # packaged tree one directory down
        (self.root / "locale" / "en-US").mkdir(parents=True)
        (self.root / "locale" / "en-US" / "legacy_only.dialog").write_text(
            "x\n", encoding="utf-8")
        pkg = self.root / "my_skill"
        (pkg / "locale" / "en-US").mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "locale" / "en-US" / "packaged_only.dialog").write_text(
            "x\n", encoding="utf-8")
        # an installed copy of another skill inside the checkout
        venv = (self.root / ".venv" / "lib" / "python3.11" / "site-packages"
                / "other_skill" / "locale" / "en-US")
        venv.mkdir(parents=True)
        (venv / "installed_dialog.dialog").write_text("x\n", encoding="utf-8")
        # a second skill vendored in the checkout, not a package of it
        vendored = self.root / "vendor" / "other_skill" / "locale" / "en-US"
        vendored.mkdir(parents=True)
        (vendored / "vendored_dialog.dialog").write_text("x\n", encoding="utf-8")
        # a second skill vendored as a DIRECT CHILD package of the checkout,
        # which is a package of the tree but not a package of this skill
        sibling = self.root / "other_skill_pkg"
        (sibling / "locale" / "en-US").mkdir(parents=True)
        (sibling / "__init__.py").write_text("", encoding="utf-8")
        (sibling / "locale" / "en-US" / "sibling_dialog.dialog").write_text(
            "x\n", encoding="utf-8")

    def _row(self, expected):
        return GoldenRow(utterance="who are you", lang="en-US",
                         skill_id=SKILL_ID, expected_intent=expected,
                         provenance={"machine_generated": True})

    def test_the_skills_own_two_layouts_are_both_read(self):
        names = locale_resources(self.root, "en-US")
        self.assertIn("legacy_only", names)
        self.assertIn("packaged_only", names)

    def test_an_installed_copy_under_the_checkout_is_not_the_skill(self):
        names = locale_resources(self.root, "en-US")
        self.assertNotIn("installed_dialog", names)
        self.assertEqual(missing_resource(self._row("installed_dialog"),
                                          SKILL_ID, self.root),
                         "installed_dialog")

    def test_a_second_skill_vendored_in_the_checkout_is_not_the_skill(self):
        names = locale_resources(self.root, "en-US")
        self.assertNotIn("vendored_dialog", names)
        self.assertEqual(missing_resource(self._row("vendored_dialog"),
                                          SKILL_ID, self.root),
                         "vendored_dialog")

    def test_the_old_glob_accepted_both(self):
        """Fail-before control. The predicate the fix replaced was the bare
        recursive glob; it answers for every locale tree under the
        checkout, which is what made the two names above read as real."""
        old = set()
        for path in self.root.glob("**/locale/en-US/*.dialog"):
            old.add(path.name[:-len(".dialog")])
        self.assertEqual(sorted(old),
                         ["installed_dialog", "legacy_only", "packaged_only",
                          "sibling_dialog", "vendored_dialog"])

    def test_a_sibling_package_is_not_the_skill(self):
        """The case reviewer-b confirmed open at 8fd442c.

        ``other_skill_pkg`` is a direct child package of the checkout, so the
        predicate "any child with an ``__init__.py``" accepted it and its
        locale tree answered for this skill. Bounding the roots to the
        package the loaded class came from drops it, and both of this
        skill's own layouts still read.
        """
        names = locale_resources(self.root, "en-US", "my_skill")
        self.assertNotIn("sibling_dialog", names)
        self.assertIn("legacy_only", names)
        self.assertIn("packaged_only", names)
        self.assertEqual(missing_resource(self._row("sibling_dialog"),
                                          SKILL_ID, self.root,
                                          package="my_skill"),
                         "sibling_dialog")

    def test_the_bound_roots_are_the_root_and_its_own_package(self):
        self.assertEqual(_own_locale_roots(self.root, "my_skill"),
                         [self.root, self.root / "my_skill"])

    def test_no_package_means_the_root_alone(self):
        """NO_PACKAGE is the definite answer: this root ships no package, so
        no child of it belongs to the skill. Passing None instead would mean
        "undetermined" and would widen the bound back to every child."""
        self.assertEqual(_own_locale_roots(self.root, NO_PACKAGE), [self.root])
        names = locale_resources(self.root, "en-US", NO_PACKAGE)
        self.assertIn("legacy_only", names)
        self.assertNotIn("sibling_dialog", names)
        self.assertNotIn("packaged_only", names)

    def test_none_still_means_undetermined_and_widens(self):
        """The wide bound survives for the case that cannot be determined,
        because over-reading is the safe direction. This is the ONLY caller
        that gets it, and run_rows logs when it happens."""
        roots = _own_locale_roots(self.root, None)
        self.assertIn(self.root / "my_skill", roots)
        self.assertIn(self.root / "other_skill_pkg", roots)

    def test_a_namespace_package_is_accepted_by_name(self):
        """PEP 420: a named package with no __init__.py is still the skill's.
        own_package has already proved its module file lives there, which is
        stronger evidence than the marker file."""
        ns = self.root / "ns_skill"
        (ns / "locale" / "en-US").mkdir(parents=True)
        (ns / "skill.py").write_text("", encoding="utf-8")
        (ns / "locale" / "en-US" / "ns_only.dialog").write_text(
            "x\n", encoding="utf-8")
        self.assertEqual(_own_locale_roots(self.root, "ns_skill"),
                         [self.root, ns])
        self.assertIn("ns_only", locale_resources(self.root, "en-US",
                                                  "ns_skill"))

    def test_the_unbounded_predicate_accepted_the_sibling(self):
        """Fail-before control. The predicate at 8fd442c took every direct
        child package, so the sibling's tree was part of the name set. This
        reproduces it rather than trusting the description."""
        unbounded = set()
        for base in [self.root] + [c for c in sorted(self.root.iterdir())
                                   if c.is_dir()
                                   and (c / "__init__.py").is_file()]:
            folder = base / "locale" / "en-US"
            if folder.is_dir():
                for path in folder.iterdir():
                    if path.name.endswith(".dialog"):
                        unbounded.add(path.name[:-len(".dialog")])
        self.assertIn("sibling_dialog", unbounded)
        self.assertEqual(sorted(unbounded),
                         ["legacy_only", "packaged_only", "sibling_dialog"])

    def test_a_locale_the_skill_does_not_ship_is_empty(self):
        self.assertEqual(locale_resources(self.root, "kab"), set())


#: en-US fires the label; the pt-PT row names it and misses. pt-PT ships
#: no resource of that name, so the label alone must not excuse it.
CROSS_LOCALE_ROWS = [
    {"utterance": "hello", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "HelloIntent"},
    {"utterance": "hi there", "lang": "en-US", "skill_id": SKILL_ID,
     "expected_intent": "HelloIntent"},
    {"utterance": "quem te fez", "lang": "pt-PT", "skill_id": SKILL_ID,
     "expected_intent": "HelloIntent", "machine_generated": True},
]


@unittest.skipUnless(is_pipeline_available(LEAN_DEFAULT_PIPELINE),
                     "lean pipeline plugins not installed")
class TestFiredLabelsAreScopedToTheirLocale(unittest.TestCase):
    """T-3735: a label fired in one locale does not excuse another.

    ``run_rows`` accumulated one ``fired_labels`` set over every locale and
    passed it to the coverage-gap pass after the loop, so a label the run
    fired in en-US proved the name existed for pt-PT as well. The escape
    hatch is right (an Adapt intent built in code ships no file), and it
    belongs to the locale that fired it.
    """

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-xlocale-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_skill(cls.checkout, "golden_xlocale_skill")
        cls.rows_path = cls.checkout / "test" / "end2end" / "golden_utterances_all.jsonl"
        _write_rows(cls.rows_path, CROSS_LOCALE_ROWS)

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("golden_xlocale_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _factory(self):
        skill_cls = self.skill_cls

        def factory(skill_id, lang, pipeline):
            return get_minicroft([skill_id], lang=lang,
                                 extra_skills={skill_id: skill_cls})
        return factory

    def test_a_label_fired_in_en_US_does_not_excuse_the_pt_PT_row(self):
        rows = collect_rows([str(self.rows_path)])
        results = run_rows(rows, SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        by_utt = {r.utterance: r for r in results}
        # the control: en-US fired the label, so en-US is where it is known
        self.assertTrue(by_utt["hello"].matched)
        wrong = by_utt["quem te fez"]
        self.assertFalse(wrong.matched)
        self.assertFalse(wrong.gap,
                         "a label fired in en-US is not a pt-PT resource")
        self.assertIn("HelloIntent", wrong.reason)
        self.assertIn("pt-PT ships no resource", wrong.reason)

    def test_a_label_fired_in_the_rows_own_locale_is_a_gap(self):
        """The control that moves the other way: the same missing name, in
        the locale that fired the label, stays a coverage gap."""
        rows = collect_rows([str(self.rows_path)])
        rows.append(GoldenRow(utterance="greetings to you", lang="en-US",
                              skill_id=SKILL_ID,
                              expected_intent="HelloIntent",
                              provenance={"machine_generated": True}))
        results = run_rows(rows, SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        by_utt = {r.utterance: r for r in results}
        self.assertTrue(by_utt["greetings to you"].gap)
        self.assertFalse(by_utt["quem te fez"].gap)

    def test_missing_resource_reads_one_locales_labels(self):
        row = GoldenRow(utterance="quem te fez", lang="pt-PT",
                        skill_id=SKILL_ID, expected_intent="HelloIntent",
                        provenance={"machine_generated": True})
        label = f"{SKILL_ID}:HelloIntent"
        self.assertEqual(missing_resource(row, SKILL_ID, self.checkout),
                         "HelloIntent")
        self.assertIsNone(missing_resource(row, SKILL_ID, self.checkout,
                                           known_labels={label}))


@unittest.skipUnless(is_pipeline_available(LEAN_DEFAULT_PIPELINE),
                     "lean pipeline plugins not installed")
class TestGapFieldsSurviveTheWorker(unittest.TestCase):
    """T-3735: ``gap`` and ``reason`` cross the worker's JSON result file.

    ``run_rows_per_locale`` runs the coverage-gap pass inside each child,
    one locale per child, and the parent rebuilds every row with
    ``RowResult(**r)``. The two fields are dataclass fields, so ``as_dict``
    carries them; this asserts it, because a silent drop reads as a run
    with no gaps at all.
    """

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-wgap-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_skill(cls.checkout, "golden_wgap_skill")
        (cls.checkout / "locale" / "en-US" / "who_is.dialog").write_text(
            "i am a test skill\n", encoding="utf-8")
        cls.rows_path = cls.checkout / "test" / "end2end" / "golden_utterances_all.jsonl"
        _write_rows(cls.rows_path, GAP_ROWS)
        (cls.checkout / "golden_worker_hook.py").write_text(GAP_HOOK_SRC,
                                                            encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("golden_wgap_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _child_env(self):
        path = os.pathsep.join([str(self.checkout),
                                os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        return mock.patch.dict(
            os.environ, {"OVOSCOPE_GOLDEN_FACTORY": "golden_worker_hook:factory",
                         "PYTHONPATH": path})

    def test_the_gap_and_the_reason_come_back_from_the_child(self):
        rows = collect_rows([str(self.rows_path)])
        with self._child_env():
            results = run_rows_per_locale(rows, SKILL_ID, self.checkout)
        by_utt = {r.utterance: r for r in results}
        gap = by_utt["who made you"]
        self.assertTrue(gap.gap)
        self.assertIn("coverage-gap", gap.reason)
        wrong = by_utt["who are you"]
        self.assertFalse(wrong.gap)
        self.assertIn("who.is", wrong.reason)
class TestTheBoundIsLiveOnTheProductionPath(unittest.TestCase):
    """The bound must hold for a root_dir built the way a skill builds it.

    T-5641. The first cut of this bound never ran in production. ovos-workshop
    sets a skill's root directory to its own class module's directory:

        self.root_dir = dirname(abspath(sys.modules[self.__module__].__file__))

    and ``run_rows`` passes exactly that to ``own_package``. So the class module
    is always directly inside the root, the relative path always has one part,
    and a function that answered None for "one part" answered None for every
    real skill, which is the undetermined case that takes the WIDE bound. The
    sibling package the bound was written to exclude still answered.

    These fixtures therefore do not pass a hand-made root: they write a module
    on disk, import it, and derive the root the way ovos-workshop does.
    """

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-prod-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.checkout = self.tmp / "checkout"

    def _write(self, rel, text="x\n"):
        path = self.checkout / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _load(self, module_rel, name):
        """Import a module from the fixture and return its class."""
        import importlib.util
        src = self._write(module_rel, "class TheSkill:\n    pass\n")
        spec = importlib.util.spec_from_file_location(name, src)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
        return module.TheSkill

    @staticmethod
    def _root_dir_of(cls):
        """What ovos-workshop would set as this skill's root_dir."""
        return Path(os.path.dirname(os.path.abspath(
            sys.modules[cls.__module__].__file__)))

    @staticmethod
    def _minicroft_holding(cls):
        loader = type("Loader", (), {"instance": cls()})()
        return type("MiniCroft", (), {"plugin_skills": {SKILL_ID: loader}})()

    def _sibling(self):
        self._write("other_skill_pkg/__init__.py", "")
        self._write("other_skill_pkg/locale/en-US/sibling_dialog.dialog")

    def test_the_packaged_layout_reads_its_own_tree_only(self):
        cls = self._load("my_skill/__init__.py", "t5641_pkg_skill")
        self._write("my_skill/locale/en-US/own_dialog.dialog")
        self._sibling()
        root = self._root_dir_of(cls)
        self.assertEqual(root, self.checkout / "my_skill")
        package = own_package(self._minicroft_holding(cls), SKILL_ID, root)
        self.assertEqual(package, NO_PACKAGE)
        self.assertEqual(locale_resources(root, "en-US", package),
                         {"own_dialog"})

    def test_the_legacy_layout_drops_the_sibling_package(self):
        """The hole this task exists to close: root_dir IS the checkout here,
        so a sibling package is a direct child of it."""
        cls = self._load("__init__.py", "t5641_legacy_skill")
        self._write("locale/en-US/own_dialog.dialog")
        self._sibling()
        root = self._root_dir_of(cls)
        self.assertEqual(root, self.checkout)
        package = own_package(self._minicroft_holding(cls), SKILL_ID, root)
        self.assertEqual(package, NO_PACKAGE)
        self.assertEqual(_own_locale_roots(root, package), [root])
        names = locale_resources(root, "en-US", package)
        self.assertEqual(names, {"own_dialog"})
        self.assertNotIn("sibling_dialog", names)

    def test_a_sibling_resource_is_a_miss_on_the_legacy_layout(self):
        """Stated as the runner sees it: the sibling's name is not real, and
        the skill's own name still is."""
        cls = self._load("__init__.py", "t5641_legacy_miss")
        self._write("locale/en-US/own_dialog.dialog")
        self._sibling()
        root = self._root_dir_of(cls)
        package = own_package(self._minicroft_holding(cls), SKILL_ID, root)

        def _row(expected):
            return GoldenRow(utterance="x", lang="en-US", skill_id=SKILL_ID,
                             expected_intent=expected,
                             provenance={"machine_generated": True})

        self.assertEqual(missing_resource(_row("sibling_dialog"), SKILL_ID,
                                          root, package=package),
                         "sibling_dialog")
        self.assertIsNone(missing_resource(_row("own_dialog"), SKILL_ID, root,
                                           package=package))

    def test_the_sentinel_cannot_collapse_into_none(self):
        """reviewer-b's hold point. Three answers in a two-valued type is how a
        third state disappears: an empty string would read the same as None to
        any consumer that tested truthiness, and the wide bound would come back
        in silence. NO_PACKAGE is therefore truthy and is not a string, so
        `if package:` takes the NAME branch and raises on `root / package`
        instead of quietly widening."""
        self.assertIsNotNone(NO_PACKAGE)
        self.assertNotEqual(NO_PACKAGE, None)
        self.assertNotEqual(NO_PACKAGE, "")
        self.assertTrue(NO_PACKAGE)
        self.assertNotIsInstance(NO_PACKAGE, str)
        self.assertIs(NO_PACKAGE, NO_PACKAGE)

    def test_a_truthiness_test_would_raise_rather_than_widen(self):
        """The guard the previous test exists for, driven: whatever a careless
        consumer does with NO_PACKAGE, it must not silently read a neighbour's
        tree."""
        with self.assertRaises(TypeError):
            _ = self.checkout / NO_PACKAGE

    def test_an_undetermined_package_is_none_not_no_package(self):
        """A class whose module is outside the root cannot name a package, and
        that must stay distinguishable from the definite NO_PACKAGE."""
        import importlib.util
        outside = self.tmp / "elsewhere"
        outside.mkdir(parents=True)
        src = outside / "stray.py"
        src.write_text("class TheSkill:\n    pass\n", encoding="utf-8")
        spec = importlib.util.spec_from_file_location("t5641_stray", src)
        module = importlib.util.module_from_spec(spec)
        sys.modules["t5641_stray"] = module
        self.addCleanup(sys.modules.pop, "t5641_stray", None)
        spec.loader.exec_module(module)
        self.checkout.mkdir(parents=True, exist_ok=True)
        self.assertIsNone(own_package(
            self._minicroft_holding(module.TheSkill), SKILL_ID, self.checkout))
@unittest.skipUnless(is_pipeline_available(LEAN_DEFAULT_PIPELINE),
                     "lean pipeline plugins not installed")
class TestTheBoundThroughRunRows(unittest.TestCase):
    """The bound driven through ``run_rows``, not through the helpers.

    T-5641, and reviewer-b's point that a mutation is only as good as its
    caller: the previous round proved the bound with probes that passed a
    hand-made root, and ``run_rows`` cannot produce that root. This drives the
    whole chain instead, ``assert_root_dir`` -> ``own_package`` ->
    ``_mark_coverage_gaps`` -> ``missing_resource``, on a real MiniCroft.

    ``_write_skill`` puts the skill's module at ``<checkout>/<module>.py``, so
    the skill's ``root_dir`` IS the checkout: the legacy top-level layout, and
    the one where a sibling package sits directly beside the skill.
    """

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-runrows-"))
        cls.checkout = cls.tmp / "checkout"
        cls.skill_cls = _write_skill(cls.checkout, "runrows_fixture_skill")
        # a second skill vendored beside this one, with a resource of its own
        sibling = cls.checkout / "other_skill_pkg"
        (sibling / "locale" / "en-US").mkdir(parents=True)
        (sibling / "__init__.py").write_text("", encoding="utf-8")
        (sibling / "locale" / "en-US" / "sibling_dialog.dialog").write_text(
            "not this skill's\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("runrows_fixture_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _factory(self):
        skill_cls = self.skill_cls

        def factory(skill_id, lang, pipeline):
            return get_minicroft([skill_id], lang=lang,
                                 extra_skills={skill_id: skill_cls})
        return factory

    def _run(self, expected_intent):
        row = GoldenRow(utterance="say something no intent matches",
                        lang="en-US", skill_id=SKILL_ID,
                        expected_intent=expected_intent,
                        provenance={"machine_generated": True})
        results = run_rows([row], SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        self.assertEqual(len(results), 1)
        return results[0]

    def test_the_root_dir_a_real_skill_reports_is_the_checkout(self):
        """The premise the rest of this class rests on, asserted rather than
        assumed: this is why own_package sees one path part."""
        root = Path(os.path.dirname(os.path.abspath(
            sys.modules[self.skill_cls.__module__].__file__)))
        self.assertEqual(root, self.checkout)

    def test_a_sibling_resource_is_a_miss_not_a_coverage_gap(self):
        """The hole, stated as a golden run reports it. Under the wide bound
        `sibling_dialog` was a real name, so this row was excused as a coverage
        gap; it must be a miss that names the resource nobody ships."""
        result = self._run("sibling_dialog")
        self.assertFalse(result.matched)
        self.assertFalse(result.gap,
                         "a neighbour's resource excused this row as a gap")
        self.assertIn("sibling_dialog", result.reason or "")

    def test_the_skills_own_resource_is_still_a_coverage_gap(self):
        """The control. The bound must not make the skill's OWN names
        unreadable: `hello` is a resource this skill ships for en-US, so a
        machine-drafted row that misses on it is a genuine coverage gap."""
        result = self._run("hello")
        self.assertFalse(result.matched)
        self.assertTrue(result.gap, result.reason)
        self.assertIn("coverage-gap", result.reason or "")
class TestTheWideBoundSaysSoInTheResult(unittest.TestCase):
    """A gap judged without knowing the skill's package must not look clean.

    reviewer-b's point on the fallback: keeping the wide branch is right, but it
    must not be takeable quietly. A coverage gap excused by a neighbour's
    resource is invisible in the result, and a log line is not something a CI
    reader opens, so the reason string carries the note and the summary counts
    it.
    """

    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp(prefix="ovoscope-widebound-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        loc = self.root / "locale" / "en-US"
        loc.mkdir(parents=True)
        # the skill really ships this name, so a machine-drafted miss on it is
        # a genuine coverage gap in BOTH bounds; only the note differs
        (loc / "whatever.dialog").write_text("x\n", encoding="utf-8")

    def _gap_reason(self, skill_package):
        row = GoldenRow(utterance="x", lang="en-US", skill_id=SKILL_ID,
                        expected_intent="whatever",
                        provenance={"machine_generated": True})
        result = RowResult("x", "en-US", "whatever", [], False, True, 0.0)
        _mark_coverage_gaps([result], [row], SKILL_ID, self.root, {},
                            skill_package)
        self.assertTrue(result.gap, result.reason)
        return result

    def test_the_note_is_on_the_reason_under_the_wide_bound(self):
        result = self._gap_reason(None)
        self.assertIn(WIDE_BOUND_NOTE, result.reason)
        self.assertIn("coverage-gap", result.reason)

    def test_there_is_no_note_when_the_package_is_known(self):
        """NO_PACKAGE is a definite answer, so the bound WAS applied."""
        result = self._gap_reason(NO_PACKAGE)
        self.assertNotIn(WIDE_BOUND_NOTE, result.reason)
        self.assertIn("coverage-gap", result.reason)

    def test_the_summary_can_see_it_on_the_scoreboard(self):
        """The note has to survive into what run_golden reads, or the summary
        line can never fire."""
        result = self._gap_reason(None)
        board = scoreboard([result], SKILL_ID)[f"minicroft:{SKILL_ID}"]
        self.assertEqual(len(board["gaps"]), 1)
        self.assertIn(WIDE_BOUND_NOTE, board["gaps"][0]["reason"])


RES_SKILL_SRC = textwrap.dedent('''
    from ovos_bus_client.message import Message
    from ovos_workshop.decorators import intent_handler
    from ovos_workshop.intents import IntentBuilder
    from ovos_workshop.skills.ovos import OVOSSkill

    RESOURCES = {resources!r}


    class ResDirFixtureSkill(OVOSSkill):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("resources_dir", RESOURCES)
            super().__init__(*args, **kwargs)

        @intent_handler(IntentBuilder("HelloIntent").require("hello"))
        def handle_hello(self, message: Message):
            self.speak("hi", wait=False)
''')


def _write_res_dir_skill(root: Path, resources: Path, module_name: str):
    """A skill whose resources live somewhere its ``root_dir`` does not hold.

    ovos-workshop keeps ``root_dir`` at the module's own directory and sets
    ``res_dir`` to ``resources_dir``. The two trees are written apart on
    purpose, each with a name the other does not have.
    """
    for lang, words in VOC.items():
        (resources / "locale" / lang).mkdir(parents=True)
        (resources / "locale" / lang / "hello.voc").write_text(
            words, encoding="utf-8")
    # a name under root_dir alone: the skill does not read this tree
    (root / "locale" / "en-US").mkdir(parents=True)
    (root / "locale" / "en-US" / "root_only.dialog").write_text(
        "not read by this skill\n", encoding="utf-8")
    (root / f"{module_name}.py").write_text(
        RES_SKILL_SRC.format(resources=str(resources)), encoding="utf-8")
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(module_name)
    finally:
        sys.path.remove(str(root))
    return module.ResDirFixtureSkill


class TestTheBoundFollowsResDir(unittest.TestCase):
    """The bound reads the tree the skill READS, which is ``res_dir``.

    T-5750. ovos-workshop ``skills/ovos.py`` sets
    ``self.res_dir = resources_dir or self.root_dir`` and every loader reads
    ``res_dir``. A bound on ``root_dir`` alone therefore finds no name at all
    for a skill built with ``resources_dir=``, and the skill's OWN resource
    reads as a name nobody ships: a correct row accused, which fails a run
    that should pass. This class drives the whole chain through ``run_rows``
    on a real MiniCroft, because the unit path with a hand-made root is what
    hid the first hole.
    """

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ovoscope-golden-resdir-"))
        cls.checkout = cls.tmp / "checkout"
        cls.resources = cls.checkout / "shared_resources"
        cls.skill_cls = _write_res_dir_skill(cls.checkout, cls.resources,
                                             "resdir_fixture_skill")

    @classmethod
    def tearDownClass(cls):
        LOG.set_level("CRITICAL")
        sys.modules.pop("resdir_fixture_skill", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _factory(self):
        skill_cls = self.skill_cls

        def factory(skill_id, lang, pipeline):
            return get_minicroft([skill_id], lang=lang,
                                 extra_skills={skill_id: skill_cls})
        return factory

    def _run(self, expected_intent):
        row = GoldenRow(utterance="say something no intent matches",
                        lang="en-US", skill_id=SKILL_ID,
                        expected_intent=expected_intent,
                        provenance={"machine_generated": True})
        results = run_rows([row], SKILL_ID, self.checkout,
                           minicroft_factory=self._factory())
        self.assertEqual(len(results), 1)
        return results[0]

    def test_the_two_trees_really_are_apart(self):
        """The premise, asserted rather than assumed: the fixture's root_dir
        is the checkout and its res_dir is a directory the root does not
        hold, so the two bounds cannot agree by accident."""
        root = Path(os.path.dirname(os.path.abspath(
            sys.modules[self.skill_cls.__module__].__file__)))
        self.assertEqual(root, self.checkout)
        self.assertNotEqual(self.resources.resolve(), root.resolve())
        self.assertEqual(locale_resources(self.resources, "en-US", NO_PACKAGE),
                         {"hello"})
        self.assertEqual(locale_resources(self.checkout, "en-US", NO_PACKAGE),
                         {"root_only"})

    def test_the_skills_own_resource_under_res_dir_is_a_coverage_gap(self):
        """The defect this round fixes. `hello` is this skill's own name, in
        the only tree it reads. Bounded on root_dir the run reported it as a
        name nobody ships and failed; it is a coverage gap."""
        result = self._run("hello")
        self.assertFalse(result.matched)
        self.assertTrue(result.gap, result.reason)
        self.assertIn("coverage-gap", result.reason or "")

    def test_a_name_under_root_dir_alone_is_still_a_miss(self):
        """The control that keeps the fix from being a widening. The bound
        MOVED to res_dir, it did not grow to hold both trees: a name the
        skill cannot read is still a defect in the row."""
        result = self._run("root_only")
        self.assertFalse(result.matched)
        self.assertFalse(result.gap,
                         "a tree the skill never reads excused this row")
        self.assertIn("root_only", result.reason or "")


class TestResDirIsCheckedLikeRootDir(unittest.TestCase):
    """``res_dir`` outside the checkout, or installed inside it, is REFUSED.

    The decision this round settles: a resources tree whose names cannot be
    shown to be the checkout's own source is not read at all. Accepting it
    would let another copy's resource excuse a wrong gold row, which is
    T-3140 from a new direction, and the failure would be silent. A refusal
    exits EXIT_ROOT_DIR and says which path it read.
    """

    class _Loader:
        def __init__(self, root, res):
            self.instance = type("S", (), {"root_dir": str(root),
                                           "res_dir": str(res)})()

    def _mc(self, root, res):
        return type("MC", (),
                    {"plugin_skills": {SKILL_ID: self._Loader(root, res)}})()

    def setUp(self):
        self.checkout = Path(tempfile.mkdtemp(prefix="ovoscope-resdir-"))
        self.addCleanup(shutil.rmtree, self.checkout, ignore_errors=True)
        self.root = self.checkout / "ovos_skill_x"
        self.root.mkdir()

    def _assert(self, res):
        return assert_res_dir(self._mc(self.root, res), SKILL_ID,
                              self.checkout, self.root.resolve())

    def test_a_skill_that_sets_nothing_keeps_its_root(self):
        """res_dir IS root_dir unless resources_dir was passed, so the
        common case collapses to the bound this round started with."""
        self.assertEqual(self._assert(self.root), self.root.resolve())

    def test_a_resources_dir_inside_the_checkout_is_accepted(self):
        shared = self.checkout / "shared_resources"
        shared.mkdir()
        self.assertEqual(self._assert(shared), shared.resolve())

    def test_a_resources_dir_outside_the_checkout_is_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="ovoscope-outside-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with self.assertRaises(RootDirMismatch) as caught:
            self._assert(outside)
        self.assertIn(str(outside.resolve()), str(caught.exception))

    def test_an_installed_resources_dir_inside_the_checkout_is_refused(self):
        for seg in ("site-packages", "dist-packages", ".venv", "venv"):
            bad = self.checkout / seg / "ovos_skill_x"
            bad.mkdir(parents=True)
            with self.assertRaises(RootDirMismatch, msg=seg):
                self._assert(bad)

    def test_a_skill_that_did_not_load_is_named(self):
        mc = type("MC", (), {"plugin_skills": {}})()
        with self.assertRaises(RootDirMismatch):
            assert_res_dir(mc, SKILL_ID, self.checkout, self.root)
