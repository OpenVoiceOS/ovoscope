Last Edit: Claude Sonnet 4.6 - 2026-03-08 - Motive: Added usage-guide, ci-integration, Who Uses, and Cross-References sections.

# OvoScope Documentation

**OvoScope** is an end-to-end testing framework for OVOS skills. It runs a lightweight in-process OVOS Core using a `FakeBus`, loads real skill plugins, and captures every bus message produced in response to a test utterance — then asserts against the captured sequence.

## Contents

| Document | Description |
|---|---|
| [usage-guide.md](usage-guide.md) | **Start here** — tutorial: from zero to your first end2end test |
| [ci-integration.md](ci-integration.md) | Wiring ovoscope into GitHub Actions CI with gh-automations |
| [minicroft.md](minicroft.md) | `MiniCroft` — in-process skill runtime |
| [capture-session.md](capture-session.md) | `CaptureSession` — message capture during a test |
| [end2end-test.md](end2end-test.md) | `End2EndTest` — full test runner reference |
| [pydantic-integration.md](pydantic-integration.md) | Using `ovos-pydantic-models` with OvoScope |

## Conceptual Model

```
Test                         FakeBus
────                         ───────
source_message ──emit──►  [MiniCroft + loaded skills]
                                  │
                    ◄──capture────┤ all emitted messages
                                  │ until EOF message
                                  ▼
            assert against expected_messages[]
```

The key insight is that OVOS skill behaviour is fully observable through bus messages. OvoScope intercepts every message on the in-process `FakeBus`, so the entire skill interaction — intent matching, converse, fallback, speak, session changes — is captured and verifiable.

## Quick Start

```bash
pip install ovoscope
```

```python
from ovoscope import End2EndTest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

session = Session("test-123")
utterance = Message(
    "recognizer_loop:utterance",
    {"utterances": ["hello world"], "lang": "en-us"},
    {"session": session.serialize(), "source": "A", "destination": "B"},
)

test = End2EndTest(
    skill_ids=["skill-hello-world.openvoiceos"],
    source_message=utterance,
    expected_messages=[
        utterance,
        Message("speak", {"utterance": "Hello!"}),
        Message("ovos.utterance.handled", {}),
    ],
)
test.execute()
```

## Recording Mode

Instead of writing expected messages by hand, record them from a live run:

```python
test = End2EndTest.from_message(
    message=utterance,
    skill_ids=["skill-hello-world.openvoiceos"],
)
test.save("tests/hello_world.json")
```

Then replay later:

```python
test = End2EndTest.from_path("tests/hello_world.json")
test.execute()
```

## Public API

All primary classes and the factory function are importable from `ovoscope` directly:

```python
from ovoscope import (
    MiniCroft,         # in-process skill runtime
    get_minicroft,     # factory: create + wait for READY
    CaptureSession,    # message recorder for a single interaction
    End2EndTest,       # declarative test runner
)
```

Type aliases also exported:

```python
from ovoscope import SerializedMessage, SerializedTest
```

## Dependencies

| Package | Role |
|---|---|
| `ovos-core >= 2.0.4a2` | `SkillManager`, `IntentService`, `FakeBus`, `SessionManager` |

Python 3.10+ is required (uses `match`/structural typing in ovos-core).

## What OvoScope Does NOT Do

- Does not start a real WebSocket MessageBus server — uses `FakeBus` (in-process pub/sub).
- Does not load PHAL plugins or the audio service — only skills and the intent pipeline.
- Does not test GUI rendering — GUI namespace messages are ignored by default (`ignore_gui=True`).
- Does not test STT or TTS — operates at the `recognizer_loop:utterance` level.

## Quick Links

| Resource | Path |
|---|---|
| Machine-readable facts | [`../QUICK_FACTS.md`](../QUICK_FACTS.md) |
| Common questions | [`../FAQ.md`](../FAQ.md) |
| Change log | [`../CHANGELOG.md`](../CHANGELOG.md) |
| Known issues | [`../AUDIT.md`](../AUDIT.md) |
| Improvement proposals | [`../SUGGESTIONS.md`](../SUGGESTIONS.md) |

## Who Uses ovoscope

| Repo | Test location | Notes |
|---|---|---|
| `ovos-core` | `ovos-core/test/end2end/` | Adapt + Padatious pipeline tests, blacklist tests |
| `Skills/ovos-skill-hello-world` | `Skills/ovos-skill-hello-world/test/test_helloworld.py` | Canonical example — Adapt + Padatious match + no-match |

## Cross-References

- [ovos-core](https://github.com/OpenVoiceOS/ovos-core) — `SkillManager`, `IntentService` (runtime dependency)
- [ovos-utils](https://github.com/OpenVoiceOS/ovos-utils) — `FakeBus`, `ProcessState`
- [ovos-workshop](https://github.com/OpenVoiceOS/ovos-workshop) — `OVOSSkill` base class
- [ovos-bus-client](https://github.com/OpenVoiceOS/ovos-bus-client) — `Message`, `Session`, `SessionManager`
- [ovos-pydantic-models](https://github.com/OpenVoiceOS/ovos-pydantic-models) — optional typed message models (see [pydantic-integration.md](pydantic-integration.md))
- [gh-automations](https://github.com/TigreGotico/gh-automations) — CI reusable workflows (see [ci-integration.md](ci-integration.md))
