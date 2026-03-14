# FAQ — `ovoscope`
## How do I measure which bus message handlers my tests actually exercise?

Use bus coverage: set `track_bus_coverage=True` on `End2EndTest`.  After
`execute()`, `test.bus_coverage_report` contains a `BusCoverageReport` with
per-skill listener coverage (which `bus.on()` registrations were triggered)
and emitter coverage (which message types were observed / asserted).

```python
test = End2EndTest(
    skill_ids=["my-skill.author"],
    source_message=message,
    expected_messages=[...],
    track_bus_coverage=True,
    print_bus_coverage=True,   # print inline summary
)
test.execute()
print(test.bus_coverage_report.to_json())
```

See [docs/bus-coverage.md](docs/bus-coverage.md) for the full reference.
`BusCoverageTracker` — `ovoscope/bus_coverage.py:242`.

## How do I get an aggregate bus coverage report across an entire test suite?

Use the `bus_coverage_session` pytest fixture.  Each test calls
`bus_coverage_session.add(test.bus_coverage_report)` after `execute()`.  A
merged table is printed automatically at session end.  See
[docs/bus-coverage.md](docs/bus-coverage.md).

## How do I run bus coverage from the command line without writing pytest tests?

Use the `ovoscope bus-coverage` subcommand:

```bash
ovoscope bus-coverage path/to/fixtures/       # table report
ovoscope bus-coverage path/to/fixtures/ --format json
ovoscope bus-coverage path/to/fixtures/ --verbose   # per-msg detail
```

`cmd_bus_coverage` — `ovoscope/cli.py`.


## How do I test AudioService or PlaybackService without real audio hardware?
Use `AudioServiceHarness` or `PlaybackServiceHarness` from `ovoscope.audio`. Both run on a
`FakeBus` with `MockAudioBackend`/`MockTTS` respectively — no real audio device, TTS engine,
or network required. See [docs/audio-testing.md](docs/audio-testing.md) for the full API
reference. Requires `pip install ovoscope[audio]` (or `ovos-audio` installed separately).

## Why does AudioService.stop() silently ignore my stop() call in tests?
`AudioService._stop()` — `ovos-audio/ovos_audio/audio.py` — has a 1-second stop guard:
it does nothing if called within 1 second of `play()`. Tests must `time.sleep(1.1)` after
`play()` before calling `stop()`.

## Why doesn't FakeBus.wait_for_response() work in audio harness tests?
`FakeBus.wait_for_response()` does not work for synchronous in-process handlers because the
reply is emitted before the internal listener is registered. Use subscribe-emit-wait with a
`threading.Event` instead. `AudioServiceHarness.get_track_info()` and `list_backends()`
implement this pattern — `ovoscope/audio.py`.

## How do I test VAD (Voice Activity Detection) without a real microphone?

Use `MockVADEngine` from `ovoscope.listener`. It classifies all-zero bytes as silence and
any non-zero byte as speech. Inject it into `MiniListener(config, vad_instance=MockVADEngine())`
or use the declarative `VADTest` dataclass. No microphone, audio driver, or OPM plugin required.

```python
from ovoscope.listener import MockVADEngine, VADTest
VADTest(vad_instance=MockVADEngine(), audio_input=b"\\x01" * 512, expect_silence=False).execute()
```

## How do I test Wake Word detection without loading a real model?

Use `MockHotWordEngine(trigger_after=N)` from `ovoscope.listener`. It fires after exactly N
`update()` calls and auto-resets. Inject via `MiniListener(config, ww_instances={"hey_mycroft": engine})`
or use the declarative `WakeWordTest` dataclass.

```python
from ovoscope.listener import MockHotWordEngine, WakeWordTest
WakeWordTest(
    ww_instances={"hey_mycroft": MockHotWordEngine(trigger_after=2)},
    audio_chunks=[b"\\x00" * 512] * 4,
    expect_detected=True,
    expected_detection_frame=1,
).execute()
```

## What is `ovoscope`?
`ovoscope` is End-to-end test framework for OpenVoiceOS skills.
## How do I install it?
```bash
pip install ovoscope
```
Or for development:
```bash
uv pip install -e ovoscope/
```
## Where do I report bugs?
Open an issue on the GitHub repository. Ensure you are targeting the `dev` branch for fixes.
## How do I run tests?
```bash
uv run pytest ovoscope/test/ --cov=ovoscope
```
## How do I contribute?
1. Fork the repository and create a feature branch from `dev`.
2. Write tests for your changes.
3. Open a PR targeting the `dev` branch.
4. Ensure CI passes before requesting review.
## What CI workflows does ovoscope run?
Seven workflows: `unit_tests.yml` (pytest + coverage on PRs), `build_tests.yml` (sdist/wheel matrix build), `license_tests.yml` (dependency license audit via gh-automations), `pipaudit.yml` (CVE scanning), `release_workflow.yml` (test-gated alpha release), `publish_stable.yml` (stable release), and `conventional-label.yaml` (PR label automation).
## Does the release workflow run tests before publishing?
Yes. The `release_workflow.yml` has a `build_tests` job that runs the full test suite. The `publish_alpha` job depends on it via `needs: build_tests`, so a failing test blocks the alpha release.
## How does ovoscope's coverage reporting work in CI?
The `unit_tests.yml` workflow runs `pytest --cov=ovoscope --cov-report xml` and uses `py-cov-action/python-coverage-comment-action@v3` to post a coverage summary as a PR comment.
## What test coverage does ovoscope have?
104 tests across 6 test files achieving 89% overall coverage. Key areas tested: End2EndTest execute/assertions/serialization/routing/active skills/boot sequence/final session/from_message recording, CaptureSession lifecycle, MiniCroft config isolation/lang/pipeline, pytest_plugin fixture logic, pydantic_helpers bridge.
## What Python versions are supported?
See `QUICK_FACTS.md` — currently `>=3.10`.
## My tests pass locally but fail on CI — why?
Usually one of three causes:
1. **Different pipeline plugins installed** — The default session pipeline includes whatever
   pipeline plugins happen to be installed.  On CI, Gemma/Ollama/persona plugins may not be
   installed (or vice versa), changing which plugin handles the utterance.
   **Fix**: always pass an explicit `default_pipeline` to `get_minicroft()` (or use the default
   `DEFAULT_TEST_PIPELINE` by leaving `isolate_config=True`).
2. **User locale affecting intent matching** — `isolate_config=True` (the default) removes the
   user's `~/.config/mycroft/mycroft.conf` from the config chain so the test environment locale
   does not affect results.  Always leave this enabled.
3. **Skill plugin not discoverable** — The skill must be registered under the `opm.skill` entry
   point group.  Old-style `ovos.plugin.skill` entries are warned but not loaded by
   `find_skill_plugins()`.  Use `extra_skills={SKILL_ID: SkillClass}` to inject skills that
   lack a proper entry point.
## A persona / AI plugin is intercepting my test utterances
This happens because `SessionManager.default_session` is initialized at import time from the
full system config (which may include persona pipeline stages).
`MiniCroft` solves this with `default_pipeline` (default: `DEFAULT_TEST_PIPELINE`):
```python
from ovoscope import get_minicroft, DEFAULT_TEST_PIPELINE, ADAPT_PIPELINE
# Default — all standard stages, no AI/persona/OCP (recommended)
mc = get_minicroft([])
# Adapt-only for fast unit-style end2end tests
mc = get_minicroft([SKILL_ID], default_pipeline=ADAPT_PIPELINE)
# Opt in to persona explicitly
from ovoscope import PERSONA_PIPELINE
mc = get_minicroft([SKILL_ID], default_pipeline=DEFAULT_TEST_PIPELINE + PERSONA_PIPELINE)
```
`DEFAULT_TEST_PIPELINE` excludes persona, Ollama, OCP, and m2v stages.
The original pipeline is restored when `mc.stop()` is called.
## Why does `SessionManager.default_session.pipeline` matter?
When a message is emitted without an explicit `session` in its context, ovos-core creates a
session by copying `SessionManager.default_session`.  That copy inherits its `pipeline` list,
which controls which pipeline plugins are consulted for intent matching.
`MiniCroft.run()` overrides `SessionManager.default_session.pipeline` to `default_pipeline`
(set after FakeBus init messages are processed, just before `READY`), and restores it on
`stop()`.
## How is `isolate_config` different from `default_pipeline`?
- `isolate_config=True` — clears `Configuration.xdg_configs` so `~/.config/mycroft/mycroft.conf`
  is not read.  Prevents user locale, custom wake words, and user-level pipeline *config* from
  affecting tests.
- `default_pipeline` — overrides `SessionManager.default_session.pipeline` directly.  Necessary
  because the default session is initialized at module import time (before config isolation takes
  effect) and may already have the user's pipeline.
Both are enabled by default.  They are complementary.
## How do I know whether to use ADAPT_PIPELINE or PADATIOUS_PIPELINE for my test?
It depends on how the skill registers its intent:
| Decorator | Pipeline |
|-----------|----------|
| `@intent_handler(IntentBuilder(...))` | `ADAPT_PIPELINE` |
| `@intent_handler("my.intent")` (string ending in `.intent`) | `PADATIOUS_PIPELINE` |
| `@fallback_handler(priority=N)` | `FALLBACK_PIPELINE` |
| `@converse_handler` | `CONVERSE_PIPELINE` |
When in doubt, look at the intent files in `locale/en-us/` — if there is a file named `*.intent`,
it is Padatious.  If there is a file named `*.voc` or `*.rx`, it is Adapt.
## My skill emits extra messages (enclosure.eyes.*, add_context, configuration.patch) — how do I handle them?
Some skills emit low-level hardware events or internal context messages that are not part of the
utterance handling protocol.  Add them to `ignore_messages`:
```python
test = End2EndTest(
    ...
    ignore_messages=[
        "enclosure.eyes.level",   # Mark 1 LED animation
        "enclosure.eyes.look",
        "add_context",            # set_context() calls
        "configuration.patch",    # disable_confirm_listening() etc.
    ],
    ...
)
```
## A skill emits a raw message (no source/dest) like recognizer_loop:sleep — how do I test it?
Some skills call `self.bus.emit(Message("some.message"))` without inheriting source/dest.
These messages have `source=None` and will fail source-checking in the framework.
Use `async_messages` to assert they were received without checking order or source:
```python
test = End2EndTest(
    ...
    ignore_messages=["recognizer_loop:sleep"],  # exclude from ordered sequence
    async_messages=["recognizer_loop:sleep"],   # assert it was received somewhere
    ...
)
```
## My test passes locally but the user's blacklisted skills cause failures on CI
Users may have skills like `skill-ovos-stop.openvoiceos` in `blacklisted_skills` in their
`~/.config/mycroft/mycroft.conf`.  `Session.__init__` reads this from the live
`Configuration()` singleton dict cache (not invalidated by `reload()`).
`MiniCroft` solves this: when `isolate_config=True` (the default), it patches
`Configuration()["skills"]["blacklisted_skills"] = []` and
`Configuration()["intents"]["blacklisted_intents"] = []` in `run()`, and restores them in `stop()`.
This is complementary to the `xdg_configs = []` isolation applied in `__init__`.
## Can I use typed pydantic models instead of raw Message objects?
Yes. Install the optional pydantic extras:
```bash
pip install ovoscope[pydantic]
```
Then use the bridge in `ovoscope.pydantic_helpers`:
```python
from ovoscope.pydantic_helpers import to_bus_message, from_bus_message
from ovos_pydantic_models import RecognizerLoopUtteranceMessage, RecognizerLoopUtteranceData, SpeakMessage
# Build a typed source message — validated at construction
utterance = to_bus_message(RecognizerLoopUtteranceMessage(
    data=RecognizerLoopUtteranceData(utterances=["hello"], lang="en-us")
))
# Parse a received message into a typed model for richer assertions
messages = test.execute()
speak = from_bus_message(messages[0], SpeakMessage)
assert "hello" in speak.data.utterance.lower()
```
A typo in a field name (`"utterance"` vs `"utterances"`) raises `ValidationError` at
construction time instead of silently producing a wrong test.
## How do I validate a JSON fixture file before loading it?
Use `validate_fixture()` from `ovoscope.pydantic_helpers` (requires `ovoscope[pydantic]`):
```python
from ovoscope.pydantic_helpers import validate_fixture
from ovoscope import End2EndTest
test = End2EndTest.deserialize(validate_fixture("test/fixtures/hello_world.json"))
test.execute()
```
If any message in the fixture is malformed, a clear `ValidationError` is raised pointing
to the offending field — instead of a cryptic `KeyError` inside `deserialize()`.
## How do I trigger non-utterance events during a test?
Use `MiniCroft.inject_message(msg)`:
```python
from ovos_bus_client.message import Message
mc.inject_message(Message("mycroft.gui.connected", {"connected": True}))
```
This emits an arbitrary message on the FakeBus during a test without going through the
utterance pipeline — useful for timer events, GUI events, or skill API calls.
## How do I assert a skill spoke a specific phrase without checking the full message sequence?
Use `End2EndTest.assert_spoke(text, lang)`:
```python
test = End2EndTest(
    skill_ids=["my-skill.author"],
    source_message=Message("recognizer_loop:utterance", {"utterances": ["hello"], "lang": "en-US"}, {}),
    expected_messages=[],  # not used by assert_spoke
)
test.assert_spoke("Hello, world!", lang="en-US")
```
`assert_spoke()` calls `execute()` internally and scans captured messages for a `speak`
message with the matching utterance and lang.
## `get_minicroft()` hangs forever — what do I do?
Pass `max_wait` to set a timeout:
```python
mc = get_minicroft(["my-skill.author"], max_wait=30)
```
If `MiniCroft` does not reach `READY` within `max_wait` seconds, a `TimeoutError` is raised
with the skill IDs — pointing you at the skill startup logs. The default is 60 seconds.
## How do I use the `minicroft` pytest fixture?
The fixture is registered automatically when ovoscope is installed (via the `pytest11` entry
point). Just declare `skill_ids` on your test class:
```python
class TestMySkill:
    skill_ids = ["my-skill.author"]
    def test_something(self, minicroft):
        from ovoscope import End2EndTest
        from ovos_bus_client.message import Message
        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=self.skill_ids,
            source_message=Message(
                "recognizer_loop:utterance",
                {"utterances": ["hello"], "lang": "en-US"},
                {},
            ),
            expected_messages=[...],
        )
        test.execute()
```
The `MiniCroft` is started once per class and stopped in teardown — no `setUp`/`tearDown`
boilerplate needed.
## How do I test a pipeline plugin (not a skill) like PersonaService?
Pipeline plugins are loaded by `MiniCroft` automatically via `IntentService`. Access them via:
```python
mc = get_minicroft([], default_pipeline=PERSONA_PIPELINE)
persona_svc = mc.intents.pipeline_plugins["ovos-persona-pipeline-plugin"]
```
Inject mocks directly into the plugin's state before each test:
```python
def setUp(self):
    persona_svc.personas.clear()          # remove real solvers (Gemma, Ollama, etc.)
    persona_svc.active_persona = None     # reset pipeline state
    persona_svc.personas["TestBot"] = MockPersona("TestBot", "forty two")
```
The `skill_ids=[]` parameter tells MiniCroft to load no skills — only pipeline plugins.
See `ovos-persona/test/end2end/test_persona.py` for a full working example.
---
## How do I test skills in non-English languages?
Pass `secondary_langs` to `get_minicroft()`:
```python
croft = get_minicroft(
    [SKILL_ID],
    secondary_langs=["pt-PT", "de-DE", "es-ES"],
)
```
This patches `Configuration()["secondary_langs"]` before Adapt/Padatious initialize, so they create per-language engines and register vocab for all specified languages. Without this, only the system's default language has vocab registered.
## Why does `End2EndTest.from_message()` crash with `TypeError: argument of type 'NoneType' is not iterable`?
This was a bug where `async_messages` defaulted to `None` and was passed to `CaptureSession`, which tried `msg.msg_type in None`. Fixed by defaulting to `[]`.
## Why do JSON fixture replays fail on session context?
Session context includes timestamps (e.g., `active_skills` activation time) that differ between recording and replay. Set `test_msg_context=False` on fixture tests. For skills with random dialog rendering (like quote pools), also set `test_msg_data=False`.
## Does `from_message()` filter GUI messages during recording?
Yes — `from_message()` now accepts `ignore_gui=True` (default), which adds `GUI_IGNORED` messages to the capture filter. This prevents GUI namespace messages from appearing in recorded fixtures.
## How do I override pipeline plugin config in a test (e.g. M2V model path)?
Pass `pipeline_config` to `get_minicroft()`. It is a `dict` keyed by the plugin's config key under `Configuration()["intents"]`:
```python
croft = get_minicroft(
    [SKILL_ID],
    default_pipeline=M2V_PIPELINE,
    pipeline_config={
        "ovos_m2v_pipeline": {
            "model": "Jarbas/ovos-model2vec-intents-distiluse-base-multilingual-cased-v2"
        }
    },
)
```
The override is patched into `Configuration()["intents"]` before `super().__init__()`, so the pipeline plugin reads the test value in its `__init__`. It is restored in `stop()`. This is useful for forcing a specific model regardless of what `mycroft.conf` says locally.
## Why do M2V tests skip when the multilingual model is not cached?
`ovos-m2v-pipeline` classifies utterances using a pre-trained model whose `classes_` are fixed intent labels. A language-specific model (e.g. Portuguese-only) won't contain English intent names and will always return no match. The multilingual model (`Jarbas/ovos-model2vec-intents-distiluse-base-multilingual-cased-v2`) covers all OVOS skill intent names. Tests that use M2V should skip when this model is not cached locally (to avoid downloading a large model in CI). Download it once with:
```bash
python -c "from model2vec.inference import StaticModelPipeline; StaticModelPipeline.from_pretrained('Jarbas/ovos-model2vec-intents-distiluse-base-multilingual-cased-v2')"
```

---

## Bus Coverage

### Why do I see `Thread-1`, `Thread-2` entries in my bus coverage report?

**This was fixed in ovoscope 0.14.0.** Previously, OVOS components that inherit 
from `Thread` (such as `SkillManager`, `PlaybackService`, `OVOSDinkumVoiceService`, 
and `MediaService`) had their handlers attributed to generic names like `Thread-1`, 
`Thread-2`, etc.

The fix uses Python's Method Resolution Order (MRO) to automatically resolve 
Thread subclasses to their actual class names. The `_get_component_name()` method 
walks the MRO chain and skips the `Thread` class, returning the first non-Thread 
class name.

**Special case:** `MiniCroft` (the test harness) is automatically renamed to 
`SkillManager` in reports for clarity, since MiniCroft is just a test wrapper 
around SkillManager.

This approach is automatic and requires no manual maintenance of message type patterns.
Any future Thread-based components will be correctly attributed without code changes.

See [docs/bus-coverage.md](docs/bus-coverage.md) for the full reference.

---

## CLI

### How do I record a fixture from the command line?
```bash
ovoscope record --skill-id ovos-skill-hello-world.openvoiceos \
    --utterance "hello" --output fixture.json
```

### How do I replay a fixture?
```bash
ovoscope run fixture.json --verbose
```

### How do I compare two fixture files?
```bash
ovoscope diff expected.json actual.json
```
Exit code 0 = identical, 1 = differences found.

### How do I scan my workspace for E2E coverage gaps?
```bash
ovoscope coverage "OpenVoiceOS Workspace/" --format table
```

---

## PHAL Testing

### Can I test PHAL plugins with ovoscope?
Yes — any PHAL plugin that communicates only via the MessageBus (no physical
hardware) is testable with `MiniPHAL` or `PHALTest` from `ovoscope.phal`.

### Which PHAL plugins require real hardware?
`ovos-PHAL-plugin-alsa`, `ovos-PHAL-plugin-mk1`, `ovos-PHAL-plugin-dotstar`.
These should use hardware-in-the-loop integration tests instead.

---

## OCP Testing

### How do I test an OCP skill without a real HTTP server?
Use `OCPTest` with `mock_responses` — keys are URL substrings matched
against actual requests, values are the JSON bodies returned.

### What message flow does OCP testing drive?
`recognizer_loop:utterance` → `ovos.common_play.query` → `ovos.common_play.query.response` → `ovos.common_play.start`

---

## GUI Assertions

### How do I assert that a skill showed a GUI page?
```python
from ovoscope import GUICaptureSession
with GUICaptureSession(mc.bus) as gui:
    # ... trigger interaction ...
    gui.assert_page_shown("my_skill", "main.qml")
```

### How do I assert that a skill set a specific session data key in a namespace?
Use `assert_namespace_has_key()`:
```python
with GUICaptureSession(mc.bus) as gui:
    # ... trigger interaction ...
    gui.assert_namespace_has_key("my_skill", "temperature")
```
This checks that a `mycroft.session.set` message was captured containing the given key in the specified namespace. See [docs/gui-testing.md](docs/gui-testing.md).

---

## Coverage Scanner

### What entry-point groups does the scanner detect?
`opm.skill`, `opm.pipeline`, `opm.phal`, `opm.plugin.tts`, `opm.plugin.stt`,
`opm.plugin.audio`, `opm.common_play`, `opm.solver`.

### How is "covered" defined?
A repo is considered covered when `test/end2end/` (or `tests/end2end/`)
exists and contains at least one `.py` file (excluding `__init__.py`).
