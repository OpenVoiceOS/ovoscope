"""The lang patch must survive a stop order that is not last-in-first-out.

A dict of live MiniCrofts is stopped in insertion order. Before the fix each
instance saved as its "original" the lang the previous instance had already
written, so the first stop restored the true original and the second stop then
wrote the first instance's lang back. The process was left on a foreign locale.
"""
import unittest

from ovos_bus_client.session import SessionManager
from ovos_config.config import Configuration
from ovos_utils.log import LOG

from ovoscope import get_minicroft


class TestLangRestoreOrder(unittest.TestCase):

    def setUp(self):
        LOG.set_level("ERROR")
        self.original_session_lang = SessionManager.get_default_session().lang
        self.had_cfg_lang = "lang" in Configuration()
        self.original_cfg_lang = Configuration().get("lang")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _assert_restored(self):
        self.assertEqual(SessionManager.get_default_session().lang,
                         self.original_session_lang)
        self.assertEqual("lang" in Configuration(), self.had_cfg_lang)
        self.assertEqual(Configuration().get("lang"), self.original_cfg_lang)

    def test_lang_applied_while_live(self):
        """Positive control: a lang boot really does move the default lang.

        Without this control a restore test passes on a build where the lang
        argument does nothing at all.
        """
        mc = get_minicroft([], lang="de-DE")
        try:
            self.assertEqual(SessionManager.get_default_session().lang, "de-DE")
            self.assertEqual(Configuration().get("lang"), "de-DE")
        finally:
            mc.stop()
        self._assert_restored()

    def test_two_langs_stopped_in_dict_order(self):
        """Stop in insertion order, not in reverse. The lang must come back."""
        crofts = {}
        crofts["de-DE"] = get_minicroft([], lang="de-DE")
        try:
            crofts["fr-FR"] = get_minicroft([], lang="fr-FR")
        except Exception:
            crofts["de-DE"].stop()
            raise
        try:
            for croft in crofts.values():  # de-DE first, then fr-FR
                croft.stop()
        except Exception:
            for croft in crofts.values():
                try:
                    croft.stop()
                except Exception:
                    pass
            raise
        self._assert_restored()

    def test_two_langs_stopped_last_in_first_out(self):
        """The order that already worked must keep working."""
        outer = get_minicroft([], lang="de-DE")
        try:
            inner = get_minicroft([], lang="fr-FR")
            inner.stop()
            # Note: the inner stop already puts the session lang back to the
            # outermost original, although the outer harness is still live.
            # A test that needs the outer lang after an inner harness stops
            # must set it again. This test measures the end state only.
        finally:
            outer.stop()
        self._assert_restored()


if __name__ == "__main__":
    unittest.main()
