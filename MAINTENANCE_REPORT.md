Last Edit: Claude Opus 4.6 - 2026-03-10 - Motive: Improved test coverage from 78% to 89% (58 → 104 tests), added routing/active skills/session/recording tests.

# Maintenance Report — `ovoscope`

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
- Created `.github/workflows/license_tests.yml` — calls `OpenVoiceOS/gh-automations/.github/workflows/license-check.yml@master` reusable workflow
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
- Skills emitting raw `Message(...)` without `forward()`/`reply()` have `source=None` — use `async_messages` + `ignore_messages`
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
