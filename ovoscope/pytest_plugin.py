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

from typing import Iterator, List, Optional, Union

import pytest

from ovoscope import MiniCroft, get_minicroft


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
        self._reports: List[object] = []

    def add(self, report: Optional[object]) -> None:
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


@pytest.fixture(scope="session")
def bus_coverage_session() -> Iterator[BusCoverageCollector]:
    """Session-scoped fixture that collects bus coverage reports from all tests.

    Tests opt in by requesting this fixture and calling
    ``bus_coverage_session.add(test.bus_coverage_report)`` after ``execute()``.
    A merged summary is printed in the pytest terminal output at session end.

    Example::

        def test_my_skill(self, minicroft, bus_coverage_session):
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
    collector = BusCoverageCollector()
    yield collector
    # The terminal summary hook below will print the report.
    # Store it on the collector for the hook to pick up.
    collector._finalized = True


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    """Print the merged bus coverage report at the end of the pytest session.

    Only runs if at least one test used the ``bus_coverage_session`` fixture
    and called ``bus_coverage_session.add(...)``.
    """
    # Retrieve the collector from the fixture manager, if it was used.
    try:
        fm = config.pluginmanager.get_plugin("ovoscope")
        if fm is None:
            return
    except Exception:
        pass

    # Walk all registered fixtures to find a BusCoverageCollector
    try:
        fixturemanager = config.pluginmanager.get_plugin("funcmanage")
        if fixturemanager is None:
            return
    except Exception:
        return

    # Find any session-scoped BusCoverageCollector instances that have data.
    # They are stored on the fixture manager's _arg2fixturedefs.
    try:
        defs = fixturemanager._arg2fixturedefs.get("bus_coverage_session", [])
    except Exception:
        return
    for fd in defs:
        try:
            # cached_result holds (value, when, exception)
            cached = fd.cached_result
            if cached is None:
                continue
            collector = cached[0]
            if not isinstance(collector, BusCoverageCollector):
                continue
            report = collector.merged_report()
            if report is None:
                continue
            terminalreporter.write_sep("=", "Bus Coverage Report")
            report.print_report()
            terminalreporter.write_line("")
        except Exception:
            continue
