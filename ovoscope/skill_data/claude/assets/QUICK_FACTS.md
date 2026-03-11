# Quick Facts — `ovoscope`
End-to-end test framework for OpenVoiceOS skills
## Core Information
| Feature | Details |
|---------|---------|
| Package Name | `ovoscope` |
| Version | `0.7.2` |
| License | Apache-2.0 |
| Repository | [https://github.com/TigreGotico/ovoscope](https://github.com/TigreGotico/ovoscope) |
| Python Support | >=3.10 |
| Status | Active development |
## Entry Points
| Group | Value | Description |
|-------|-------|-------------|
| `console_scripts` | `ovoscope = ovoscope.cli:main` | CLI entry point |
| `pytest11` | `ovoscope = ovoscope.pytest_plugin` | pytest plugin (auto-loaded by pytest) |

## Testing & CI
| Feature | Details |
|---------|---------|
| Unit Tests | 243 tests across `test/unittests/` (all passing) |
| Coverage | 53% overall (transformer/remote code excluded — requires optional deps) |
| Test Framework | pytest with custom fixtures |
| Coverage Reporter | py-cov-action/python-coverage-comment-action@v3 |
## CI Workflows
| Workflow | Trigger | Status |
|----------|---------|--------|
| `unit_tests.yml` | Push to dev | Uses coverage.yml@dev |
| `build_tests.yml` | Push to master, PR to dev | Uses build-tests.yml@dev |
| `license_check.yml` | Push to master/dev, PR | Uses license-check.yml@dev |
| `pip_audit.yml` | Push to master/dev, PR | Uses pip-audit.yml@dev |
| `release_workflow.yml` | PR merge to dev | Gates on build_tests, calls publish-alpha.yml@dev |
| `publish_stable.yml` | Push to master | Calls publish-stable.yml@dev |
| `release_preview.yml` | PR to dev | Uses release-preview.yml@dev |
| `repo_health.yml` | PR to dev | Uses repo-health.yml@dev |
## Key Features
- **End-to-end testing framework** for OpenVoiceOS skills
- **MiniCroft fixture** — pytest integration with class-scoped skill testing
- **Message capture** — CaptureSession for recording skill responses
- **Assertions** — End2EndTest with assertions (assert_spoke, etc.)
- **Audio harnesses** — AudioServiceHarness, PlaybackServiceHarness, MockAudioBackend, MockTTS, AudioCaptureSession (optional `[audio]` extra)
- **Pydantic integration** — Optional typed bridge with ovos-pydantic-models
- **Version from pyproject.toml** — Full migration from setup.py

## Audio Harness Classes (ovoscope.audio)
| Class | Description |
|---|---|
| `MockAudioBackend` | No-op AudioBackend tracking state (is_playing, is_paused, played_tracks, ducking counters) |
| `AudioServiceHarness` | Context manager: AudioService + MockAudioBackend on FakeBus |
| `MockTTS` | No-op TTS writing silent WAV, recording spoken_utterances |
| `PlaybackServiceHarness` | Context manager: PlaybackService + MockTTS on FakeBus |
| `AudioCaptureSession` | Records bus messages matching prefix list for sequence assertions |
## Test-Gated Releases
✅ Alpha releases gate on `build_tests` passing (100+ unit tests)
✅ Stable releases gate on master push (must pass alpha CI first)
