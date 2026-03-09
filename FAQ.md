Last Edit: Claude Sonnet 4.6 - 2026-03-09 - Motive: Updated pydantic_helpers module name (pydantic.py → pydantic_helpers.py) in all FAQ entries.

# FAQ — `ovoscope`

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
