"""ovoscope pytest plugin — provides the ``minicroft`` fixture and bus-coverage hooks.

Registered automatically via the ``pytest11`` entry point in ``pyproject.toml``.
Import directly in a ``conftest.py`` if you need to customise the fixture scope::

    # conftest.py
    from ovoscope.pytest_plugin import minicroft  # noqa: F401

Usage in tests::

    class TestMySkill:
        skill_ids = ["my-skill.author"]

        def test_something(self, minicroft):
            from ovoscope import End2EndTest
            from ovos_bus_client.message import Message
            from ovos_bus_client.session import Session

            session = Session("test-1")
            message = Message(
                "recognizer_loop:utterance",
                {"utterances": ["hello"], "lang": "en-US"},
                {"session": session.serialize(), "source": "A", "destination": "B"},
            )
            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=self.skill_ids,
                source_message=message,
                expected_messages=[...],
            )
            test.execute(timeout=10)

Bus coverage opt-in::

    class TestMySkill:
        skill_ids = ["my-skill.author"]

        def test_something(self, minicroft, bus_coverage_session):
            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=self.skill_ids,
                source_message=message,
                expected_messages=[...],
                track_bus_coverage=True,
            )
            test.execute()
            bus_coverage_session.add(test.bus_coverage_report)
"""

from typing import TYPE_CHECKING, Iterator, List, Optional, Union

if TYPE_CHECKING:
    from ovoscope.bus_coverage import BusCoverageReport

import pytest

from ovoscope import MiniCroft, get_minicroft, End2EndTest

# Global collector for autouse fixture and monkey-patched End2EndTest
_SESSION_COLLECTOR: Optional["BusCoverageCollector"] = None


def pytest_addoption(parser):
    """Add CLI options for ovoscope bus coverage."""
    group = parser.getgroup("ovoscope")
    group.addoption(
        "--ovoscope-bus-cov",
        action="store_true",
        default=False,
        help="Enable bus-level coverage tracking for all End2EndTests.",
    )
    group.addoption(
        "--ovoscope-bus-cov-file",
        action="store",
        default=None,
        metavar="PATH",
        help="Save the merged bus coverage report to a JSON file.",
    )
    group.addoption(
        "--ovoscope-bus-cov-verbose",
        action="store_true",
        default=False,
        help="Show detailed list of covered/uncovered message types in the terminal.",
    )
    group.addoption(
        "--ovoscope-bus-cov-include",
        action="store",
        default=None,
        metavar="PATTERN",
        help="Only include skills/components matching this regex in the coverage report.",
    )
    group.addoption(
        "--ovoscope-bus-cov-exclude",
        action="store",
        default=None,
        metavar="PATTERN",
        help="Exclude skills/components matching this regex from the coverage report.",
    )
    group.addoption(
        "--ovoscope-accuracy-report",
        action="store",
        default=None,
        metavar="PATH",
        help="Write per-(pipeline, lang, intent) accuracy report as JSON.",
    )
    group.addoption(
        "--ovoscope-accuracy-min",
        action="store",
        type=float,
        default=None,
        metavar="RATIO",
        help=("Minimum overall intent-case pass rate (0.0-1.0). If set and "
              "the rate falls below, the session exits non-zero — useful "
              "as a CI gate on regression in intent routing accuracy."),
    )
    group.addoption(
        "--ovoscope-accuracy-baseline",
        action="store",
        default=None,
        metavar="PATH",
        help=("Path to a previous --ovoscope-accuracy-report JSON. The "
              "session fails if overall accuracy is lower than the "
              "baseline (helpful for blocking PRs that lower accuracy)."),
    )
    group.addoption(
        "--ovoscope-accuracy-tolerant",
        action="store_true",
        default=False,
        help=("Downgrade individual intent-case failures to xfail so they "
              "don't fail the build; only the aggregate accuracy gate "
              "(--ovoscope-accuracy-min / --ovoscope-accuracy-baseline) "
              "can block the session."),
    )


@pytest.fixture(scope="class")
def minicroft(request) -> Iterator[MiniCroft]:
    """Class-scoped pytest fixture that provides a ready ``MiniCroft`` instance.

    Reads ``skill_ids`` from the test class attribute ``skill_ids: List[str]``.
    The MiniCroft is started once for the entire test class and stopped in teardown.

    Example::

        class TestMySkill:
            skill_ids = ["my-skill.author"]

            def test_intent(self, minicroft):
                ...  # minicroft is already started and READY
    """
    skill_ids: Union[List[str], str] = getattr(request.cls, "skill_ids", [])
    if isinstance(skill_ids, str):
        skill_ids = [skill_ids]
    mc: MiniCroft = None
    mc = get_minicroft(skill_ids)
    try:
        yield mc
    finally:
        if mc is not None:
            mc.stop()


class BusCoverageCollector:
    """Accumulates :class:`~ovoscope.bus_coverage.BusCoverageReport` objects
    across a pytest session and merges them for the terminal summary.

    Usage::

        # In a test
        def test_something(self, minicroft, bus_coverage_session):
            test = End2EndTest(..., track_bus_coverage=True)
            test.execute()
            bus_coverage_session.add(test.bus_coverage_report)
    """

    def __init__(self) -> None:
        self._reports: List["BusCoverageReport"] = []

    def add(self, report: Optional["BusCoverageReport"]) -> None:
        """Add a :class:`~ovoscope.bus_coverage.BusCoverageReport` to the collector.

        Silently ignores ``None`` so callers do not need to guard against tests
        where ``track_bus_coverage=False``.

        Args:
            report: A :class:`~ovoscope.bus_coverage.BusCoverageReport` or ``None``.
        """
        if report is not None:
            self._reports.append(report)

    def merged_report(self) -> Optional[object]:
        """Return a merged :class:`~ovoscope.bus_coverage.BusCoverageReport`.

        Merges all accumulated reports by summing per-skill listener invocations,
        observed counts, and asserted counts.

        Returns:
            A merged report, or ``None`` if no reports have been added.
        """
        if not self._reports:
            return None
        try:
            from ovoscope.bus_coverage import (
                BusCoverageReport,
                SkillBusCoverage,
                HandlerEntry,
                EmitterEntry,
            )
        except ImportError:
            return None

        # Merge by skill_id
        listener_data: dict = {}  # skill_id -> {msg_type -> (handler_count, invocation_count)}
        observed_data: dict = {}  # skill_id -> {msg_type -> count}
        asserted_data: dict = {}  # skill_id -> {msg_type -> count}

        for report in self._reports:
            for skill in report.skills:
                sid = skill.skill_id
                if sid not in listener_data:
                    listener_data[sid] = {}
                for h in skill.listeners:
                    existing = listener_data[sid].get(h.msg_type, (h.handler_count, 0))
                    listener_data[sid][h.msg_type] = (
                        existing[0],
                        existing[1] + h.invocation_count,
                    )
                if sid not in observed_data:
                    observed_data[sid] = {}
                for e in skill.emitters:
                    observed_data[sid][e.msg_type] = (
                        observed_data[sid].get(e.msg_type, 0) + e.observed_count
                    )
                if sid not in asserted_data:
                    asserted_data[sid] = {}
                for e in skill.emitters:
                    asserted_data[sid][e.msg_type] = (
                        asserted_data[sid].get(e.msg_type, 0) + e.asserted_count
                    )

        skills = []
        for skill_id in sorted(set(listener_data) | set(observed_data)):
            listeners = [
                HandlerEntry(
                    msg_type=mt,
                    handler_count=hc,
                    invocation_count=ic,
                    covered=ic > 0,
                )
                for mt, (hc, ic) in sorted(listener_data.get(skill_id, {}).items())
            ]
            all_emitted = set(observed_data.get(skill_id, {}).keys()) | set(
                asserted_data.get(skill_id, {}).keys()
            )
            emitters = [
                EmitterEntry(
                    msg_type=mt,
                    observed_count=observed_data.get(skill_id, {}).get(mt, 0),
                    asserted_count=asserted_data.get(skill_id, {}).get(mt, 0),
                    observed=observed_data.get(skill_id, {}).get(mt, 0) > 0,
                    asserted=asserted_data.get(skill_id, {}).get(mt, 0) > 0,
                )
                for mt in sorted(all_emitted)
            ]
            skills.append(SkillBusCoverage(skill_id=skill_id, listeners=listeners, emitters=emitters))

        return BusCoverageReport(skills=skills)


@pytest.fixture(scope="session", autouse=True)
def bus_coverage_session(request) -> Iterator[BusCoverageCollector]:
    """Session-scoped fixture that collects bus coverage reports from all tests.

    Automatically enabled if ``--ovoscope-bus-cov`` is passed to pytest.
    When enabled, it monkey-patches ``End2EndTest`` to
    automatically add reports to the session collector after ``execute()``.

    Tests can also opt in manually without the CLI flag by requesting this
    fixture and calling ``bus_coverage_session.add(test.bus_coverage_report)``.
    """
    import ovoscope
    global _SESSION_COLLECTOR
    enabled = request.config.getoption("--ovoscope-bus-cov")
    cov_file = request.config.getoption("--ovoscope-bus-cov-file")

    collector = BusCoverageCollector()
    _SESSION_COLLECTOR = collector

    original_execute = End2EndTest.execute

    if enabled:
        ovoscope.GLOBAL_BUS_COVERAGE = True
        ovoscope.GLOBAL_BUS_COVERAGE_FILE = cov_file
        # Initialize the global collector to catch boot-time events
        ovoscope.GLOBAL_BUS_COVERAGE_COLLECTOR = ovoscope.GlobalBusCoverageCollector()

        # Auto-collect report after execution
        def patched_execute(self, *args, **kwargs):
            res = original_execute(self, *args, **kwargs)
            if self.bus_coverage_report:
                collector.add(self.bus_coverage_report)
            return res

        End2EndTest.execute = patched_execute

    try:
        yield collector
    finally:
        _SESSION_COLLECTOR = None
        if enabled:
            ovoscope.GLOBAL_BUS_COVERAGE = False
            ovoscope.GLOBAL_BUS_COVERAGE_COLLECTOR = None
            # Restore original behavior
            End2EndTest.execute = original_execute
            # Note: we don't restore track_bus_coverage default because it's a
            # class attribute and we might have stepped on a manual True/False
            # in some tests, but in pytest context it usually doesn't matter
            # after the session ends.

    # Store the merged report on the config object so the terminal hook can
    # retrieve it without touching private pytest internals.
    report = collector.merged_report()
    if report is not None:
        # Apply filters
        include = request.config.getoption("--ovoscope-bus-cov-include")
        exclude = request.config.getoption("--ovoscope-bus-cov-exclude")
        report = report.filter(include=include, exclude=exclude)

        if not hasattr(request.config, "_bus_coverage_reports"):
            request.config._bus_coverage_reports = []
        request.config._bus_coverage_reports.append(report)

        # Save to file if requested
        cov_file = request.config.getoption("--ovoscope-bus-cov-file")
        if cov_file:
            import os
            try:
                os.makedirs(os.path.dirname(os.path.abspath(cov_file)), exist_ok=True)
                with open(cov_file, "w", encoding="utf-8") as f:
                    f.write(report.to_json())
            except Exception as exc:
                print(f"\nERROR: Failed to save bus coverage report to {cov_file}: {exc}")


def _bus_coverage_summary(terminalreporter, config):
    """Print the merged bus coverage report (factored out so the combined
    ``pytest_terminal_summary`` below can call both reporters)."""
    reports = getattr(config, "_bus_coverage_reports", None)
    if not reports:
        return
    verbose = config.getoption("--ovoscope-bus-cov-verbose")
    for report in reports:
        terminalreporter.write_sep("=", "Bus Coverage Report")
        report.print_report(verbose=verbose)
        terminalreporter.write_line("")


# ---------------------------------------------------------------------------
# Intent-case accuracy reporter
#
# Aggregates pass/fail per (pipeline, lang, intent) for tests generated by
# :func:`ovoscope.intent_cases.register_intent_case_tests`. Each generated
# method carries an ``_intent_case`` attribute; we read it during the
# ``pytest_runtest_logreport`` hook, accumulate, then emit a report and an
# optional pass/fail gate during ``pytest_terminal_summary``.
# ---------------------------------------------------------------------------
def _resolve_intent_case_meta(item):
    """Return (IntentCase, pipeline_name, skill_id) or None if not generated."""
    func = getattr(item, "function", None)
    if func is None:
        return None
    case = getattr(func, "_intent_case", None)
    if case is None:
        return None
    return (case,
            getattr(func, "_intent_case_pipeline", "Unknown"),
            getattr(func, "_intent_case_skill_id", ""))


def pytest_collection_modifyitems(config, items):
    """In tolerant mode, mark every intent-case test as ``xfail(strict=False)``.

    That lets the suite measure per-case routing accuracy without forcing
    every CI run to be green only when 100% of cases match. The aggregate
    gate (``--ovoscope-accuracy-min`` / ``--ovoscope-accuracy-baseline``)
    is the real blocker.
    """
    if not config.getoption("--ovoscope-accuracy-tolerant"):
        return
    for item in items:
        if _resolve_intent_case_meta(item) is not None:
            item.add_marker(pytest.mark.xfail(reason="intent-case (tolerant)",
                                              strict=False, run=True))


def pytest_runtest_logreport(report):
    """Record intent-case outcomes on the session config."""
    if report.when != "call":
        return
    item_func = getattr(report, "_intent_case_func", None)
    # We can't get the item directly from a logreport; fall back to nodeid.
    # The accumulator is keyed by nodeid -> (case, pipeline) which we set in
    # ``pytest_runtest_setup``.
    accum = getattr(pytest_runtest_logreport, "_accum", None)
    if accum is None:
        return
    meta = accum["meta"].get(report.nodeid)
    if meta is None:
        return
    case, pipeline, skill_id = meta
    passed = report.outcome == "passed" or (
        report.outcome == "skipped"
        and isinstance(report.longrepr, tuple)
        and "XPASS" in str(report.longrepr))
    # xfail/xpass handling: in tolerant mode a "failure" surfaces as xfail.
    if report.outcome == "skipped" and hasattr(report, "wasxfail"):
        passed = False
    accum["results"].append({
        "nodeid": report.nodeid,
        "skill_id": skill_id,
        "pipeline": pipeline,
        "lang": case.lang,
        "intent": case.intent or "no_match",
        "utterance": case.utterance,
        "source": str(case.source),
        "passed": passed,
    })


def pytest_runtest_setup(item):
    """Index intent-case metadata by nodeid for the logreport hook."""
    meta = _resolve_intent_case_meta(item)
    if meta is None:
        return
    accum = getattr(pytest_runtest_logreport, "_accum", None)
    if accum is None:
        accum = {"results": [], "meta": {}}
        pytest_runtest_logreport._accum = accum
    accum["meta"][item.nodeid] = meta


def _accuracy_summary(results):
    """Aggregate results into pivot tables for reporting."""
    by_pipeline: Dict[str, Dict[str, int]] = {}
    by_pipeline_lang: Dict[tuple, Dict[str, int]] = {}
    by_pipeline_intent: Dict[tuple, Dict[str, int]] = {}
    total_pass = total = 0
    for r in results:
        total += 1
        if r["passed"]:
            total_pass += 1
        for bucket, key in (
                (by_pipeline, r["pipeline"]),
                (by_pipeline_lang, (r["pipeline"], r["lang"])),
                (by_pipeline_intent, (r["pipeline"], r["intent"])),
        ):
            d = bucket.setdefault(key, {"pass": 0, "total": 0})
            d["total"] += 1
            if r["passed"]:
                d["pass"] += 1
    overall = (total_pass / total) if total else 0.0
    return {
        "overall_accuracy": overall,
        "passed": total_pass,
        "total": total,
        "by_pipeline": by_pipeline,
        "by_pipeline_lang": {f"{p}|{l}": v for (p, l), v in by_pipeline_lang.items()},
        "by_pipeline_intent": {f"{p}|{i}": v for (p, i), v in by_pipeline_intent.items()},
    }


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    """Combined session summary: bus coverage + intent-case accuracy."""
    _bus_coverage_summary(terminalreporter, config)
    accum = getattr(pytest_runtest_logreport, "_accum", None)
    if not accum or not accum["results"]:
        return
    summary = _accuracy_summary(accum["results"])

    tr = terminalreporter
    tr.write_sep("=", "ovoscope Intent-Case Accuracy")
    tr.write_line(
        f"Overall: {summary['passed']}/{summary['total']} "
        f"= {summary['overall_accuracy']:.1%}")
    tr.write_line("")
    tr.write_line("By pipeline:")
    for pipe, d in sorted(summary["by_pipeline"].items()):
        ratio = d["pass"] / d["total"] if d["total"] else 0.0
        tr.write_line(f"  {pipe:24s}  {d['pass']:4d}/{d['total']:<4d}  {ratio:>6.1%}")
    tr.write_line("")
    tr.write_line("By pipeline x lang:")
    for key in sorted(summary["by_pipeline_lang"]):
        d = summary["by_pipeline_lang"][key]
        ratio = d["pass"] / d["total"] if d["total"] else 0.0
        tr.write_line(f"  {key:36s}  {d['pass']:4d}/{d['total']:<4d}  {ratio:>6.1%}")
    tr.write_line("")
    tr.write_line("By pipeline x intent:")
    for key in sorted(summary["by_pipeline_intent"]):
        d = summary["by_pipeline_intent"][key]
        ratio = d["pass"] / d["total"] if d["total"] else 0.0
        tr.write_line(f"  {key:48s}  {d['pass']:4d}/{d['total']:<4d}  {ratio:>6.1%}")

    # Persist to JSON if requested.
    report_path = config.getoption("--ovoscope-accuracy-report")
    if report_path:
        import json
        import os
        os.makedirs(os.path.dirname(os.path.abspath(report_path)) or ".",
                    exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "results": accum["results"]},
                      fh, indent=2)
        tr.write_line(f"\nWrote accuracy report -> {report_path}")

    # Gate the session on minimum / baseline accuracy.
    min_acc = config.getoption("--ovoscope-accuracy-min")
    baseline_path = config.getoption("--ovoscope-accuracy-baseline")
    failures = []
    if min_acc is not None and summary["overall_accuracy"] < min_acc:
        failures.append(
            f"overall accuracy {summary['overall_accuracy']:.1%} < "
            f"required {min_acc:.1%}")
    if baseline_path:
        try:
            import json as _json
            with open(baseline_path, "r", encoding="utf-8") as fh:
                base = _json.load(fh)["summary"]["overall_accuracy"]
            if summary["overall_accuracy"] < base:
                failures.append(
                    f"overall accuracy {summary['overall_accuracy']:.1%} < "
                    f"baseline {base:.1%} ({baseline_path})")
        except Exception as exc:
            tr.write_line(f"\nWARNING: could not read baseline "
                          f"{baseline_path}: {exc}")
    if failures:
        tr.write_sep("!", "ovoscope accuracy gate FAILED")
        for f in failures:
            tr.write_line(f"  - {f}")
        # Mark the session as failed.
        config._ovoscope_accuracy_gate_failed = True


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Propagate accuracy-gate failure as a non-zero exit status."""
    if getattr(session.config, "_ovoscope_accuracy_gate_failed", False):
        if session.exitstatus == 0:
            session.exitstatus = 1
