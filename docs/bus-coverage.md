# Bus Coverage

Bus coverage measures how thoroughly an end-to-end test exercises a skill's
MessageBus interface.  Unlike line coverage (which measures code paths), bus
coverage answers:

> *Which message handlers did my tests actually trigger?  Which messages did
> the skill emit, and which of those did I explicitly assert?*

## Two dimensions

| Dimension | What it measures |
|-----------|-----------------|
| **Listener coverage** | Which `bus.on(msg_type, handler)` registrations were invoked (i.e. `bus.emit` was called for that msg_type) during tests |
| **Emitter coverage** | Which message types the skill emitted (*observed*) and which were listed in `expected_messages` (*asserted*) |

Both dimensions are grouped **per skill_id**.

---

## Enabling in a test

Add `track_bus_coverage=True` to `End2EndTest`:

```python
from ovoscope import End2EndTest

test = End2EndTest(
    skill_ids=["my-skill.author"],
    source_message=message,
    expected_messages=[...],
    track_bus_coverage=True,   # enable tracking
    print_bus_coverage=True,   # print inline summary after execute()
)
test.execute()
report = test.bus_coverage_report
```

### Fields on `End2EndTest`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `track_bus_coverage` | `bool` | `False` | Enable `BusCoverageTracker` for this test |
| `print_bus_coverage` | `bool` | `False` | Print a one-line summary per skill after `execute()` |
| `bus_coverage_report` | `BusCoverageReport \| None` | `None` | Populated after `execute()` when `track_bus_coverage=True` |

Source: `End2EndTest` — `ovoscope/__init__.py:532`

---

## Pytest session summary

Tests opt in to the session-wide summary via the `bus_coverage_session` fixture:

```python
class TestMySkill:
    skill_ids = ["my-skill.author"]

    def test_hello(self, minicroft, bus_coverage_session):
        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=self.skill_ids,
            source_message=message,
            expected_messages=[...],
            track_bus_coverage=True,
        )
        test.execute()
        bus_coverage_session.add(test.bus_coverage_report)
```

A merged table is printed at the end of the pytest session:

```
========================= Bus Coverage Report =========================
Skill                              Listeners      Observed  Asserted
──────────────────────────────────────────────────────────────────────
my-skill.author                    8/12   66.7%   10/15     6/15
other-skill.author                12/12  100.0%    8/8      8/8
──────────────────────────────────────────────────────────────────────
TOTAL                             20/24   83.3%   18/23    14/23
```

Source: `BusCoverageCollector` — `ovoscope/pytest_plugin.py:81`

---

## CLI subcommand

```
ovoscope bus-coverage <TEST_DIR> [--skill-id ID] [--format table|json] [--verbose]
```

Loads every `.json` fixture in `TEST_DIR`, runs each with
`track_bus_coverage=True`, aggregates, and prints the report.

```bash
# Table report
ovoscope bus-coverage Skills/ovos-skill-hello-world/test/end2end/

# JSON export
ovoscope bus-coverage Skills/ovos-skill-hello-world/test/end2end/ --format json

# Verbose per-msg detail
ovoscope bus-coverage Skills/ovos-skill-hello-world/test/end2end/ --verbose

# Filter to a specific skill
ovoscope bus-coverage Skills/ --skill-id ovos-skill-hello-world.openvoiceos
```

Source: `cmd_bus_coverage` — `ovoscope/cli.py`

---

## Public API

### `ovoscope.bus_coverage.HandlerEntry`

`HandlerEntry` — `ovoscope/bus_coverage.py:56`

| Attribute | Type | Description |
|-----------|------|-------------|
| `msg_type` | `str` | Bus message type |
| `handler_count` | `int` | Number of distinct handlers registered for this type |
| `invocation_count` | `int` | Times `bus.emit` was called for this type |
| `covered` | `bool` | `invocation_count > 0` |

### `ovoscope.bus_coverage.EmitterEntry`

`EmitterEntry` — `ovoscope/bus_coverage.py:85`

| Attribute | Type | Description |
|-----------|------|-------------|
| `msg_type` | `str` | Bus message type |
| `observed_count` | `int` | Times in `CaptureSession.responses` |
| `asserted_count` | `int` | Times in `End2EndTest.expected_messages` |
| `observed` | `bool` | `observed_count > 0` |
| `asserted` | `bool` | `asserted_count > 0` |

### `ovoscope.bus_coverage.SkillBusCoverage`

`SkillBusCoverage` — `ovoscope/bus_coverage.py:118`

| Property | Returns | Description |
|----------|---------|-------------|
| `listener_coverage_pct` | `float` | % of listener msg_types invoked |
| `observed_emitter_pct` | `float` | % of emitter entries that were observed |
| `asserted_emitter_pct` | `float` | % of emitter entries that were asserted |
| `to_dict()` | `dict` | JSON-serializable representation |

### `ovoscope.bus_coverage.BusCoverageReport`

`BusCoverageReport` — `ovoscope/bus_coverage.py:163`

| Method | Description |
|--------|-------------|
| `summary_line()` | One-line summary per skill, joined by newlines |
| `print_report(verbose=False)` | Print formatted table to stdout |
| `to_json()` | Serialize to JSON string |

### `ovoscope.bus_coverage.BusCoverageTracker`

`BusCoverageTracker` — `ovoscope/bus_coverage.py:242`

| Method | Description |
|--------|-------------|
| `snapshot_listeners()` | Introspect bus after READY; map handlers to skills |
| `start_tracking()` | Monkey-patch `bus.emit` to count invocations |
| `stop_tracking()` | Restore original `bus.emit` |
| `record_session(responses, expected_messages)` | Feed session data into emitter tracking |
| `build_report()` | Compile a `BusCoverageReport` from all accumulated data |

---

## How listener attribution works

After `MiniCroft` reaches READY, `BusCoverageTracker.snapshot_listeners()`
uses a three-pass strategy:

1. **Skills via EventContainer** — reads `skill.events.events` for every
   entry in `minicroft.plugin_skills`.  This is authoritative because
   ovos-workshop wraps handlers in `create_wrapper` closures before calling
   `bus.on()`, making `handler.__self__` unreliable for skill handlers.
2. **Core components via direct `__self__`** — handlers whose owner is not
   a loaded skill are attributed by `type(owner).__name__`
   (e.g. `IntentService`, `AdaptPipeline`, `FallbackService`).
3. **Closure scan** — handlers without a direct `__self__` are scanned for
   bound-method cell variables that point to a known skill instance.

Source: `BusCoverageTracker.snapshot_listeners` — `ovoscope/bus_coverage.py:368`

---

## `__core__` bucket

Messages emitted by core services (`IntentService`, `FallbackService`, pipeline
components) do not carry `skill_id` in their context.  These messages are
attributed to the `"__core__"` bucket in both observed and asserted emitter
tracking so they are never silently dropped.  They appear as a normal row
labelled `__core__` in the report.

Source: `BusCoverageTracker.record_session` — `ovoscope/bus_coverage.py:510`

---

## Limitations

- **Registration-time handlers always show NOT TESTED** — `register_vocab`,
  `register_intent`, `mycroft.skills.train`, and other skill lifecycle handlers
  are invoked during `MiniCroft.run()` *before* `snapshot_listeners()` is called.
  They will always show 0 invocations regardless of test coverage.  This is
  structural, not a test failure.  Source: `snapshot_listeners` —
  `ovoscope/bus_coverage.py:368`.

- **`bus.once()` handlers are invisible after firing** — one-shot handlers
  registered with `bus.once()` during skill loading de-register before
  `snapshot_listeners()` runs.  They will not appear in the listener report.

- **Pipeline matching is not bus-driven** — Adapt and Padatious intent matching
  is a direct callable call inside `IntentService`, not a `bus.emit`.
  Pipeline handler listener coverage will structurally never reach 100%.

- **`ignore_messages` types are excluded from emitter coverage** — message
  types in `End2EndTest.ignore_messages` (e.g. GUI messages when
  `ignore_gui=True`) never reach `CaptureSession.responses` and therefore
  show 0 observed count regardless of how many times they were emitted.
  Source: `CaptureSession.capture` — `ovoscope/__init__.py:503`.

- **`async_responses` are included in observed emitter coverage** — since
  v0.x, `async_responses` are merged with `responses` before
  `record_session()` so async messages are no longer silently dropped.
  Source: `End2EndTest.execute` — `ovoscope/__init__.py:666`.

- **Only skills loaded through `MiniCroft.plugin_skills` are attributed**.
  Injected skills passed via `extra_skills` are included; skills from other
  processes are not.

- **Listener coverage tracks invocations by msg_type, not by individual
  handler**.  If two handlers for the same type are registered, one
  invocation counts both.
