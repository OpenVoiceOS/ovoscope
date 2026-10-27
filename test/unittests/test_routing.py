"""The m2v routing tally and the session gate the pytest plugin builds on it."""
from unittest import SkipTest

import pytest

from ovoscope.routing import RoutingTally

SKILL = "my-skill.author"


def _hit(tally, method, *args):
    """Call a tally check that must not skip; a skip here is a test failure."""
    try:
        getattr(tally, method)(*args)
    except SkipTest as exc:
        pytest.fail(f"unexpected miss: {exc}")


class TestRoutingTally:

    def test_a_request_that_reaches_its_intent_is_a_hit(self):
        tally = RoutingTally()
        _hit(tally, "assert_routed", "set a timer", f"{SKILL}:timer",
             ["recognizer_loop:utterance", f"{SKILL}:timer", "speak"])
        assert (tally.hits, tally.misses, tally.rate) == (["set a timer"], [], 1.0)

    def test_a_request_routed_elsewhere_skips_and_names_the_intent_it_got(self):
        tally = RoutingTally()
        with pytest.raises(SkipTest, match=r"got \['my-skill.author:alarm'\]"):
            tally.assert_routed("set a timer", f"{SKILL}:timer",
                                ["recognizer_loop:utterance", f"{SKILL}:alarm", "speak"])
        assert tally.hits == []
        assert tally.misses == [("'set a timer': expected ['my-skill.author:timer'], "
                                 "got ['my-skill.author:alarm']")]

    def test_a_request_routed_to_another_skill_names_that_skill(self):
        tally = RoutingTally()
        with pytest.raises(SkipTest, match=r"got \['other-skill.author:weather'\]"):
            tally.assert_routed("set a timer", f"{SKILL}:timer",
                                ["recognizer_loop:utterance", "other-skill.author:weather"])

    def test_an_unmatched_request_is_a_miss(self):
        tally = RoutingTally()
        with pytest.raises(SkipTest, match=r"got \['ovos.intent.unmatched'\]"):
            tally.assert_routed("hello", f"{SKILL}:timer", ["ovos.intent.unmatched"])

    @pytest.mark.parametrize("expected, fired", [
        (f"{SKILL}:timer.intent", f"{SKILL}:timer"),
        (f"{SKILL}:timer", f"{SKILL}:timer.intent"),
    ])
    def test_the_intent_suffix_of_older_workshop_topics_is_ignored(self, expected, fired):
        tally = RoutingTally()
        _hit(tally, "assert_routed", "set a timer", expected, [fired])
        assert tally.hits == ["set a timer"]

    def test_any_of_several_expected_intents_is_a_hit(self):
        tally = RoutingTally()
        _hit(tally, "assert_routed", "wake me at 7",
             {f"{SKILL}:alarm", f"{SKILL}:media"}, [f"{SKILL}:media"])
        assert tally.hits == ["wake me at 7"]

    def test_a_single_fired_topic_string_is_one_topic(self):
        tally = RoutingTally()
        _hit(tally, "assert_routed", "set a timer", f"{SKILL}:timer", f"{SKILL}:timer")
        with pytest.raises(SkipTest):
            tally.assert_not_routed("set a timer", f"{SKILL}:timer", f"{SKILL}:timer")

    def test_a_forbidden_intent_given_as_a_string_is_checked(self):
        tally = RoutingTally()
        with pytest.raises(SkipTest, match=r"\['my-skill.author:timer'\] claimed it"):
            tally.assert_not_routed("timer status", f"{SKILL}:timer.intent",
                                    [f"{SKILL}:timer"])
        assert len(tally.misses) == 1

    def test_a_clean_negative_check_is_not_counted(self):
        tally = RoutingTally()
        _hit(tally, "assert_not_routed", "what time is it", [f"{SKILL}:timer"], ["time:now"])
        assert (tally.total, tally.rate) == (0, None)

    def test_negative_checks_cannot_carry_a_boot_that_routes_nothing(self):
        tally = RoutingTally()
        for n in range(8):
            tally.assert_not_routed(f"off topic {n}", [f"{SKILL}:timer"], ["ovos.intent.unmatched"])
        for n in range(2):
            with pytest.raises(SkipTest):
                tally.assert_routed(f"timer {n}", f"{SKILL}:timer", ["ovos.intent.unmatched"])
        assert tally.rate == 0.0
        assert tally.failure(0.8) is not None

    @pytest.mark.parametrize("hits, misses, min_rate, fails", [
        (4, 1, 0.8, False),
        (3, 1, 0.8, True),
        (0, 0, 0.8, False),
    ])
    def test_the_gate_compares_the_rate_with_the_minimum(self, hits, misses, min_rate, fails):
        tally = RoutingTally()
        tally.hits = ["hit"] * hits
        tally.misses = ["miss"] * misses
        assert (tally.failure(min_rate) is not None) is fails


SUITE = """
from ovoscope.routing import TALLY

SKILL = "my-skill.author"


def test_hits():
    for n in range({hits}):
        TALLY.assert_routed(f"hit {{n}}", SKILL + ":a", [SKILL + ":a"])


def test_misses():
    for n in range({misses}):
        try:
            TALLY.assert_routed(f"miss {{n}}", SKILL + ":a", [SKILL + ":b"])
        except Exception:
            pass
"""

ONE_MISS_PER_TEST = """
import pytest
from ovoscope.routing import TALLY


@pytest.mark.parametrize("n", range(6))
def test_miss(n):
    TALLY.assert_routed(f"miss {n}", "my-skill.author:a", ["my-skill.author:b"])
"""


class TestSessionGate:
    """Each run is a subprocess: ``TALLY`` is process-wide, and an in-process
    run would count its checks into this session too."""

    def test_a_rate_below_the_default_fails_the_session(self, pytester):
        pytester.makepyfile(test_suite=SUITE.format(hits=3, misses=1))
        result = pytester.runpytest_subprocess()
        result.assert_outcomes(passed=2)
        assert result.ret == 1
        result.stdout.fnmatch_lines(["*3/4 = 75.0%*gate 80%*",
                                     "*routing gate FAILED*"])

    def test_a_rate_at_the_default_passes(self, pytester):
        pytester.makepyfile(test_suite=SUITE.format(hits=4, misses=1))
        result = pytester.runpytest_subprocess()
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*4/5 = 80.0%*gate 80%*"])

    def test_the_ini_value_sets_the_minimum(self, pytester):
        pytester.makeini("[pytest]\novoscope_min_routing_rate = 0.7\n")
        pytester.makepyfile(test_suite=SUITE.format(hits=3, misses=1))
        result = pytester.runpytest_subprocess()
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*3/4 = 75.0%*gate 70%*"])

    @pytest.mark.parametrize("value", ["70%", "70", "0.7 # comment", "-0.1"])
    def test_a_bad_ini_value_stops_the_run_with_a_usage_error(self, pytester, value):
        pytester.makeini(f"[pytest]\novoscope_min_routing_rate = {value}\n")
        pytester.makepyfile(test_plain="def test_ok():\n    assert True\n")
        result = pytester.runpytest_subprocess()
        assert result.ret == pytest.ExitCode.USAGE_ERROR
        result.stderr.fnmatch_lines(["*ovoscope_min_routing_rate must be a number from 0 to 1*"])

    def test_a_session_that_routes_nothing_is_not_gated(self, pytester):
        pytester.makepyfile(test_plain="def test_ok():\n    assert True\n")
        result = pytester.runpytest_subprocess()
        assert result.ret == 0
        assert "routing rate" not in result.stdout.str()

    def test_a_failing_test_keeps_its_own_exit_status(self, pytester):
        pytester.makepyfile(test_suite=SUITE.format(hits=4, misses=0),
                            test_bad="def test_bad():\n    assert False\n")
        result = pytester.runpytest_subprocess()
        assert result.ret == 1
        result.assert_outcomes(passed=2, failed=1)

    def test_xdist_workers_hand_their_checks_to_the_controller(self, pytester):
        pytester.makepyfile(test_suite=ONE_MISS_PER_TEST)
        result = pytester.runpytest_subprocess("-n", "2", "-p", "xdist")
        result.assert_outcomes(skipped=6)
        assert result.ret == 1
        result.stdout.fnmatch_lines(["*0/6 = 0.0%*gate 80%*", "*routing gate FAILED*"])
