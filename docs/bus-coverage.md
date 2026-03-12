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
iterates over the FakeBus handler registry (`bus.ee._events` in pyee v8+).
For each handler, it checks `handler.__self__` (bound-method owner) against
`minicroft.plugin_skills`.  Handlers whose owner is not a loaded skill are
silently skipped (IntentService, SkillManager internals, etc.).

Source: `BusCoverageTracker.snapshot_listeners` — `ovoscope/bus_coverage.py:289`

---

## Limitations

- Only skills loaded through `MiniCroft.plugin_skills` are attributed.  Injected
  skills passed via `extra_skills` are included; skills from other processes are not.
- Listener coverage tracks invocations by *msg_type*, not by individual handler.
  If two handlers for the same type are registered, one invocation counts both.
- Emitter attribution relies on `msg.context["skill_id"]` being set correctly by
  the skill.  Messages without `skill_id` in context (e.g. pipeline messages) use
  a fallback heuristic: they are attributed to the first skill that already
  observed that msg_type.
