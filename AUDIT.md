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

### ~~[CRITICAL] async_responses excluded from emitter coverage~~ ✅ FIXED
`execute()` now passes `messages + list(capture.async_responses)` to `record_session()`. Source: `ovoscope/__init__.py:666`.

### ~~[CRITICAL] Unattributed expected_messages silently disappear~~ ✅ FIXED
Both observed and expected messages with no `skill_id` in context now fall back to the `"__core__"` sentinel bucket. Source: `BusCoverageTracker.record_session` — `ovoscope/bus_coverage.py:510`.

### [CRITICAL] Registration-time handlers always show NOT TESTED — misleading
**Evidence**: `ovoscope/bus_coverage.py:368` / `ovoscope/__init__.py:647` — `snapshot_listeners()` is called after `MiniCroft` reaches READY. Handlers invoked *during* skill loading were called *before* the snapshot and will always show 0 invocations.
**Impact**: Users see `register_intent: NOT TESTED` and conclude their intent registration failed.
**Status**: Documented in `docs/bus-coverage.md` Limitations as a known structural constraint. A `LOAD_TIME` tag or pre-READY tracking remains a future enhancement.

### ~~[CRITICAL] Non-skill messages silently excluded from emitter coverage~~ ✅ FIXED
Messages with no `skill_id` in context are now attributed to the `"__core__"` bucket in `record_session()`. Source: `ovoscope/bus_coverage.py:510`.

### ~~[MAJOR] Unused `skill_map` variable in `record_session()`~~ ✅ FIXED
Dead `skill_map = self._skill_instance_map()` call removed from `record_session()`.

### ~~[MAJOR] `_get_bus_events()` called three times in `snapshot_listeners()`~~ ✅ FIXED
`bus_events = self._get_bus_events()` is now called once and reused across all three passes. Source: `ovoscope/bus_coverage.py:432`.

### ~~[MAJOR] Double-stop risk in `cmd_bus_coverage()`~~ ✅ FIXED
`test.managed = False` is now set explicitly before `test.execute()`. The `finally` block is the sole owner of `mc.stop()`. The redundant `mc.stop()` in the `except Exception` branch was also removed. Source: `ovoscope/cli.py:349`.

### ~~[MAJOR] `pytest_terminal_summary` hook uses private pytest internals~~ ✅ FIXED
`bus_coverage_session` fixture now stores merged reports on `request.config._bus_coverage_reports` in its teardown. `pytest_terminal_summary` reads that list — no private attrs. Source: `ovoscope/pytest_plugin.py:191`.

### [MAJOR] `once()` handlers invisible after firing
**Evidence**: `bus_coverage.py:368` — one-shot handlers fired during skill loading are de-registered before the snapshot.
**Status**: Documented in `docs/bus-coverage.md` Limitations. Pre-READY tracking is a future enhancement.

### [MAJOR] `ignore_messages` list silently excludes messages from emitter coverage
**Evidence**: `ovoscope/__init__.py:504-505` — messages in `ignore_messages` never reach `responses`.
**Status**: Documented in `docs/bus-coverage.md` Limitations. Passing ignored messages as a separate bucket is a future enhancement.

### ~~[MAJOR] No JSON schema version field~~ ✅ FIXED
`to_json()` now includes `"schema_version": "1"` as the first key. Source: `ovoscope/bus_coverage.py:297`.

### ~~[MINOR] Column widths hardcoded in `print_report()`~~ ✅ FIXED
`col_w = max(len(s.skill_id) for s in self.skills) + 2` now drives column width dynamically. Source: `ovoscope/bus_coverage.py:237`.

### ~~[MINOR] Coverage summary printed before test assertions~~ ✅ FIXED
`print_bus_coverage` block moved to after all assertions, just before `managed` teardown. Source: `ovoscope/__init__.py:795`.

### ~~[MINOR] `bus_coverage_report` type hint uses `Optional[Any]`~~ ✅ FIXED
Type hint changed to `Optional["BusCoverageReport"]`. Source: `ovoscope/__init__.py:589`.

### ~~[NITPICK] `_SKIP` set has fragile `"type"` entry~~ ✅ FIXED
Pass 2 now uses `isinstance(owner, type)` check to skip class objects, and the `"type"` string entry removed from `_SKIP`. Source: `ovoscope/bus_coverage.py:450`.

### ~~Docs gaps (bus-coverage.md)~~ ✅ FIXED
All five missing Limitations items added to `docs/bus-coverage.md`:
- Registration-time handlers always show NOT TESTED
- Pipeline matching is not bus-driven
- `async_responses` now included (fix note)
- `ignore_messages` types excluded
- Core services use `__core__` bucket (not 0/0 — fix note)
