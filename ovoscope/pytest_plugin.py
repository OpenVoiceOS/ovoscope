"""ovoscope pytest plugin — provides the ``minicroft`` fixture.

Registered automatically via the ``pytest11`` entry point in ``setup.py`` /
``pyproject.toml``.  Import directly in a ``conftest.py`` if you need to
customise the fixture scope:

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
"""

from typing import Iterator, List, Union

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
    mc = get_minicroft(skill_ids)
    yield mc
    mc.stop()
