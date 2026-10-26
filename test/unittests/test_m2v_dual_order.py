"""``M2V_DUAL_PIPELINE`` answers a skill's own template lines.

The list is padacioso first, then the model2vec classifier, then the
model2vec prototype stage (Miro's ruling of 2026-09-23, T-4089). The live
test fires every expanded en-US template line of ovos-skill-volume through
this list and through the pair of m2v stages alone, which is what the list
held before the ruling, and asserts that the new list leaves no line
unmatched and no line mis-routed.

The live test needs the published checkpoint in the HuggingFace cache and
ovos-skill-volume installed. It is skipped unless OVOSCOPE_LIVE=1.
"""
import os
import shutil
import tempfile
import unittest

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from ovoscope import (CaptureSession, M2V_DUAL_PIPELINE,
                      M2V_MULTILINGUAL_MODEL, get_m2v_minicroft,
                      is_pipeline_available)

LIVE = os.environ.get("OVOSCOPE_LIVE") == "1"
SKILL_ID = "ovos-skill-volume.openvoiceos"
# What M2V_DUAL_PIPELINE held before the ruling: the two m2v stages at every
# tier with no template engine ahead of them, prototype stage first.
M2V_ONLY_PIPELINE = [
    "ovos-stop-pipeline-plugin-high",
    "ovos-converse-pipeline-plugin",
    "ovos-m2v-prototype-pipeline-high",
    "ovos-m2v-pipeline-high",
    "ovos-fallback-pipeline-plugin-high",
    "ovos-stop-pipeline-plugin-medium",
    "ovos-m2v-prototype-pipeline-medium",
    "ovos-m2v-pipeline-medium",
    "ovos-fallback-pipeline-plugin-medium",
    "ovos-m2v-prototype-pipeline-low",
    "ovos-m2v-pipeline-low",
    "ovos-fallback-pipeline-plugin-low",
]


class TestM2VDualOrder(unittest.TestCase):
    """The order of the list itself. No model, no boot."""

    def test_padacioso_precedes_both_m2v_stages(self):
        pada = M2V_DUAL_PIPELINE.index("ovos-padacioso-pipeline-plugin-high")
        clf = M2V_DUAL_PIPELINE.index("ovos-m2v-pipeline-high")
        proto = M2V_DUAL_PIPELINE.index("ovos-m2v-prototype-pipeline-medium")
        self.assertLess(pada, clf)
        self.assertLess(clf, proto)

    def test_each_stage_appears_once(self):
        self.assertEqual(sorted(M2V_DUAL_PIPELINE), sorted(set(M2V_DUAL_PIPELINE)))
        self.assertEqual(M2V_DUAL_PIPELINE, [
            "ovos-padacioso-pipeline-plugin-high",
            "ovos-m2v-pipeline-high",
            "ovos-m2v-prototype-pipeline-medium",
        ])


def volume_cases():
    """Every expanded en-US template line of ovos-skill-volume.

    Returns (label, utterance) pairs. A line carrying a ``{slot}`` or an
    ``<entity>`` is left out: its match is a slot question, not an order
    question.
    """
    import ovos_skill_volume
    from ovos_utils.bracket_expansion import expand_template
    loc = os.path.join(os.path.dirname(ovos_skill_volume.__file__),
                       "locale", "en-US")
    rows = []
    for fn in sorted(os.listdir(loc)):
        if not fn.endswith(".intent"):
            continue
        label = fn[:-len(".intent")]
        with open(os.path.join(loc, fn)) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "{" in line or "<" in line:
                    continue
                for utt in expand_template(line):
                    rows.append((label, " ".join(utt.split())))
    return rows


@unittest.skipUnless(LIVE, "live m2v model test; set OVOSCOPE_LIVE=1 to enable")
class TestM2VDualOrderRoutesTemplateLines(unittest.TestCase):
    """The list answers the template lines the skill ships."""

    @classmethod
    def setUpClass(cls):
        if not is_pipeline_available(M2V_DUAL_PIPELINE):
            raise unittest.SkipTest("M2V_DUAL_PIPELINE is not installed")
        try:
            import ovos_skill_volume  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("ovos-skill-volume is not installed")
        cls.cases = volume_cases()
        if not cls.cases:
            raise unittest.SkipTest("no en-US template line without a slot")

    def _sweep(self, pipeline):
        """Fire every case on one MiniCroft pinned to ``pipeline``."""
        xdg = tempfile.mkdtemp(prefix="ovoscope-t4089-xdg-")
        saved = {v: os.environ.get(v) for v in
                 ("HOME", "HF_HOME", "XDG_CONFIG_HOME",
                  "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")}

        def _restore():
            for var, was in saved.items():
                if was is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = was
            shutil.rmtree(xdg, ignore_errors=True)

        self.addCleanup(_restore)
        # The HuggingFace cache follows HOME unless HF_HOME says otherwise.
        # Pin it to the real cache before HOME moves, or the boot goes looking
        # for the checkpoint inside the scratch directory.
        os.environ.setdefault(
            "HF_HOME", os.path.join(os.path.expanduser("~"), ".cache",
                                    "huggingface"))
        os.environ["HOME"] = xdg
        for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                    "XDG_STATE_HOME"):
            os.environ[var] = os.path.join(xdg, var.lower())

        import ovoscope
        was = ovoscope.M2V_DUAL_PIPELINE
        ovoscope.M2V_DUAL_PIPELINE = list(pipeline)
        try:
            mc = get_m2v_minicroft([SKILL_ID], model=M2V_MULTILINGUAL_MODEL,
                                   lang="en-US")
        finally:
            ovoscope.M2V_DUAL_PIPELINE = was
        prefix = f"{SKILL_ID}:"
        routed = {}
        try:
            for idx, (label, utt) in enumerate(self.cases):
                sess = Session(session_id=f"t4089-{idx}", lang="en-US")
                sess.pipeline = list(pipeline)
                cap = CaptureSession(minicroft=mc)
                cap.capture(Message("recognizer_loop:utterance",
                                    {"utterances": [utt], "lang": "en-US"},
                                    {"session": sess.serialize(),
                                     "source": "t4089",
                                     "destination": "skills"}),
                            timeout=20)
                fired = [m.msg_type[len(prefix):] for m in cap.finish()
                         if m.msg_type.startswith(prefix)]
                fired = [f[:-len(".intent")] if f.endswith(".intent") else f
                         for f in fired]
                routed[(idx, label, utt)] = fired[0] if fired else None
        finally:
            mc.stop()
        return routed

    def test_every_template_line_routes_to_its_own_intent(self):
        routed = self._sweep(M2V_DUAL_PIPELINE)
        unmatched = [k for k, got in routed.items() if got is None]
        wrong = [(k, got) for k, got in routed.items()
                 if got is not None and got != k[1]]
        self.assertEqual(unmatched, [], f"{len(unmatched)} line(s) unmatched")
        self.assertEqual(wrong, [], f"{len(wrong)} line(s) mis-routed")

    def test_the_m2v_stages_alone_do_not_answer_every_line(self):
        """The control: this is what the list did before padacioso led it.

        The test states the direction, not a count: the counts move with the
        checkpoint and with the ovos-m2v-pipeline release.
        """
        routed = self._sweep(M2V_ONLY_PIPELINE)
        missed = [(k, got) for k, got in routed.items() if got != k[1]]
        self.assertTrue(
            missed,
            "the m2v stages alone answered every template line, so this "
            "control proves nothing about the order")
