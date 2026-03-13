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


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    """Print the merged bus coverage report at the end of the pytest session.

    Only runs if at least one test used the ``bus_coverage_session`` fixture
    (or ``--ovoscope-bus-cov`` was used) and reports were collected.
    """
    reports = getattr(config, "_bus_coverage_reports", None)
    if not reports:
        return
    verbose = config.getoption("--ovoscope-bus-cov-verbose")
    for report in reports:
        terminalreporter.write_sep("=", "Bus Coverage Report")
        report.print_report(verbose=verbose)
        terminalreporter.write_line("")
