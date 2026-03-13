# Suggestions — `ovoscope`

Agent-generated proposals for refactors and enhancements.
Each item includes a rationale, affected file, and implementation sketch.

---

## 1. Share MiniCroft Across Fixtures in `cmd_bus_coverage()` [PERFORMANCE]

**File**: `ovoscope/cli.py` — `cmd_bus_coverage()`

**Problem**: The current implementation creates a new `MiniCroft` for every
fixture file it runs.  When a workspace has many fixtures for the same skill,
this means repeated skill loading, plugin initialisation, and READY-wait
overhead for each fixture — typically 5–20 seconds per fixture.

**Suggestion**: Group fixture files by their `skill_ids` list, create a single
`MiniCroft` per unique skill set, then replay all fixtures against that shared
instance.  Expected speedup: 10–50× for typical skill test suites.

**Sketch**:
```python
from itertools import groupby
fixtures_by_skills = groupby(sorted(fixtures, key=lambda f: f.skill_ids_key), ...)
for skill_key, group in fixtures_by_skills:
    mc = get_minicroft(skill_key)
    for fixture in group:
        fixture.execute(minicroft=mc)
    mc.stop()
```

---

## 2. Add `PipelineHarness.assert_no_match()` Convenience Method [DONE]

**File**: `ovoscope/pipeline.py`

**Status**: Already implemented — `assert_no_match(utterance, timeout=2.0)` is
present at `pipeline.py:213`.  No further action needed.

---

## 3. Add `LOAD_TIME` Tag for Registration-Time Handlers [BUS COVERAGE]

**File**: `ovoscope/bus_coverage.py`

**Problem**: Handlers invoked during skill loading (before the snapshot) always
show `0 invocations` and `NOT TESTED` in bus coverage reports.  This is
misleading because intent registration handlers *are* exercised — just before
the snapshot window.

**Suggestion**: Capture a pre-READY handler snapshot in `MiniCroft.__init__`
(before `super().__init__()`), then tag any handler present in both the
pre-READY and post-READY snapshots with a `LOAD_TIME` label in the report.
These handlers should be excluded from the `NOT TESTED` count.

---

## 4. `diff.py` — Strict Mode for Extra Keys [DONE]

**File**: `ovoscope/diff.py`

**Status**: Implemented in this audit cycle.  `_dict_diff()` now accepts
`strict: bool = False`; when `True`, keys present in `actual` but not in
`expected` are flagged as unexpected extras.  `diff_fixtures()` exposes the
same `strict` parameter.  Default `False` preserves existing behaviour.

---

## 5. Make Coverage Fixture Search Recursive [DONE]

**File**: `ovoscope/coverage.py` — `_count_fixtures()`

**Status**: Implemented in this audit cycle.  The search now uses
`Path.rglob("*.json")` instead of `os.listdir()`, so fixtures in
sub-directories are counted correctly.

---

## 6. Add Noise-Floor Tolerance to `MockVADEngine.is_silence()` [LISTENER]

**File**: `ovoscope/listener.py`

**Problem**: `MockVADEngine.is_silence()` currently returns a fixed value
configured at construction time.  Real VAD engines apply a noise-floor
threshold; tests that simulate borderline audio may need to replicate this
behaviour.

**Suggestion**: Add `noise_floor: float = 0.0` parameter to
`MockVADEngine.__init__()`.  When `noise_floor > 0`, `is_silence()` returns
`True` only if the sample RMS is below `noise_floor`.  Default `0.0`
preserves existing behaviour (fixed return value).

---

## 7. Make OCP HTTP Patch Targets Configurable [OCP]

**File**: `ovoscope/ocp.py`

**Problem**: The default patch targets (`requests.Session.get` and
`requests.get`) are hardcoded in `_apply_patches`.  Skills that use
`httpx`, `aiohttp`, or a custom HTTP wrapper cannot be mocked without
specifying `patch_targets`.

**Suggestion**: Expose `default_patch_targets: List[str]` as a class-level
constant on `OCPTest` so subclasses can override it without rewriting each
test instance:

```python
class OCPTest:
    default_patch_targets: List[str] = ["requests.Session.get", "requests.get"]
```

---

## 8. Support Env Var for GitHub URL in `setup_skill.py` [SETUP]

**File**: `ovoscope/setup_skill.py`

**Problem**: The GitHub URL for skill assets is hardcoded.  CI environments or
forks may need to point to a different repository.

**Suggestion**: Read `OVOSCOPE_SKILL_URL` environment variable as an override:

```python
import os
SKILL_URL = os.environ.get("OVOSCOPE_SKILL_URL", DEFAULT_SKILL_URL)
```

---

## 9. Add `RemoteRecorder` Usage to Docs [DOCUMENTATION]

**File**: `docs/index.md`, `docs/usage-guide.md`

**Problem**: `RemoteRecorder` — `ovoscope/remote_recorder.py:46` — is not
documented in any public-facing doc file.  Users who want to capture fixtures
from a live OVOS instance have no guide.

**Suggestion**: Add a "Pattern 13: Recording from a Live OVOS Instance" section
to `docs/usage-guide.md` showing the `connect()`/`record()`/`disconnect()`
workflow and the `--live` CLI flag.

---

## 10. Expand `docs/pipeline.md` to Full API Reference [DONE]

**File**: `docs/pipeline.md`

**Status**: Expanded in this audit cycle.  The file now includes the full
`PipelineHarness` API table with `pipeline.py:LINE` citations, examples for
Adapt and Padatious pipelines, an explanation of `_SinkSkill`, and notes on
pipeline stage ordering and success/failure signals.
