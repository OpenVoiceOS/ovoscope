# ovoscope — Audit Report
## Documentation Status
- [ ] AGENTS.md Header Format
- [ ] QUICK_FACTS.md
- [ ] FAQ.md
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
### [MAJOR] Missing LICENSE file
**Evidence**: `pyproject.toml` declares `license={text = "Apache-2.0"}` but no `LICENSE` file
exists at the repo root.
**Impact**: Legal ambiguity for downstream users and packagers. PyPI classifiers and SPDX tooling
expect the file to be present.
**Recommended fix**: Add `LICENSE` file containing the Apache-2.0 full text.
---
### ~~[MAJOR] `End2EndTest.execute()` returns `None`~~ ✅ FIXED
`execute()` now returns `List[Message]`. Signature changed to
`def execute(self, timeout: int = 30) -> List[Message]`. `assert_spoke()` builds on this.
---
### [MAJOR] No type annotations on any public method
**Evidence**: All public methods in `ovoscope/__init__.py` — `get_minicroft()`,
`CaptureSession.capture()`, `CaptureSession.finish()`, `End2EndTest.execute()`,
`End2EndTest.from_message()`, `End2EndTest.from_path()`, `End2EndTest.save()` — lack return type
annotations. Parameters are annotated on some (e.g., `get_minicroft`) but not consistently.
**Impact**: IDE type checking and mypy cannot verify callers. Reduces discoverability for new
contributors.
**Recommended fix**: Add PEP 484 annotations to all public method signatures. Run `mypy
ovoscope/` to verify.
---
### [MODERATE] `CaptureSession.capture()` returns `None` — captured messages inaccessible inline
**Evidence**: `ovoscope/__init__.py` lines 133–137 — `capture()` returns nothing. Captured
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
1. Add `LICENSE` (Apache-2.0) — legal requirement
2. Add type annotations to all public methods — maintainability
3. Pin CI action refs — reproducibility
