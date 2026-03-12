# Maintenance Report — `ovoscope`

## [2026-03-12] — Full Audit Improvements (Correctness, Coverage, Docs, Packaging)

- **AI Model**: claude-sonnet-4-6
- **Actions Taken**:
  - **P1.1** Fixed `pipeline.py` race condition: split success/failure into
    separate `threading.Event` objects; `match()` now returns `None` on timeout
    or failure instead of returning a failure message as success.
    Source: `ovoscope/pipeline.py:149–200`.
  - **P1.2** Added `strict: bool = False` to `diff.py` `_dict_diff()` and
    `diff_fixtures()`.  When `strict=True`, extra keys in `actual` not in
    `expected` are flagged.  Default `False` preserves existing behaviour.
    Source: `ovoscope/diff.py:121`.
  - **P1.3** Deleted dead `_skill_id_for_handler()` from `bus_coverage.py`
    (lines 745–763, never called anywhere in the codebase).
  - **P2.1** Created `test/unittests/test_media.py` — 20 unit tests for
    `MockOCPBackend` state transitions and `OCPCaptureSession` accumulation.
  - **P2.2** Created `test/unittests/test_remote_recorder.py` — 15 unit tests
    for `RemoteRecorder` using mocked `MessageBusClient`.
  - **P2.3** Fixed deprecated `ovos_utils.messagebus.Message` import in
    `test/unittests/test_phal.py` → `ovos_bus_client.message.Message`.
  - **P3.1** Created `SUGGESTIONS.md` with 10 structured proposals.
  - **P3.2** Updated `QUICK_FACTS.md` test count: 243 → 306.
  - **P3.3** Expanded `docs/pipeline.md` to full API reference with `pipeline.py:LINE`
    citations, `_SinkSkill` explanation, Adapt/Padatious examples, and
    pipeline success/failure signal documentation.
  - **P3.4** Fixed `docs/ocp.md` to correctly reference `OCPTest` (the class
    in `ocp.py`) and add cross-reference to `OCPPlayerHarness` in `media.py`.
  - **P3.5** Updated `AUDIT.md` with 7 new findings (5 fixed, 2 pre-existing).
  - **P4.1** Updated `pyproject.toml`: added Documentation and Issue Tracker
    URLs, `[tool.setuptools.package-data]`, `timeout = 60` in pytest options,
    and comment explaining the `ovos-core>=2.0.4a2` alpha pin.
  - **P5.1** Made `_count_fixtures()` in `coverage.py` use `Path.rglob("*.json")`
    for recursive fixture counting instead of `os.listdir()`.
  - **P5.2** Added `TYPE_CHECKING` guard and proper `List["BusCoverageReport"]`
    type annotation to `BusCoverageCollector._reports` in `pytest_plugin.py`.
- **Oversight**: Human review pending. 348 unit tests pass locally (was 301; +35 new, +12 from new files).

---

## [2026-03-12] — Bus Coverage Report Feature

- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**:
  - Created `ovoscope/bus_coverage.py` — `BusCoverageTracker`, `BusCoverageReport`, `SkillBusCoverage`, `HandlerEntry`, `EmitterEntry` dataclasses.  Tracks listener invocations (via `bus.emit` monkey-patch) and emitter observed/asserted counts per skill_id.  Handler attribution via `handler.__self__` → `minicroft.plugin_skills`.  Handles pyee v9 `OrderedDict` storage format.
  - Modified `ovoscope/__init__.py`: added `track_bus_coverage`, `print_bus_coverage`, `bus_coverage_report` fields to `End2EndTest`; hooked `BusCoverageTracker` into `execute()` around the capture block.
  - Modified `ovoscope/pytest_plugin.py`: added `BusCoverageCollector`, `bus_coverage_session` session fixture, `pytest_terminal_summary` hook for merged end-of-session report.
  - Modified `ovoscope/cli.py`: added `cmd_bus_coverage` subcommand and `bus-coverage` parser entry.
  - Created `docs/bus-coverage.md` — full API reference with source citations.
  - Updated `FAQ.md` with three new Q&A entries.
  - Created `test/unittests/test_bus_coverage.py` — 32 unit tests, all passing.
- **Oversight**: 301 unit tests pass locally.  `bus_coverage.py` at 97% coverage.


## [2026-03-11] — Add ovoscope-setup entrypoint for AI assistant skill installation

- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**:
  - Created `ovoscope/setup_skill.py` — `ovoscope-setup` CLI with install/uninstall for Claude, Gemini, OpenCode; auto-detect mode; `--list`, `--path`, `--uninstall` flags.
  - Created `ovoscope/skill_data/` package with bundled skill definitions:
    - `claude/SKILL.md` + `claude/scripts/ovoscope.sh` + `claude/assets/docs/` + `claude/assets/FAQ.md|QUICK_FACTS.md`
    - `gemini/` — identical structure (Gemini uses same SKILL.md format, project-level install)
    - `opencode/ovoscope.md` — YAML frontmatter agent definition for OpenCode
  - Updated `pyproject.toml`: added `ovoscope-setup` script entrypoint, `[tool.setuptools.packages.find]`, and `[tool.setuptools.package-data]` to bundle `skill_data/`.
  - Added 26 unit tests in `test/unittests/test_setup_skill.py` — all passing.
- **Oversight**: 269 unit tests pass locally.

## [2026-03-11] — Docs Gap Review and Fixes

- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**:
  - `docs/ocp.md`: Documented `execute()` return type (`List[Message]`), clarified `patch_targets` format (dotted Python path where symbol is used), added aiohttp example.
  - `docs/pipeline.md`: Documented `assert_matches(intent_type=...)` as substring check with example; added `ovoscope/pipeline.py:LINE` citations to all methods.
  - `docs/cli.md`: Corrected `--ignore-context` → `--include-context`, explained when/why to use it; clarified `validate` pydantic fallback trigger.
  - `docs/end2end-test.md`, `docs/minicroft.md`, `docs/capture-session.md`: Added `ovoscope/__init__.py:LINE` source citations to class and key method definitions.
  - `docs/capture-session.md`: Documented `finish()` idempotency.
  - `docs/listener.md`: Added full VAD/WakeWord API section (`MockVADEngine`, `MockHotWordEngine`, `is_silence`, `extract_speech`, `detect_wakeword`, `scan_for_wakeword`, `VADTest`, `WakeWordTest`) with examples and `ovoscope/listener.py:LINE` citations. Updated constructor parameter table. Fixed stale line references.
  - `docs/index.md`: Added `gui-testing.md` link; updated Public API section with `GUICaptureSession`, VAD/WW helpers; fixed "Does NOT Do" section for VAD/WW.
  - `QUICK_FACTS.md`: Added entry-point groups table; updated test count (243) and coverage note.
- **Oversight**: No new code changes — docs only.

## [2026-03-11] — Add VAD and WakeWord Support to MiniListener

- **AI Model**: Claude Haiku 4.5
- **Actions Taken**:
  - Extended `ovoscope/listener.py` with `MockVADEngine`, `MockHotWordEngine`, `VADTest`, `WakeWordTest`.
  - Extended `MiniListener` with `vad_instance` / `ww_instances` constructor params.
  - Added `is_silence()`, `extract_speech()`, `detect_wakeword()`, `scan_for_wakeword()` methods to `MiniListener` — `listener.py:466–600`.
  - Extended `get_mini_listener()` factory with `vad_plugin`, `vad_instance`, `ww_plugin`, `ww_instances` params.
  - Made `ovos_dinkum_listener` import lazy (graceful `ImportError`) so VAD/WW tests work without the full listener stack installed.
  - Added 41 unit tests in `test/unittests/test_listener_vad_ww.py`.
  - Updated `FAQ.md` with VAD and WakeWord testing Q&A.
- **Oversight**: 243 unit tests pass locally.

## [2026-03-11] — Enhance Audio Testing Robustness and CI

- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**:
  - Added `LIGHT_TEST_PIPELINE` as a lightweight fallback when Adapt/Padatious are missing.
  - Updated `MiniCroft` to auto-fallback to `LIGHT_TEST_PIPELINE` if stages are missing.
  - Refactored `PlaybackServiceHarness` for better robustness (proper patch cleanup, timeout handling).
  - Added skip guard to audio harness tests to prevent failures when `ovos-audio` is not installed.
  - Fixed documentation path references and added prerequisites.
  - Added missing `LICENSE` (Apache-2.0) file.
  - Updated CI workflows to include `audio` extra for unit tests.
- **Oversight**: All 147 unit tests pass locally.

## [2026-03-10] — Add Audio Testing Harnesses

- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**:
  - Created `ovoscope/audio.py` — 5 new classes:
    - `MockAudioBackend` (inherits `AudioBackend`) — no-op backend tracking state
    - `AudioServiceHarness` — context manager wrapping `AudioService` with `MockAudioBackend`
    - `MockTTS` (inherits `TTS`) — writes 44-byte silent WAV, records spoken utterances
    - `PlaybackServiceHarness` — context manager wrapping `PlaybackService` with `MockTTS`
    - `AudioCaptureSession` — records bus messages matching configurable prefix list
  - Updated `ovoscope/__init__.py` — guarded import of audio harness classes
  - Updated `pyproject.toml` — added `[audio]` optional dependency
  - Created `test/unittests/test_audio_harness.py` — 38 unit tests (all passing)
  - Created `ovos-audio/test/end2end/__init__.py` — empty marker
  - Created `ovos-audio/test/end2end/test_audio_service_e2e.py` — 11 E2E tests (all passing)
  - Created `ovos-audio/test/end2end/test_playback_service_e2e.py` — 7 E2E tests (all passing)
  - Created `docs/audio-testing.md` — full API reference with source citations
  - Updated `docs/index.md` — link to audio-testing.md
  - Updated `FAQ.md` — 3 new Q&As for audio testing
  - Updated `QUICK_FACTS.md` — new audio harness classes, updated test count
- **Key design decisions**:
  - `AudioServiceHarness` uses `autoload=False` then manually injects `MockAudioBackend`
  - `PlaybackServiceHarness` patches `ovos_audio.playback.play_audio` to prevent real audio
  - `TTS.queue` is class-level; harness drains it before each `PlaybackService` construction
  - `stop()` MUST return `True` to trigger `mycroft.stop.handled` in `AudioService`
  - `FakeBus.wait_for_response()` does not work in-process; subscribe-emit-wait pattern used
- **Oversight**: All 38 ovoscope unit tests + 18 ovos-audio E2E tests pass

## [2026-03-10] — Add `pipeline_config` parameter to `MiniCroft`
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**:
  - Added `pipeline_config: Optional[Dict[str, Dict]] = None` parameter to `MiniCroft.__init__` — `ovoscope/__init__.py`
  - Patches `Configuration()["intents"][plugin_key]` before `super().__init__()` so pipeline plugins read overridden config in their own `__init__`
  - Restores all overrides in `MiniCroft.stop()` — `ovoscope/__init__.py`
  - Updated `docs/minicroft.md`: added `pipeline_config` to constructor table and added "Pipeline Plugin Config Overrides" section with usage example
  - Updated `FAQ.md`: added Q&A for `pipeline_config` and M2V multilingual model skip behaviour
  - Added 5 unit tests in `test/unittests/test_minicroft.py::TestMiniCroftPipelineConfig`: patch active, restore after stop, existing key preserved, None is no-op, multiple keys
- **Oversight**: 18/18 minicroft unit tests pass; confucius e2e suite: 20 passed, 2 skipped.
- **Motivation**: Needed to force the M2V multilingual model in `TestConfuciusM2VEN` regardless of what `mycroft.conf` says locally. Language-specific models (e.g. Portuguese) don't contain English intent labels and always return no match.
- **Oversight**: All ovoscope unit tests pass; confucius e2e suite: 20 passed, 2 skipped (M2V — multilingual model not cached locally).

## [2026-03-10] — Test coverage improvement (78% → 89%)
### Changes
- Created `test/unittests/test_end2end_extended.py` — 46 new tests covering:
  - **Routing internals**: flip_points, entry_points, keep_original_src assertions
  - **Active skills**: inject_active, activation_points, deactivation_points, disallow_extra_active_skills
  - **Boot sequence**: correct/incorrect boot message assertions
  - **Final session**: lang mismatch raises, matching session passes
  - **Async messages**: captured separately, missing raises, count mismatch raises
  - **Context assertions**: wrong context raises
  - **GUI filtering**: ignore_gui=True/False behavior
  - **Serialization**: JSON string input, flip_points/flags preservation, anonymize_message
  - **from_message recording**: captures sequence, wraps single message
  - **Pipeline constants**: composition validation
  - **MiniCroft lang config**: override and restore
  - **Verbose output**: exercises all print branches
  - **Message count verbose**: first differing message output
- Created `test/unittests/test_pytest_plugin.py` — 6 new tests for minicroft fixture logic via `__wrapped__`
- Updated `FAQ.md` — added coverage FAQ entry
### AI Transparency Report
- **AI Model**: Claude Opus 4.6
- **Actions Taken**: Created 2 new test files with 52 total new tests
- **Oversight**: All tests verified passing. Coverage: 78% → 89% overall, `__init__.py` 54% → 68%, `pytest_plugin.py` 0% → 64%
---
## [2026-03-09] — CI workflows and test-gated releases
### Changes
- Created `.github/workflows/unit_tests.yml` — runs 58 unit tests with `pytest --cov=ovoscope` on PRs/pushes to `dev`, posts coverage comment via `py-cov-action/python-coverage-comment-action@v3`
- Created `.github/workflows/build_tests.yml` — matrix build (Python 3.10, 3.11) with `python -m build`, tests sdist/wheel creation and package install
- Created `.github/workflows/license_tests.yml` — calls `OpenVoiceOS/gh-automations/.github/workflows/license-check.yml@dev` reusable workflow
- Created `.github/workflows/pipaudit.yml` — CVE scanning via `pypa/gh-action-pip-audit@v1.0.0` on Python 3.10/3.11 matrix
- Updated `.github/workflows/release_workflow.yml` — added `build_tests` job that runs full test suite; `publish_alpha` now depends on `build_tests` via `needs:`, gating alpha releases on test success
- Updated `docs/ci-integration.md` — documented ovoscope's own CI workflow table
- Updated `FAQ.md` — added 3 new CI-related Q&A entries
### AI Transparency Report
- **AI Model**: Claude Opus 4.6
- **Actions Taken**: Created 4 new workflow files, updated 1 existing workflow, updated docs and FAQ
- **Oversight**: All workflows follow established OVOS conventions (actions/checkout@v4, actions/setup-python@v5, python-version 3.11, python -m build). 58 existing tests verified passing.
---
## [2026-03-09] — pytest_plugin: safe teardown guard
### Changes
- `ovoscope/pytest_plugin.py` — `minicroft` fixture: initialise `mc = None` before calling
  `get_minicroft()`, then wrap `yield mc` in `try/finally` with `if mc is not None: mc.stop()`.
  Previously, if `get_minicroft()` raised (e.g. `TimeoutError`), teardown would hit a
  `NameError: name 'mc' is not defined`, masking the original exception in pytest output.
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Applied targeted edit to `pytest_plugin.py` lines 57–62.
- **Oversight**: No logic change — only teardown safety. Existing tests unaffected.
---
## [2026-03-09] — pydantic_helpers: typing, docstrings, tests, bug fix, pyproject.toml migration
### Changes
**`ovoscope/pydantic_helpers.py`** (new module, renamed from the initial `pydantic.py`):
- Full module docstring with install instructions and usage example.
- `TYPE_CHECKING`-guarded import of `OpenVoiceOSMessage` — type checkers see full annotations;
  no `ImportError` at runtime when `ovos-pydantic-models` is absent.
- All three public functions have complete Google-style docstrings with `Args`, `Returns`,
  `Raises`, and `Example` blocks; all parameter and return types are annotated.
- **Bug fixed** in `validate_fixture()`: was constructing `raise ValidationError(str, ...)` which
  pydantic v2 does not support (it is not user-constructible). Changed to `raise ValueError(...) from exc`.
- **Bug fixed** in `validate_fixture()`: normalisation fallback changed from `""` to `None` so
  messages missing both `"type"` and `"message_type"` keys are correctly rejected by pydantic
  (an empty string passes `message_type: str = Field(...)` validation silently).
**`test/unittests/test_pydantic_helpers.py`** (new, 20 tests):
| Class | Tests | What is covered |
|-------|-------|----------------|
| `TestToBusMessage` | 6 | `msg_type`, data fields, return type, utterance msg, empty context, roundtrip |
| `TestFromBusMessage` | 5 | valid speak, valid utterance, return type, invalid raises `ValidationError`, base model leniency |
| `TestValidateFixture` | 9 | valid fixture, source/expected preserved, missing file, malformed source, malformed expected, error chains `ValidationError`, `message_type` key accepted, empty lists |
All 20 tests pass. Full suite now 58 tests (38 pre-existing + 20 new), all passing.
**`pyproject.toml`** — completed migration:
- `build-backend` changed from `setuptools.backends.legacy:build` to `setuptools.build_meta`.
- `dynamic = ["version"]` added; `[tool.setuptools.dynamic] version = {attr = "ovoscope.version.__version__"}`.
- `[project.optional-dependencies] pydantic = ["ovos-pydantic-models>=0.1.0"]` added.
- `setup.py` removed.
**`ovoscope/version.py`**:
- Added `__version__` computed from `VERSION_MAJOR`, `VERSION_MINOR`, `VERSION_BUILD`, `VERSION_ALPHA`
  so `pyproject.toml` dynamic versioning works without `setup.py`.
**`AUDIT.md`**, **`SUGGESTIONS.md`**, **`FAQ.md`**:
- All module references updated from `ovoscope.pydantic` → `ovoscope.pydantic_helpers`.
- AUDIT unit-test count updated to 58; setup.py fix marked fully complete.
- SUGGESTIONS.md item 6 file path corrected.
- FAQ.md pydantic section import paths corrected.
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Read existing module and all test files; identified two bugs in `validate_fixture()`
  via live `python -c` verification; wrote 20 tests and iterated until all pass; migrated pyproject.toml.
- **Oversight**: `validate_fixture()` validates top-level message structure only (`message_type`,
  `data`, `context` shape) via `OpenVoiceOSMessage` — it does not validate data-field-level schemas
  (e.g. `utterances` type). Use `from_bus_message(msg, SpecificModel)` for field-level validation.
---
## [2026-03-09] — End2end tests written for ovos-persona (11 tests)
### Tests Created
New `ovos-persona/test/end2end/test_persona.py` — 4 test classes, 11 tests:
| Class | Tests | Intents/triggers |
|-------|-------|-----------------|
| `TestPersonaList` | 2 | `list_personas.intent` (no personas / 2 personas) |
| `TestPersonaCheck` | 2 | `active_persona.intent` (no active / active) |
| `TestPersonaSummon` | 2 | `summon.intent` (known / unknown persona) |
| `TestPersonaRelease` | 1 | `Release.voc` via `voc_match()` |
| `TestPersonaQuery` | 4 | `ask.intent` explicit / active fallback / error / no-match |
### Key Patterns Discovered
- Pipeline plugins accessed via `mc.intents.pipeline_plugins["ovos-persona-pipeline-plugin"]`
- Inject mock personas into `persona_svc.personas` dict — bypasses real solver loading
- `setUp()` clears real personas (Gemma etc.) and resets `active_persona = None`
- `skill_ids=[]` — no skills needed; pipeline plugin loads automatically
- `ovos.utterance.handled` data is `{"name": "PersonaService.handle_persona_*"}` — not empty
- `speak` with dialog template checked only by `context={"skill_id": SKILL_ID}` (text varies)
- Direct speaks from query answers checked with `data={"utterance": "forty two"}`
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Traced all message sequences via live FakeBus capture; wrote tests iteratively; all 11 pass.
- **Oversight**: Dialog text assertions omitted — locale-dependent. `test_list_two_personas` relies on dict insertion order (Python 3.7+).
---
## [2026-03-09] — End2end tests written for 6 skills (18 tests)
### Skills Covered
New `test/end2end/` directories and test files created for:
| Skill | Test file | Tests | Intents tested |
|-------|-----------|-------|----------------|
| `ovos-skill-hello-world` | `test_hello_world.py` | 4 | HelloWorldIntent (Adapt), Greetings.intent (Padatious), no-match cases |
| `ovos-skill-fallback-unknown` | `test_fallback_unknown.py` | 2 | fallback-low match, Adapt no-match |
| `ovos-skill-naptime` | `test_naptime.py` | 2 | naptime.intent (Padatious), no-match |
| `ovos-skill-volume` | `test_volume.py` | 4 | volume.max.intent, volume.mute.intent, volume.unmute.intent (Padatious), no-match |
| `ovos-skill-count` | `test_count.py` | 3 | count_to_N.intent (Padatious), no-match |
| `ovos-skill-parrot` | `test_parrot.py` | 3 | speak.intent, repeat.tts.intent, no-match |
### Key Patterns Discovered
- Intents registered with string `"name.intent"` → Padatious; `IntentBuilder(...)` → Adapt
- Skills emitting raw `Message(...)` without `forward(...)`/`reply()` have `source=None` — use `async_messages` + `ignore_messages`
- Enclosure/LED messages and `add_context`/`configuration.patch` must be in `ignore_messages`
- `message.forward(...)` inherits the post-flip source/dest — do NOT add these to `keep_original_src`
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Read each skill's `__init__.py` and locale files; wrote tests iteratively with test runs to fix pipeline selection, ignore_messages, meta dict content. All 18 tests pass.
- **Oversight**: naptime test skips dialog content check (varies with `listener.wake_word` config).
---
## [2026-03-09] — Config isolation extended: blacklisted_skills + blacklisted_intents
### Problem Addressed
After pipeline isolation, `test_stop.py` (6 tests) and `test_cancel_plugin.py` (1 test) still failed.
Root cause: `Session.__init__` reads `Configuration()["skills"]["blacklisted_skills"]` and
`Configuration()["intents"]["blacklisted_intents"]` from the live singleton dict cache, same problem
as the pipeline. The user had `skill-ovos-stop.openvoiceos` blacklisted in `~/.config/mycroft/mycroft.conf`.
Additionally, `ovos-skill-count` and `ovos-utterance-plugin-cancel` were not installed in the workspace venv.
### Changes
- `ovoscope/__init__.py` — `MiniCroft.__init__`: added `_original_blacklisted_skills` and
  `_original_blacklisted_intents` state variables.
- `ovoscope/__init__.py` — `MiniCroft.run()`: when `isolate_config=True`, patches
  `Configuration()["skills"]["blacklisted_skills"] = []` and
  `Configuration()["intents"]["blacklisted_intents"] = []` in the live singleton dict cache.
- `ovoscope/__init__.py` — `MiniCroft.stop()`: restores both lists from saved originals.
- `ovos-core/test/end2end/test_stop.py` — Added `"ovos-hivemind-pipeline-plugin.stop.response"` to
  `ignore_messages` in both `TestStopNoSkills` and `TestCountSkills` (hivemind responds to `mycroft.stop`).
- Installed `Skills/ovos-skill-count` and `Transformer plugins/ovos-utterance-plugin-cancel` with `uv pip install --no-deps -e`.
### Result
27/27 ovos-core end2end tests pass (was 20/27).
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Diagnosed `blacklisted_skills` stale cache issue; extended `run()`/`stop()` patch pattern;
  identified hivemind stop response as uncaught message; installed missing plugins.
- **Oversight**: `blacklisted_skills` patch only runs when `isolate_config=True` (same condition as xdg isolation).
---
## [2026-03-09] — Pipeline isolation and reproducible test pipelines
### Problem Addressed
`MiniCroft.isolate_config=True` cleared `Configuration.xdg_configs` to remove the user's
`~/.config/mycroft/mycroft.conf`, but `SessionManager.default_session` is a singleton
initialised at module import time — it already held the user's pipeline (which could include
`ovos-persona-pipeline-plugin-high`, Ollama, OCP, etc.).  Any utterance emitted without an
explicit session in its context would inherit this pipeline and be intercepted by AI plugins
non-deterministically, making tests environment-dependent.
### Changes
- `ovoscope/__init__.py` — Added pipeline stage constants:
  `STOP_PIPELINE`, `CONVERSE_PIPELINE`, `ADAPT_PIPELINE`, `PADATIOUS_PIPELINE`,
  `FALLBACK_PIPELINE`, `COMMON_QUERY_PIPELINE`, `PERSONA_PIPELINE`.
- `ovoscope/__init__.py` — Added `DEFAULT_TEST_PIPELINE`: all standard built-in pipeline stages
  (stop/converse/adapt/padatious/fallback/common-query), **no** AI/LLM/persona/OCP stages.
- `ovoscope/__init__.py` — `MiniCroft.__init__`: added `default_pipeline: Optional[List[str]]`
  parameter (default `DEFAULT_TEST_PIPELINE`).  Stored as `_default_pipeline`; original
  pipeline stored for restoration.
- `ovoscope/__init__.py` — `MiniCroft.run()`: after `load_plugin_skills()` and before
  `set_ready()`, sets `SessionManager.default_session.pipeline = self._default_pipeline` when
  not `None`.  Setting it here (post-FakeBus-sync) is the correct point — after all init bus
  messages have been processed.
- `ovoscope/__init__.py` — `MiniCroft.stop()`: restores `SessionManager.default_session.pipeline`
  to its pre-test value, enabling test isolation within a single process.
- `test/unittests/test_minicroft.py` — Added `TestMiniCroftPipelineIsolation` (5 tests):
  pipeline overrides default session, restored after stop, `isolate_config=True` uses
  `DEFAULT_TEST_PIPELINE`, persona/ollama/m2v absent from `DEFAULT_TEST_PIPELINE`,
  `default_pipeline=None` leaves session unchanged.
### Use Cases Unblocked
- `get_minicroft([])` → `complete_intent_failure` tests now pass without Gemma/persona intercepting.
- `get_minicroft([SKILL_ID], default_pipeline=ADAPT_PIPELINE)` — Adapt-only testing.
- `get_minicroft([SKILL_ID], default_pipeline=ADAPT_PIPELINE + FALLBACK_PIPELINE)` — intent+fallback.
- `get_minicroft([SKILL_ID], default_pipeline=PERSONA_PIPELINE)` — explicitly test persona behaviour.
- `get_minicroft([SKILL_ID], default_pipeline=None)` — use system default (includes all installed plugins).
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Diagnosed root cause (singleton default_session pre-initialised from user config);
  added constants + `default_pipeline` param; updated `run()` and `stop()`; added 5 unit tests.
- **Oversight**: `DEFAULT_TEST_PIPELINE` does not include OCP or m2v stages — repos that test
  media skills should pass an explicit pipeline including those stages.
---
## [2026-03-08] — Code improvements from SUGGESTIONS.md
### Changes
- `ovoscope/__init__.py` — `get_minicroft()`: added `max_wait: float = 60` parameter; raises
  `TimeoutError` if MiniCroft does not reach READY within the deadline. Return type annotated
  as `-> MiniCroft`.
- `ovoscope/__init__.py` — `MiniCroft.inject_message(msg: Message) -> None`: new helper method
  for emitting arbitrary messages during a test without going through the utterance pipeline.
- `ovoscope/__init__.py` — `End2EndTest.execute()`: now returns `List[Message]` (was `None`).
  Return type annotated. Enables test composition and `assert_spoke()`.
- `ovoscope/__init__.py` — `End2EndTest.assert_spoke(text, lang, timeout)`: new sugar method;
  calls `execute()` and asserts a matching `speak` message was emitted.
- `ovoscope/__init__.py` — `End2EndTest.save()`: return type annotated as `-> None`.
- `ovoscope/pytest_plugin.py` (NEW): class-scoped `minicroft` pytest fixture; reads `skill_ids`
  from the test class attribute; handles startup and teardown automatically.
- `setup.py`: registered `pytest11` entry point so the fixture is auto-discovered.
- `pyproject.toml` (NEW): `[build-system]`, `[project]`, `[project.entry-points."pytest11"]`,
  and `[tool.pytest.ini_options]` tables. `setup.py` retained for dynamic version reading.
- `AUDIT.md`: marked 3 issues as FIXED; updated Next Steps.
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Read `__init__.py` fully; made targeted edits; created `pytest_plugin.py`
  and `pyproject.toml`. No logic was changed — only additions and the `return messages` fix.
- **Oversight**: `assert_spoke()` depends on `execute()` returning messages — verify against
  a live install. `pyproject.toml` dynamic version section has a TODO comment for when
  `version.py` exports `__version__`.
---
## [2026-03-08] — Documentation enrichment and audit deepening
### Changes
- Created `docs/usage-guide.md` — full tutorial from install to 8 test patterns; references
  hello-world canonical examples and real class/method signatures from `ovoscope/__init__.py`.
- Created `docs/ci-integration.md` — directory layout, pytest config, GitHub Actions job
  template, fixture management, and CI gotchas.
- Updated `docs/index.md` — added `usage-guide.md` and `ci-integration.md` to navigation table;
  added "Who Uses ovoscope" section; added gh-automations cross-reference.
- Replaced `AUDIT.md` — shallow CI-pin findings replaced with 7 evidence-based issues
  (CRITICAL/MAJOR/MODERATE/MINOR) all traced to specific lines in `__init__.py`.
- Replaced `SUGGESTIONS.md` — 4 generic stubs replaced with 7 concrete, repo-specific proposals
  with code snippets pointing to specific lines.
### Rationale
The previous docs scaffold was boilerplate with no practical value. This pass enriches docs to the
level where every OVOS repo can adopt ovoscope end-to-end testing without reading source code.
### Verification
- `ls ovoscope/docs/` shows 7 files (5 pre-existing + `usage-guide.md` + `ci-integration.md`).
- All code examples in `usage-guide.md` use real imports and class names verified from source.
- All `AUDIT.md` findings reference specific file:line evidence.
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Read `ovoscope/__init__.py` (485 lines), `test/test_helloworld.py`,
  `ovos-core/test/end2end/test_adapt.py`, and all existing docs; then generated enriched content.
- **Oversight**: Code examples are illustrative but not executed. Verify against live skill install before treating as runnable.

---

## 2026-03-11 — Phase 1–3 Feature Additions

**AI Model**: claude-sonnet-4-6
**Oversight**: Human review pending

### Actions Taken

Added CLI, PHAL harness, fixture differ, OCP harness, pipeline harness,
ecosystem coverage scanner, GUI capture session, and remote recorder.

**New modules:**
- `ovoscope/cli.py` — `ovoscope` CLI with `record`, `run`, `diff`, `validate`, `coverage`
- `ovoscope/diff.py` — `MessageDiff`, `FixtureDiffResult`, `diff_fixtures`
- `ovoscope/phal.py` — `MiniPHAL`, `PHALTest`
- `ovoscope/ocp.py` — `OCPTest`, `assert_ocp_query_response`
- `ovoscope/pipeline.py` — `PipelineHarness`
- `ovoscope/coverage.py` — `RepoCoverage`, `EcosystemCoverageReport`, `scan_workspace`
- `ovoscope/remote_recorder.py` — `RemoteRecorder`

**Extended modules:**
- `ovoscope/__init__.py` — added `GUICaptureSession`

**New docs:**
- `docs/cli.md`, `docs/phal.md`, `docs/ocp.md`, `docs/pipeline.md`
- `docs/usage-guide.md` — Patterns 9–12 appended

**New tests:**
- `test/unittests/test_diff.py` — 7 test methods
- `test/unittests/test_phal.py` — 8 test methods
- `test/unittests/test_coverage.py` — 11 test methods
- `test/unittests/test_cli.py` — 14 test methods

**pyproject.toml changes:**
- Added `[project.scripts] ovoscope = "ovoscope.cli:main"`

All 202 tests pass. No regressions introduced.

---

## [2026-03-08] — Initial compliance scaffold
### Changes
- Created `QUICK_FACTS.md` with machine-readable package metadata.
- Created `FAQ.md` with common Q&A.
- Created `MAINTENANCE_REPORT.md` (this file) as the change log.
- Created `SUGGESTIONS.md` with initial improvement proposals.
- Created `docs/index.md` as the documentation entry point (if missing).
### Rationale
Establishing the required file set mandated by `AGENTS.md` for all active workspace repositories.
### AI Transparency Report
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**: Generated boilerplate compliance scaffold (QUICK_FACTS, FAQ, MAINTENANCE_REPORT, SUGGESTIONS, docs/index).
- **Oversight**: Files were stubs — enriched in the 2026-03-08 documentation pass above.
