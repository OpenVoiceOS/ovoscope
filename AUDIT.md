# ovoscope — Audit Report
## Documentation Status
- [x] AGENTS.md Header Format
- [x] QUICK_FACTS.md
- [x] FAQ.md
- [x] MAINTENANCE_REPORT.md
- [x] AUDIT.md
- [x] SUGGESTIONS.md
- [x] docs/index.md
- [x] docs/usage-guide.md
- [x] docs/ci-integration.md
---
## Technical Debt & Issues
### ~~[CRITICAL] No unit tests for ovoscope itself~~ ✅ FIXED
62 unit tests across `test/unittests/test_capture_session.py`, `test/unittests/test_end2end.py`,
`test/unittests/test_minicroft.py`, `test/unittests/test_pydantic_helpers.py`, and
`test/unittests/test_audio_harness.py`.
All pass (62 passed, 0 failed).
---
### ~~[MAJOR] Missing LICENSE file~~ ✅ FIXED
LICENSE file (Apache-2.0) added to repo root. `pyproject.toml` correctly references it.
---
### ~~[MAJOR] `End2EndTest.execute()` returns `None`~~ ✅ FIXED
`execute()` now returns `List[Message]`. Signature changed to
`def execute(self, timeout: int = 30) -> List[Message]`. `assert_spoke()` builds on this.
---
### ~~[MAJOR] No type annotations on any public method~~ ✅ FIXED
All public methods in `ovoscope/__init__.py` and new modules now have PEP 484 annotations.
---
### [MODERATE] `CaptureSession.capture()` returns `None` — captured messages inaccessible inline
**Evidence**: `ovoscope/__init__.py` — `capture()` returns nothing. Captured
messages are only accessible via `self.responses` after `finish()` is called. The pattern
`capture.capture(msg); messages = capture.finish()` is functional but forces a two-step flow.
**Impact**: Cannot chain captures or do inline assertions without accessing the attribute
directly. Slightly awkward for advanced multi-turn test composition.
**Recommended fix**: Return `List[Message]` (the current `self.responses` snapshot) from
`capture()`, or add a `messages` property. No breaking change required.
---
### ~~[MODERATE] `get_minicroft()` busy-waits with no timeout~~ ✅ FIXED
`get_minicroft()` now accepts `max_wait: float = 60` and raises `TimeoutError` if the deadline
is exceeded. Signature: `def get_minicroft(skill_ids, *args, max_wait=60, **kwargs) -> MiniCroft`.
---
### ~~[MINOR] `setup.py` should migrate to `pyproject.toml`~~ ✅ FIXED
`setup.py` removed. `pyproject.toml` uses `build-backend = "setuptools.build_meta"`,
`dynamic = ["version"]`, and `[tool.setuptools.dynamic] version = {attr = "ovoscope.version.__version__"}`.
`version.py` now exports `__version__`. Optional pydantic extras added:
`pip install ovoscope[pydantic]`.
---
### [MINOR] CI action pins at `@master`
**Evidence**: GitHub Actions workflows use `pypa/gh-action-pypi-publish@master` and
`ad-m/github-push-action@master`. The `@master` ref is not pinned to a specific SHA, making
builds non-reproducible if the upstream action changes.
**Recommended fix**: Pin to `pypa/gh-action-pypi-publish@release/v1` and a specific SHA for
`ad-m/github-push-action`.
---
## Next Steps (Priority Order)
1. Address CaptureSession.capture() return value — usability
2. Pin CI action refs — reproducibility

---
## Bus Coverage Module — Full Audit [2026-03-12]

### [CRITICAL] async_responses excluded from emitter coverage
**Evidence**: `ovoscope/__init__.py:666` — `record_session(messages, self.expected_messages)` passes only `capture.responses`, not `capture.async_responses`. Async messages collected in `CaptureSession.async_responses` (`__init__.py:503`) are silently dropped.
**Impact**: Tests that use `async_messages=` configuration report incomplete emitter coverage; any message type that only appears in async responses shows as "not observed".
**Fix**: Pass `messages + capture.async_responses` (or the union) to `record_session()`.

### [CRITICAL] Unattributed expected_messages silently disappear
**Evidence**: `ovoscope/bus_coverage.py:540-549` — when `_skill_id_for_message()` returns `None` for an expected message, the fallback (lines 542–547) only works if the same `msg_type` was already observed under some skill. If no skill observed that type yet, the entry is dropped entirely (no `__unattributed__` bucket).
**Impact**: A message that appears in `expected_messages` but has no `skill_id` and was never observed is completely invisible to the report — a silent false negative.
**Fix**: Fall back to a sentinel component label (`"__core__"` or `"__unattributed__"`) instead of returning `None`.

### [CRITICAL] Registration-time handlers always show NOT TESTED — misleading
**Evidence**: `ovoscope/bus_coverage.py:368` / `ovoscope/__init__.py:647` — `snapshot_listeners()` is called after `MiniCroft` reaches READY. Handlers invoked *during* skill loading (`register_vocab`, `register_intent`, `mycroft.skills.train`, lifecycle handlers) were called *before* the snapshot and will always show 0 invocations.
**Impact**: Users see `register_intent: NOT TESTED` and conclude their intent registration failed, when in fact it succeeded during `MiniCroft.run()`.
**Fix**: (1) Document explicitly. (2) Consider calling `start_tracking()` before READY to capture registration-time invocations, then snapshot after. Or mark known registration-time handlers with a distinct `LOAD_TIME` tag rather than `NOT TESTED`.

### [CRITICAL] Non-skill messages silently excluded from emitter coverage
**Evidence**: `ovoscope/bus_coverage.py:529-531` — messages with no `skill_id` in context are dropped. Core services (`IntentService`, `AdaptPipeline`, `FallbackService`) never set `skill_id` in context, so their emitted messages are invisible to coverage even though they appear in `CaptureSession.responses`.
**Impact**: Emitter coverage for all non-skill components is permanently 0/0. Tests that explicitly assert pipeline, intent-service, or fallback messages get no emitter coverage for those.
**Fix**: Infer component from `msg.context.get("source")` or the `_invocations` map, or use a `"__core__"` bucket for unattributed observed messages.

### [MAJOR] Unused `skill_map` variable in `record_session()`
**Evidence**: `ovoscope/bus_coverage.py:525` — `skill_map = self._skill_instance_map()` is called but the result is never referenced. `_skill_id_for_message()` reads only `msg.context` and ignores the map.
**Impact**: Dead code; redundant object construction on every `record_session()` call.
**Fix**: Remove line 525.

### [MAJOR] `_get_bus_events()` called three times in `snapshot_listeners()`
**Evidence**: `ovoscope/bus_coverage.py:432, 448, 464` — three passes each call `dict(bus.ee._events)`.
**Impact**: O(n) redundant copy of the handler registry. Negligible at 76 events but wasteful.
**Fix**: Call once at the start of `snapshot_listeners()` and reuse the result.

### [MAJOR] Double-stop risk in `cmd_bus_coverage()`
**Evidence**: `ovoscope/cli.py:349-360` — sets `test.minicroft = mc` (so `managed` stays `False`), then calls `test.execute()`, then stops `mc` in a `finally` block. If the test internally stops the minicroft (or if `execute()` is refactored to always stop), `mc.stop()` is called twice.
**Impact**: Potential exception or resource leak on double-stop depending on `MiniCroft.stop()` idempotency.
**Fix**: Set `test.managed = False` explicitly and rely solely on the `finally` block; or let `execute()` own the minicroft lifecycle by not pre-setting it.

### [MAJOR] `pytest_terminal_summary` hook uses private pytest internals
**Evidence**: `ovoscope/pytest_plugin.py:244, 250` — accesses `fixturemanager._arg2fixturedefs` and `fd.cached_result`, both private attributes.
**Impact**: Hook silently breaks on pytest version upgrades.
**Fix**: Use a session-scoped list stored on the config object (`config._bus_coverage_reports = []`) populated via the fixture's finalizer, and consumed in the hook. No private attrs needed.

### [MAJOR] `once()` handlers invisible after firing
**Evidence**: `bus_coverage.py:368` — `snapshot_listeners()` runs after READY. One-shot handlers registered with `bus.once()` that fired during skill loading are already de-registered before the snapshot.
**Impact**: Any skill that uses `bus.once()` during initialization has those handlers invisible to coverage.
**Fix**: Start invocation tracking before READY (in `get_minicroft()` or `MiniCroft.run()`), then snapshot afterward; the invocations will still be counted.

### [MAJOR] `ignore_messages` list silently excludes messages from emitter coverage
**Evidence**: `ovoscope/__init__.py:504-505` — messages in `ignore_messages` never reach `responses`, so they're never passed to `record_session()`.
**Impact**: If a skill emits a message type that's in the ignore list (e.g., GUI messages when `ignore_gui=True`), that type has 0 emitter coverage regardless of how many times it was emitted.
**Fix**: Pass ignored messages as a third argument to `record_session()` (or include them as a separate `ignored_responses` bucket). Document this explicitly.

### [MAJOR] No JSON schema version field
**Evidence**: `ovoscope/bus_coverage.py:297-301` — `to_json()` produces `{"skills": [...], "totals": {...}}` with no version.
**Impact**: External parsers cannot detect breaking format changes.
**Fix**: Add `"schema_version": "1"` to the output dict.

### [MINOR] Column widths hardcoded in `print_report()`
**Evidence**: `ovoscope/bus_coverage.py:241, 262` — `'Skill':<34` clips skill IDs longer than 34 chars.
**Fix**: `col_w = max(len(s.skill_id) for s in self.skills) + 2` as dynamic width.

### [MINOR] Coverage summary printed before test assertions
**Evidence**: `ovoscope/__init__.py:668-669` — `summary_line()` is printed before the assertion blocks (lines 671+). A failing test still prints coverage, creating confusing output ordering.
**Fix**: Move the `print_bus_coverage` block to the end of `execute()`, after all assertions.

### [MINOR] `bus_coverage_report` type hint uses `Optional[Any]`
**Evidence**: `ovoscope/__init__.py:589` — avoids circular import by using `Any`.
**Fix**: `Optional["BusCoverageReport"]` with `from __future__ import annotations` (already imported at line 1).

### [NITPICK] `_SKIP` set has fragile `"type"` entry
**Evidence**: `ovoscope/bus_coverage.py:445` — `_SKIP = {"FakeBus", "type"}`. `"type"` matches any classmethod handler whose `__self__` is a class object. Correct result by coincidence; other classmethods on non-Python-builtin classes would also match `type.__name__ == "type"` only if they're bare Python `type`.
**Fix**: Skip by `isinstance(owner, type)` check instead of string comparison.

### Docs gaps (bus-coverage.md)
- **Missing**: registration-time handlers are never invocated in tests — add to Limitations
- **Missing**: pipeline matching is not bus-driven (Adapt/Padatious listener coverage structurally < 100%) — add note
- **Missing**: `async_responses` are excluded from emitter coverage — add to Limitations
- **Missing**: `ignore_messages` types are excluded from emitter coverage — add to Limitations
- **Missing**: core services (`IntentService`, `FallbackService`, etc.) always show 0/0 emitter coverage because they don't set `skill_id` in context — add note
