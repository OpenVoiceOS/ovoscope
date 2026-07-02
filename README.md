[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/TigreGotico/ovoscope)
[![PyPI](https://img.shields.io/pypi/v/ovoscope)](https://pypi.org/project/ovoscope/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/ovoscope/)
# OvoScope
**End-to-end testing for [OVOS](https://openvoiceos.org) skills.**
OvoScope runs a full OVOS Core pipeline in-process using a `FakeBus` — no server, no audio
stack, no network. Load real skill plugins, emit a test utterance, and assert on every bus
message that comes back: type, data, routing context, session state, and message ordering.
![image](https://github.com/user-attachments/assets/10a10ff5-64b7-42fd-86bd-cb6a5db769dd)
> Like a microscope for your OVOS skills.
---
## Features
| | |
|---|---|
| **Full pipeline** | Runs real intent pipeline plugins (Adapt, Padatious, Fallback, Converse, Common Query) |
| **Isolated** | Config isolation strips user preferences; deterministic `DEFAULT_TEST_PIPELINE` excludes AI/persona/OCP stages |
| **Ordered assertions** | Assert message type, data keys, routing context, and session state in sequence |
| **Recording mode** | Capture a live message sequence and save it as a JSON fixture — no manual construction needed |
| **Multi-turn** | Pass a list of utterances to test full conversational flows |
| **pytest fixture** | `minicroft` class-scoped fixture auto-discovered via the `pytest11` entry point |
| **Inject skills** | `extra_skills={id: SkillClass}` to load inline test skills without a PyPI entry point |
| **Inject messages** | `MiniCroft.inject_message()` to trigger non-utterance handlers (GUI events, timers, API calls) |
| **Typed models** | Optional `ovoscope[pydantic]` bridge to `ovos-pydantic-models` for schema-validated messages |
---
## Installation
```bash
pip install ovoscope
```
With optional typed message model support:
```bash
pip install ovoscope[pydantic]
```
---
## Quick Start
```python
import unittest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovoscope import End2EndTest
SKILL_ID = "ovos-skill-hello-world.openvoiceos"
session = Session("test-session")
utterance = Message(
    "recognizer_loop:utterance",
    {"utterances": ["hello world"], "lang": "en-US"},
    {"session": session.serialize(), "source": "A", "destination": "B"},
)
class TestHelloWorld(unittest.TestCase):
    def test_intent_match(self):
        End2EndTest(
            skill_ids=[SKILL_ID],
            source_message=utterance,
            expected_messages=[
                utterance,
                Message(f"{SKILL_ID}.activate", context={"skill_id": SKILL_ID}),
                Message(f"{SKILL_ID}:HelloWorldIntent",
                        data={"utterance": "hello world"}, context={"skill_id": SKILL_ID}),
                Message("mycroft.skill.handler.start", context={"skill_id": SKILL_ID}),
                Message("speak", data={"lang": "en-US"}, context={"skill_id": SKILL_ID}),
                Message("mycroft.skill.handler.complete", context={"skill_id": SKILL_ID}),
                Message("ovos.utterance.handled", context={"skill_id": SKILL_ID}),
            ],
        ).execute(timeout=10)
```
Only keys you specify in `expected.data` and `expected.context` are checked — extra keys in the
received message are ignored.
---
## Recording Mode
Don't know the exact message sequence yet? Record it from a live run:
```python
from ovoscope import End2EndTest
test = End2EndTest.from_message(
    message=utterance,
    skill_ids=[SKILL_ID],
    timeout=20,
)
test.save("tests/fixtures/hello_world.json")  # anonymises location data by default
```
Replay in CI:
```python
End2EndTest.from_path("tests/fixtures/hello_world.json").execute(timeout=10)
```
---
## pytest Fixture
The `minicroft` class-scoped fixture is auto-registered when ovoscope is installed.
No `setUp`/`tearDown` boilerplate needed:
```python
class TestMySkill:
    skill_ids = ["my-skill.author"]
    def test_something(self, minicroft):
        End2EndTest(
            minicroft=minicroft,
            skill_ids=self.skill_ids,
            source_message=utterance,
            expected_messages=[...],
        ).execute(timeout=10)
```
---
## Pipeline Control
OvoScope exposes composable pipeline stage lists so tests are deterministic regardless of which
AI plugins are installed on the host:
```python
from ovoscope import ADAPT_PIPELINE, PADATIOUS_PIPELINE, FALLBACK_PIPELINE, PERSONA_PIPELINE
# Adapt only — fastest
mc = get_minicroft([SKILL_ID], default_pipeline=ADAPT_PIPELINE)
# Full intent chain
mc = get_minicroft([SKILL_ID],
                   default_pipeline=ADAPT_PIPELINE + PADATIOUS_PIPELINE + FALLBACK_PIPELINE)
# Opt in to persona for AI testing
mc = get_minicroft([SKILL_ID], default_pipeline=DEFAULT_TEST_PIPELINE + PERSONA_PIPELINE)
```
`DEFAULT_TEST_PIPELINE` (the default when `isolate_config=True`) includes all standard built-in
stages and deliberately excludes persona, Ollama, OCP, and m2v plugins.
---
## Documentation
| Document | |
|---|---|
| [docs/usage-guide.md](docs/usage-guide.md) | **Start here** — 8 test patterns with full worked examples |
| [docs/ci-integration.md](docs/ci-integration.md) | Wiring ovoscope into GitHub Actions |
| [docs/minicroft.md](docs/minicroft.md) | `MiniCroft` and `get_minicroft()` reference |
| [docs/capture-session.md](docs/capture-session.md) | `CaptureSession` internals |
| [docs/end2end-test.md](docs/end2end-test.md) | `End2EndTest` full parameter reference |
| [docs/pydantic-integration.md](docs/pydantic-integration.md) | Typed message models with `ovos-pydantic-models` |
| [FAQ.md](FAQ.md) | Common questions and gotchas |
---

---

## Credits

Developed by [TigreGótico](https://tigregotico.pt) for
[OpenVoiceOS](https://openvoiceos.org).

[![NGI0 Commons Fund](./ngi.png)](https://nlnet.nl/project/OpenVoiceOS)

This project was funded through the [NGI0 Commons Fund](https://nlnet.nl/commonsfund),
a fund established by [NLnet](https://nlnet.nl) with financial support from the
European Commission's [Next Generation Internet](https://ngi.eu) programme, under
the aegis of [DG Communications Networks, Content and Technology](https://commission.europa.eu/about-european-commission/departments-and-executive-agencies/communications-networks-content-and-technology_en)
under grant agreement No [101135429](https://cordis.europa.eu/project/id/101135429).

---

## License

[Apache 2.0](LICENSE)

---

## Contributing

PRs are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## AI Disclosure

Parts of this project are developed with the assistance of AI tools.

  actions it took, and what human oversight was applied. This log is updated after every
  significant AI-assisted session.
These files are intentionally published so that contributors and users can understand how the
project evolves and where AI assistance has been applied.
