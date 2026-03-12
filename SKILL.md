---
name: ovoscope
description: Generate test boilerplate, run ovoscope tests, record fixtures, and validate expectations for OpenVoiceOS skills. Use when testing OVOS skills or creating test templates.
trigger: Testing OVOS skills, creating end-to-end tests, scaffolding test files, recording test fixtures
---

# ovoscope — OVOS End-to-End Testing

**Use this skill when you are:**
- Creating or scaffolding end-to-end tests for an OVOS skill
- Debugging failing ovoscope tests
- Recording live test fixtures from running skills
- Validating test expectations against actual behavior
- Testing skill interaction patterns (Adapt, Padatious, multi-turn, fallback, etc.)
- Setting up CI/CD integration for skill E2E tests

## Installation

```bash
pip install ovoscope
```

Or in a project with `uv`:
```bash
uv add ovoscope
uv run pytest test/end2end/ -v --timeout=60
```

## Quick Reference

### Run E2E Tests
```bash
pytest test/end2end/ -v --timeout=60
```

### Scaffold a Test File (Python API)

```python
from ovoscope import End2EndTest, get_minicroft

# Start MiniCroft with your skill
minicroft = get_minicroft(["skill-id.author"])

# Define and run a test
test = End2EndTest(
    utterance="hello world",
    skill_id="skill-id.author",
    expected_messages=["speak"],
)
test.execute(minicroft)
```

### Record a Fixture (CLI)

```bash
ovoscope record <skill_id> "<utterance>" --output fixtures/hello.json
```

### Validate Expectations

```python
from ovoscope import CaptureSession

# Capture live interaction
with CaptureSession(minicroft) as session:
    minicroft.bus.emit("recognizer_loop:utterance", {"utterances": ["hello"]})

# Assert captured messages match expected pattern
assert any(msg["type"] == "speak" for msg in session.messages)
```

## Key Docs (in this repo)

- **`docs/index.md`** — Conceptual model, architecture, and public API overview
- **`docs/usage-guide.md`** — 8 test patterns (Adapt, Padatious, recording, replay, multi-turn, fallback, session state, etc.)
- **`docs/end2end-test.md`** — `End2EndTest` parameter reference and full API
- **`docs/minicroft.md`** — `MiniCroft` and `get_minicroft()` reference
- **`docs/cli.md`** — CLI tool reference (`ovoscope record`, etc.)
- **`docs/capture-session.md`** — `CaptureSession` API for recording and replaying messages
- **`docs/ci-integration.md`** — GitHub Actions setup and CI/CD patterns
- **`docs/listener.md`** — Testing listener/audio pipeline components
- **`docs/phal.md`** — Testing PHAL plugin interactions
- **`docs/gui-testing.md`** — Testing GUI interaction patterns
- **`docs/audio-testing.md`** — Audio playback and TTS testing
- **`docs/pipeline.md`** — Testing STT/TTS pipeline components
- **`docs/ocp.md`** — Open Consumer Protocol (OCP) testing
- **`docs/pydantic-integration.md`** — Using Pydantic models in test assertions

## What ovoscope Does

`ovoscope` is a **lightweight end-to-end testing framework** for OVOS skills. It:
- Runs a **MiniCroft** (in-process `SkillManager`) on a `FakeBus` (no network)
- Loads real skill plugins from entry points
- Fires `recognizer_loop:utterance` messages and captures the full message sequence
- Asserts expected behavior without audio, TTS, or GUI

**What ovoscope does NOT cover:** PHAL plugins (use unit tests), actual audio service, STT/TTS implementations, GUI rendering, skill lifecycle hooks, internal handler logic.

## Example Test File

```python
"""test/end2end/test_basic_interaction.py"""
from ovoscope import End2EndTest, get_minicroft

def test_hello_world():
    minicroft = get_minicroft(["ovos-skill-hello-world"])

    test = End2EndTest(
        utterance="hello",
        skill_id="ovos-skill-hello-world",
        expected_messages=["speak", "play_sound"],
        max_wait=5,
    )

    test.execute(minicroft)
```

## Canonical Examples

- **Hello World skill**: `ovos-skill-hello-world/test/end2end/test_*.py`
- **ovos-core**: `ovos-core/test/end2end/test_*.py`

## Common Patterns

See `docs/usage-guide.md` for detailed patterns:
1. **Intent matching** (Adapt, Padatious)
2. **Recording and replaying** fixtures
3. **Multi-turn conversations**
4. **Fallback handling**
5. **Session state** persistence
6. **Message filtering** and validation
7. **Timeout and wait** strategies
8. **Fixture replay** and regression testing

---

**For more details, see the full docs in this repository.**
