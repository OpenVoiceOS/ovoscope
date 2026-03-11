---
name: ovoscope
description: Generate test boilerplate, run ovoscope tests, record fixtures, and validate expectations for OpenVoiceOS skills. Use when testing OVOS skills or creating test templates.
---

# ovoscope — OVOS End-to-End Testing

**Use this skill when you are:**
- Creating or scaffolding end-to-end tests for an OVOS skill
- Debugging failing ovoscope tests
- Recording live test fixtures from running skills
- Validating test expectations against actual behavior
- Testing skill interaction patterns (Adapt, Padatious, multi-turn, fallback, etc.)
- Setting up CI/CD integration for skill E2E tests

## Commands

### record
Record a live message sequence as a test fixture.
```bash
ovoscope record --skill-id <skill_id> --utterance "<utterance>" --output fixture.json
ovoscope record --live --bus-url ws://localhost:8181/core --skill-id <id> --utterance "<utt>" --output fixture.json
```

### run
Replay a fixture file and exit 1 on failure.
```bash
ovoscope run fixture.json [--verbose] [--timeout 30]
```

### diff
Compare two fixture files with colored output.
```bash
ovoscope diff expected.json actual.json [--include-context]
```

### validate
Schema-validate one or more fixture files.
```bash
ovoscope validate fixture.json [fixture2.json ...]
```

### coverage
Scan a workspace root and report E2E test coverage.
```bash
ovoscope coverage /path/to/workspace [--format table|json]
```

## Documentation

- **[assets/docs/usage-guide.md](assets/docs/usage-guide.md)** — 12 test patterns with full examples
- **[assets/docs/end2end-test.md](assets/docs/end2end-test.md)** — `End2EndTest` parameter reference
- **[assets/docs/minicroft.md](assets/docs/minicroft.md)** — `MiniCroft` / `get_minicroft()` reference
- **[assets/docs/listener.md](assets/docs/listener.md)** — VAD, WakeWord, STT pipeline testing
- **[assets/docs/phal.md](assets/docs/phal.md)** — PHAL plugin testing
- **[assets/docs/audio-testing.md](assets/docs/audio-testing.md)** — AudioService / PlaybackService harnesses
- **[assets/docs/ocp.md](assets/docs/ocp.md)** — OCP / Common Play testing
- **[assets/docs/pipeline.md](assets/docs/pipeline.md)** — Pipeline plugin (intent) testing
- **[assets/docs/gui-testing.md](assets/docs/gui-testing.md)** — GUI message assertion
- **[assets/docs/cli.md](assets/docs/cli.md)** — CLI reference
- **[assets/docs/ci-integration.md](assets/docs/ci-integration.md)** — GitHub Actions setup
- **[assets/FAQ.md](assets/FAQ.md)** — Common questions and troubleshooting
- **[assets/QUICK_FACTS.md](assets/QUICK_FACTS.md)** — Machine-readable reference

## Key Classes

```python
from ovoscope import (
    End2EndTest,         # declarative test runner
    MiniCroft,           # in-process skill runtime
    get_minicroft,       # factory: create + wait for READY
    CaptureSession,      # message recorder for a single interaction
    GUICaptureSession,   # capture gui.* messages
    MiniListener,        # audio transformer / VAD / WakeWord pipeline
    get_mini_listener,   # factory: create MiniListener
)
from ovoscope.listener import MockVADEngine, MockHotWordEngine, VADTest, WakeWordTest
from ovoscope.phal import MiniPHAL, PHALTest
from ovoscope.ocp import OCPTest
from ovoscope.pipeline import PipelineHarness
from ovoscope.audio import AudioServiceHarness, PlaybackServiceHarness
```

## Requirements

- Python 3.10+
- `ovos-core>=2.0.4a2`
- `ovos-audio>=1.2.0` (optional, for audio harness)

## License

Apache 2.0
