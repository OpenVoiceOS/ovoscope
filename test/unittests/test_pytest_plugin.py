"""Unit tests for ovoscope.pytest_plugin — the ``minicroft`` fixture.

Since pytest fixtures can't be called directly, we test the underlying
logic by importing the module and inspecting/mocking its internals.
"""
import unittest
from unittest.mock import MagicMock, patch

import ovoscope.pytest_plugin as plugin_mod


class TestMinicroftFixtureLogic(unittest.TestCase):
    """Tests for the fixture's skill_ids extraction and lifecycle."""

    def test_module_has_minicroft_fixture(self):
        """The module exposes a 'minicroft' callable."""
        self.assertTrue(hasattr(plugin_mod, "minicroft"))
        self.assertTrue(callable(plugin_mod.minicroft))

    @patch.object(plugin_mod, "get_minicroft")
    def test_skill_ids_read_from_class(self, mock_get):
        """The fixture function reads skill_ids from request.cls."""
        mock_mc = MagicMock()
        mock_get.return_value = mock_mc

        request = MagicMock()
        request.cls = type("FakeTest", (), {"skill_ids": ["skill-a.test"]})

        # Call the underlying generator function directly (bypassing pytest's
        # fixture decorator which blocks direct calls in newer pytest versions)
        gen = plugin_mod.minicroft.__wrapped__(request)
        mc = next(gen)

        mock_get.assert_called_once_with(["skill-a.test"])
        self.assertIs(mc, mock_mc)

        try:
            next(gen)
        except StopIteration:
            pass
        mock_mc.stop.assert_called_once()

    @patch.object(plugin_mod, "get_minicroft")
    def test_string_skill_ids_normalized(self, mock_get):
        """A single string skill_ids is wrapped into a list."""
        mock_mc = MagicMock()
        mock_get.return_value = mock_mc

        request = MagicMock()
        request.cls = type("FakeTest", (), {"skill_ids": "single.test"})

        gen = plugin_mod.minicroft.__wrapped__(request)
        next(gen)
        mock_get.assert_called_once_with(["single.test"])

        try:
            next(gen)
        except StopIteration:
            pass

    @patch.object(plugin_mod, "get_minicroft")
    def test_missing_skill_ids_defaults_empty(self, mock_get):
        """If the test class has no skill_ids, default to []."""
        mock_mc = MagicMock()
        mock_get.return_value = mock_mc

        request = MagicMock()
        request.cls = type("FakeTest", (), {})

        gen = plugin_mod.minicroft.__wrapped__(request)
        next(gen)
        mock_get.assert_called_once_with([])

        try:
            next(gen)
        except StopIteration:
            pass

    @patch.object(plugin_mod, "get_minicroft")
    def test_stop_called_on_exception(self, mock_get):
        """mc.stop() is called even if the test body raises."""
        mock_mc = MagicMock()
        mock_get.return_value = mock_mc

        request = MagicMock()
        request.cls = type("FakeTest", (), {"skill_ids": []})

        gen = plugin_mod.minicroft.__wrapped__(request)
        next(gen)

        try:
            gen.throw(RuntimeError("test failure"))
        except RuntimeError:
            pass
        mock_mc.stop.assert_called_once()

    @patch.object(plugin_mod, "get_minicroft", side_effect=TimeoutError("boom"))
    def test_get_minicroft_failure_no_name_error(self, mock_get):
        """If get_minicroft raises, teardown must not raise NameError."""
        request = MagicMock()
        request.cls = type("FakeTest", (), {"skill_ids": []})

        gen = plugin_mod.minicroft.__wrapped__(request)
        with self.assertRaises(TimeoutError):
            next(gen)


if __name__ == "__main__":
    unittest.main()


class TestModuleLevelSkipDoesNotAbortCollection:
    """Regression test: a module-level ``pytest.importorskip()``/``pytest.skip()``
    used to abort the *entire* collection session instead of skipping just
    that one module.

    ``pytest.skip.Exception`` subclasses ``BaseException`` (via
    ``_pytest.outcomes.OutcomeException``), not ``Exception``. The ovoscope
    ``pytest_pycollect_makemodule`` hook wrapper imports every collected
    module eagerly (to look for the ``ovoscope_intent_cases`` shim marker)
    guarded only by ``except Exception``. That guard never sees the skip
    exception, so it escapes the hook wrapper uncaught and pytest reports
    "found no collectors" / exit code 5 for the whole run, even though only
    one of the test files actually wanted to be skipped.
    """

    def test_importorskip_module_does_not_nuke_collection(self, pytester):
        pytester.makepyfile(
            test_skips_at_import="""
            import pytest
            pytest.importorskip("this_module_does_not_exist_xyz")

            def test_never_runs():
                assert False
            """
        )
        pytester.makepyfile(
            test_plain="""
            def test_ok():
                assert True
            """
        )

        result = pytester.runpytest()

        result.assert_outcomes(passed=1, skipped=1)
        assert result.ret == 0


class TestAnUnimportableModuleIsNeverSilent:
    """Regression test: the swallow above must not turn a failed import into
    an absence under ``--import-mode=importlib``.

    ``pytest_pycollect_makemodule`` touches ``collector.obj`` to look for the
    ``ovoscope_intent_cases`` shim marker, and swallows whatever the import
    raises so a module-level skip cannot abort the session. Its premise is
    that pytest's own protected collection call imports the module again and
    reports the failure there. Measured on pytest 9.1.1, that premise holds
    under the default prepend mode and fails under importlib:

    * prepend — the failed import leaves nothing in ``sys.modules``, so the
      next access raises the same error and pytest reports a collection error;
    * importlib — the half-executed module STAYS in ``sys.modules``, so the
      next access returns that module object instead. It carries no test
      functions, because execution stopped at the failing line, so the
      collector yields no items, pytest prints nothing and exits 0.

    This hook is the first thing to touch ``collector.obj``, so it consumes
    the one attempt that ever raises. ``_forget_failed_module`` drops the
    corpse so the re-import really happens.

    Measured before the fix on a three-file reproduction: with an installed
    package made unimportable, importlib plus this plugin exited 0 with no
    diagnostic, while the same tree with ``-p no:ovoscope`` exited 2 and
    printed the error (T-6264, from reviewer-b's T-6242).
    """

    FAILING = """
        raise RuntimeError("OVOSCOPE_IMPORT_SENTINEL")

        def test_never_runs():
            assert False
        """
    PLAIN = """
        def test_ok():
            assert True
        """

    def _run(self, pytester, *args):
        pytester.makepyfile(test_broken_import=self.FAILING)
        pytester.makepyfile(test_plain=self.PLAIN)
        return pytester.runpytest(*args)

    def test_the_failure_is_reported_under_importlib(self, pytester):
        """The defect. This is the arm that exited 0 and said nothing."""
        result = self._run(pytester, "--import-mode=importlib")
        assert result.ret != 0, "an unimportable module passed for silence"
        result.stdout.fnmatch_lines(["*OVOSCOPE_IMPORT_SENTINEL*"])

    def test_the_failure_is_reported_under_prepend(self, pytester):
        """The control: prepend mode always reported it, and still does."""
        result = self._run(pytester)
        assert result.ret != 0
        result.stdout.fnmatch_lines(["*OVOSCOPE_IMPORT_SENTINEL*"])

    def test_the_two_import_modes_agree(self, pytester):
        """The property that was broken: the plugin must not make the choice
        of import mode decide whether a failure is visible."""
        prepend = self._run(pytester)
        pytester.path.joinpath("__pycache__").exists()  # touch nothing else
        importlib_run = self._run(pytester, "--import-mode=importlib")
        assert prepend.ret == importlib_run.ret

    def test_the_sound_module_in_the_same_run_is_unaffected(self, pytester):
        """One bad module must not take the others with it: the point of
        swallowing rather than raising out of the hook wrapper.

        pytest's own default is to stop the session on a collection error, so
        the other module runs only under ``--continue-on-collection-errors``.
        That is pytest's policy and not this plugin's, and the check here is
        that the sound module is still collectable and still passes while the
        broken one errors.
        """
        result = self._run(pytester, "--import-mode=importlib",
                           "--continue-on-collection-errors")
        result.assert_outcomes(passed=1, errors=1)


class TestAModuleLevelSkipSurvivesImportlibToo:
    """The case the swallow exists for, measured in both import modes.

    On the tree before this fix, a module-level skip under
    ``--import-mode=importlib`` was not reported as a skip at all: a run of
    one plain module and two skipping modules read "1 passed", with the two
    skips missing from the report entirely. Under prepend the same run read
    "1 passed, 2 skipped". Dropping the half-executed module makes the two
    modes agree.
    """

    def _write(self, pytester):
        pytester.makepyfile(
            test_module_skip="""
            import pytest
            pytest.skip("module level skip", allow_module_level=True)

            def test_never():
                assert False
            """
        )
        pytester.makepyfile(
            test_importorskip="""
            import pytest
            pytest.importorskip("totally_absent_module_xyz")

            def test_never2():
                assert False
            """
        )
        pytester.makepyfile(
            test_ok="""
            def test_c():
                assert True
            """
        )

    def test_both_skips_are_reported_under_importlib(self, pytester):
        self._write(pytester)
        result = pytester.runpytest("--import-mode=importlib")
        result.assert_outcomes(passed=1, skipped=2)
        assert result.ret == 0

    def test_both_skips_are_reported_under_prepend(self, pytester):
        self._write(pytester)
        result = pytester.runpytest()
        result.assert_outcomes(passed=1, skipped=2)
        assert result.ret == 0


class TestForgetFailedModuleTouchesOnlyItsOwnModule:
    """``_forget_failed_module`` is named by path, not by guessed module name.

    Under importlib the name pytest derives depends on the rootdir and on
    ``consider_namespace_packages``, so a guess would silently do nothing.
    The helper compares ``__file__`` instead. It must evict only the corpse the
    failed import just created, which it tells apart by taking the set of
    ``sys.modules`` keys from before the import: an entry that was already
    there is not this hook's corpse.
    """

    def test_only_the_named_file_is_dropped(self, tmp_path):
        import sys
        import types

        from ovoscope.pytest_plugin import _forget_failed_module

        target = tmp_path / "victim.py"
        target.write_text("", encoding="utf-8")
        neighbour = tmp_path / "bystander.py"
        neighbour.write_text("", encoding="utf-8")

        known_before = frozenset(sys.modules)
        victim = types.ModuleType("ovoscope_test_victim")
        victim.__file__ = str(target)
        bystander = types.ModuleType("ovoscope_test_bystander")
        bystander.__file__ = str(neighbour)
        sys.modules["ovoscope_test_victim"] = victim
        sys.modules["ovoscope_test_bystander"] = bystander
        try:
            _forget_failed_module(target, known_before)
            assert "ovoscope_test_victim" not in sys.modules
            assert "ovoscope_test_bystander" in sys.modules
        finally:
            sys.modules.pop("ovoscope_test_victim", None)
            sys.modules.pop("ovoscope_test_bystander", None)

    def test_a_module_with_no_file_is_survived(self, tmp_path):
        """A builtin or namespace module has no ``__file__``; the helper must
        not raise on one."""
        import sys
        import types

        from ovoscope.pytest_plugin import _forget_failed_module

        odd = types.ModuleType("ovoscope_test_no_file")
        sys.modules["ovoscope_test_no_file"] = odd
        try:
            _forget_failed_module(tmp_path / "absent.py", frozenset(sys.modules))
            assert "ovoscope_test_no_file" in sys.modules
        finally:
            sys.modules.pop("ovoscope_test_no_file", None)

    def test_a_healthy_twin_of_the_same_file_is_kept(self, tmp_path):
        """The same file under two names, one of them loaded beforehand.

        ``realpath`` makes a symlinked test file collide with its target by
        construction, and the same file collected through two rootdirs does the
        same. Matching on the path alone evicted the healthy entry as well,
        which re-executes the module on the next import and breaks every
        identity check against a class captured before collection. Only the
        entry that appeared during the failed import is the corpse.
        """
        import sys
        import types

        from ovoscope.pytest_plugin import _forget_failed_module

        target = tmp_path / "twin.py"
        target.write_text("", encoding="utf-8")

        healthy = types.ModuleType("ovoscope_test_twin_healthy")
        healthy.__file__ = str(target)
        sys.modules["ovoscope_test_twin_healthy"] = healthy
        # The snapshot is taken here, as the hook takes it: after the healthy
        # import, before the one that fails.
        known_before = frozenset(sys.modules)
        corpse = types.ModuleType("ovoscope_test_twin_corpse")
        corpse.__file__ = str(target)
        sys.modules["ovoscope_test_twin_corpse"] = corpse
        try:
            _forget_failed_module(target, known_before)
            assert "ovoscope_test_twin_corpse" not in sys.modules
            assert "ovoscope_test_twin_healthy" in sys.modules
            assert sys.modules["ovoscope_test_twin_healthy"] is healthy
        finally:
            sys.modules.pop("ovoscope_test_twin_corpse", None)
            sys.modules.pop("ovoscope_test_twin_healthy", None)


class TestASymlinkedTwinKeepsItsClassIdentity:
    """The whole mechanism of the twin case, through a real nested pytest.

    ``shared.py`` exports a class and skips at module level only when it is
    collected under its test name. ``test_shared.py`` is a symlink to it, so
    one file sits in ``sys.modules`` twice: once as the healthy ``shared`` a
    conftest imported, once as the module the skip aborts half-way. Before the
    snapshot the healthy entry was evicted with the corpse, in prepend mode as
    well as importlib, where the behaviour had been correct. The run then
    re-executes ``shared`` on the next import and the class object it exports
    is no longer the one already held.
    """

    SHARED = '''
        import pytest

        class Marker:
            pass

        if __name__.startswith("test_"):
            pytest.skip("collected under its test name", allow_module_level=True)
        '''

    CONFTEST = '''
        import os
        import sys

        # importlib mode does not put the rootdir on sys.path; a consumer that
        # imports a helper module beside its tests does this itself.
        sys.path.insert(0, os.path.dirname(__file__))

        import shared

        SHARED_MODULE = shared
        CAPTURED = shared.Marker
        '''

    PROBE = '''
        import importlib
        import sys

        import conftest

        def test_the_healthy_twin_is_still_the_same_object():
            assert "shared" in sys.modules, "the healthy twin was evicted"
            fresh = importlib.import_module("shared")
            assert fresh is conftest.SHARED_MODULE
            assert fresh.Marker is conftest.CAPTURED
            assert isinstance(fresh.Marker(), conftest.CAPTURED)
        '''

    def _run(self, pytester, *args):
        import textwrap

        pytester.makeconftest(textwrap.dedent(self.CONFTEST))
        shared = pytester.path / "shared.py"
        shared.write_text(textwrap.dedent(self.SHARED), encoding="utf-8")
        link = pytester.path / "test_shared.py"
        link.symlink_to(shared.name)
        probe = pytester.path / "test_probe.py"
        probe.write_text(textwrap.dedent(self.PROBE), encoding="utf-8")
        return pytester.runpytest(*args)

    def test_under_importlib(self, pytester):
        result = self._run(pytester, "--import-mode=importlib")
        result.assert_outcomes(passed=1, skipped=1)

    def test_under_prepend(self, pytester):
        """The base behaviour in this mode was already correct, so this cell is
        a guard against the fix regressing it rather than a new capability."""
        result = self._run(pytester)
        result.assert_outcomes(passed=1, skipped=1)
