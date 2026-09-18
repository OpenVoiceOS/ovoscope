"""M2V_DUAL_PIPELINE runs the classifier before the prototype stage at
every tier (T-1621 section 3.1: prototype first lost 6 of 53 volume rows
and 7 of 117 alerts handler tests on the v6 provisional model)."""
import unittest

from ovoscope import M2V_DUAL_PIPELINE


class TestM2VDualOrder(unittest.TestCase):

    def test_classifier_precedes_prototype_in_every_tier(self):
        for tier in ("high", "medium", "low"):
            clf = M2V_DUAL_PIPELINE.index(f"ovos-m2v-pipeline-{tier}")
            proto = M2V_DUAL_PIPELINE.index(f"ovos-m2v-prototype-pipeline-{tier}")
            fallback = M2V_DUAL_PIPELINE.index(f"ovos-fallback-pipeline-plugin-{tier}")
            self.assertLess(clf, proto, tier)
            self.assertLess(proto, fallback, tier)

    def test_both_engines_present_once_per_tier(self):
        for tier in ("high", "medium", "low"):
            self.assertEqual(M2V_DUAL_PIPELINE.count(f"ovos-m2v-pipeline-{tier}"), 1)
            self.assertEqual(
                M2V_DUAL_PIPELINE.count(f"ovos-m2v-prototype-pipeline-{tier}"), 1)
