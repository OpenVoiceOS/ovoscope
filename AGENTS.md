# ovoscope — agent guide

End-to-end test framework for OpenVoiceOS skills: boots a full OVOS Core intent pipeline in-process on a `FakeBus` (no server, no audio stack, no network), emits a test utterance, and asserts on every bus message that comes back.

## Setup
```bash
pip install -e .            # core (pulls ovos-core>=2.0.4a2)
pip install -e .[dev]       # + ovos-audio, ovos-pydantic-models, pytest, pytest-cov
```
Optional extras: `[audio]` (listener/audio/playback harnesses), `[pydantic]` (typed message bridge to `ovos-pydantic-models`).

## Test
```bash
pytest test/unittests/
```
`pyproject.toml` sets `testpaths = ["test"]` and a 60s per-test timeout. CI runs with `install_extras: audio,pydantic`.

## Lint/Typecheck
A `lint.yml` workflow exists (via gh-automations). No local lint/typecheck config in `pyproject.toml`.

## Layout
- `ovoscope/__init__.py` — core API: `MiniCroft` (subclasses `SkillManager`, runs on `FakeBus`), `get_minicroft()`, `CaptureSession`, `End2EndTest`, `GUICaptureSession`, pipeline stage-group constants (`ADAPT_PIPELINE`, `PADATIOUS_PIPELINE`, `PADACIOSO_PIPELINE`, `FALLBACK_PIPELINE`, `PERSONA_PIPELINE`, `M2V_PIPELINE`, `DEFAULT_TEST_PIPELINE`, `LIGHT_TEST_PIPELINE`), `is_pipeline_available()`, and global bus-coverage monkey-patching of `FakeBus`/`OVOSSkill`.
- `ovoscope/pytest_plugin.py` — `minicroft` and `bus_coverage_session` fixtures; registered via the `pytest11` entry point (auto-loaded when installed).
- `ovoscope/cli.py` — `ovoscope` console script: `record`, `run`, `diff`, `validate`, `coverage` subcommands.
- `ovoscope/setup_skill.py` — `ovoscope-setup` console script that installs the ovoscope helper skill into AI coding assistants.
- Specialised harnesses: `listener.py` (MiniListener: STT/VAD/WakeWord), `audio.py` (audio/playback/TTS mocks), `ocp.py` + `media.py` (OCP/media), `phal.py` (PHAL plugins), `pipeline.py` (pipeline plugins).
- `bus_coverage.py` / `coverage.py` — per-test bus-message coverage and workspace-wide E2E coverage scanning.
- `diff.py`, `remote_recorder.py`, `pydantic_helpers.py` — fixture diffing, live-bus fixture recording, typed-model bridge.
- `test/unittests/` — unit tests.

Entry-point groups: `console_scripts` (`ovoscope`, `ovoscope-setup`) and `pytest11` (`ovoscope`). This is a testing tool, not an OPM plugin or skill.

## Conventions (Org hard rules)
- Branches: `dev` for work, `master` for stable. NEVER `main`.
- Never edit `ovoscope/version.py`; gh-automations bumps semver from conventional-commit prefixes (`feat:`/`fix:`/`feat!:`).
- New repos private by default.
- Commit identity: JarbasAI <jarbasai@mailfence.com>.
- Reference `OpenVoiceOS/gh-automations` reusable workflows at `@dev`.
- No Neon / `neon-*` references.
- No meta-commentary (no history, dates, or design-decision narration) in code, docs, commits, or PRs.
- CI is provided by `OpenVoiceOS/gh-automations`.

## Gotchas
- Depends on an alpha pin `ovos-core>=2.0.4a2` (stable 2.0.4 not yet released) for FakeBus-compatible `SkillManager`.
- `MiniCroft` mutates the global `Configuration()` singleton dict cache and `SessionManager.default_session` (pipeline, lang, blacklists) and restores them in `stop()` — always pair construction with `stop()` (or use `get_minicroft`/managed `End2EndTest`). `Configuration.reload()` does not invalidate the live dict cache, so it patches the singleton directly.
- Importing `ovoscope` immediately monkey-patches `FakeBus.on/once/emit` and `OVOSSkill.add_event/bind` for global bus coverage.
- Pipeline auto-selection: with `isolate_config=True` (default) it uses `DEFAULT_TEST_PIPELINE` if Adapt+Padatious are installed, else falls back to `LIGHT_TEST_PIPELINE` (pure-Python, no swig). `DEFAULT_TEST_PIPELINE` deliberately excludes persona/Ollama/OCP/m2v stages.
- `End2EndTest` checks only the keys you list in `expected.data`/`expected.context`; extra keys in received messages are ignored. GUI messages are ignored by default (`ignore_gui=True`).
- `audio` and `listener` submodule imports are guarded: missing optional deps are silenced, but a genuine import error in those modules is re-raised.
