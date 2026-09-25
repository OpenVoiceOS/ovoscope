# ovoscope CLI

The `ovoscope` command-line tool provides seven subcommands: golden-utterance
runs on a real intent service, and recording, replaying, diffing, validating
and scanning E2E test fixtures.

## Installation

After installing the package (``pip install ovoscope``), the ``ovoscope``
command is available on your ``$PATH``.

```bash
ovoscope --help
```

---

## Subcommands

### `ovoscope record`: Record a fixture

**In-process recording** (default): loads the skill(s) inside the current
process using `MiniCroft` (`cli.py:cmd_record`).

```bash
ovoscope record \
    --skill-id ovos-skill-hello-world.openvoiceos \
    --utterance "hello" \
    --output fixture.json \
    --lang en-US \
    --timeout 20
```

**Live recording** from a running OVOS instance (`RemoteRecorder`, in
`remote_recorder.py:RemoteRecorder.record`):

```bash
ovoscope record --live \
    --bus-url ws://localhost:8181/core \
    --skill-id ovos-skill-date-time.openvoiceos \
    --utterance "what time is it" \
    --output datetime_fixture.json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--skill-id` | none | OPM skill IDs to load (repeatable). |
| `--utterance` | **required** | User utterance text. |
| `--output` | **required** | Output fixture JSON path. |
| `--lang` | `en-US` | Language tag. |
| `--pipeline` | None | Comma-separated pipeline stage IDs. |
| `--timeout` | `20.0` | Capture timeout in seconds. |
| `--live` | False | Use live OVOS instance via `RemoteRecorder`. |
| `--bus-url` | `ws://localhost:8181/core` | MessageBus URL (only for `--live`). |

---

### `ovoscope run`: Replay a fixture

Replays a saved fixture file and exits with code 1 on failure, in
`cli.py:cmd_run`.

```bash
ovoscope run test/fixtures/hello.json
ovoscope run test/fixtures/hello.json --verbose --timeout 30
```

| Flag | Default | Description |
|------|---------|-------------|
| `fixture` | **required** | Path to fixture JSON file. |
| `--verbose` | False | Print failure details. |
| `--timeout` | `30.0` | Execution timeout in seconds. |

---

### `ovoscope diff`: Compare two fixtures

Compares two fixture files and prints a colored report, in
`diff.py:diff_fixtures` and `cli.py:cmd_diff`.

```bash
ovoscope diff expected.json actual.json
ovoscope diff expected.json actual.json --no-color
```

Exits 0 if identical, 1 if differences are found.

| Flag | Default | Description |
|------|---------|-------------|
| `expected` | **required** | Reference fixture path. |
| `actual` | **required** | Fixture to compare against reference. |
| `--no-color` | False | Disable ANSI color codes. |
| `--include-context` | False | Include `context` fields in the comparison. By default context is ignored because it contains ephemeral routing metadata (`source`, `destination`, `session`) that varies between runs. Pass `--include-context` when you specifically want to assert routing behaviour. |

---

### `ovoscope validate`: Schema-validate fixtures

Validates one or more fixture files against the expected schema, in
`cli.py:cmd_validate`.

```bash
ovoscope validate test/fixtures/*.json
```

Uses `pydantic_helpers.validate_fixture` when available (requires
`pip install ovoscope[pydantic]`); falls back to basic JSON structure
validation (checks required top-level keys and that `expected_messages`
is a list) when the `pydantic` extra is not installed.

---

### `ovoscope coverage`: Ecosystem coverage scan

Scans a workspace root for OVOS plugin repos and reports E2E test coverage, in
`coverage.py:scan_workspace` and `cli.py:cmd_coverage`.

```bash
ovoscope coverage "OpenVoiceOS Workspace/" --format table
ovoscope coverage "OpenVoiceOS Workspace/" --format json
```

| Flag | Default | Description |
|------|---------|-------------|
| `workspace` | **required** | Workspace root directory. |
| `--format` | `table` | Output format: `table` or `json`. |

---

### `ovoscope bus-coverage` — Bus handler/emitter coverage

Runs every fixture found under a directory (or a single fixture file), and
reports which bus message types each skill actually listens for and emits,
merged across all fixtures — `cli.py:cmd_bus_coverage`.

```bash
ovoscope bus-coverage test/fixtures/
ovoscope bus-coverage test/fixtures/hello.json --format json
ovoscope bus-coverage test/fixtures/ --skill-id ovos-skill-hello-world.openvoiceos --verbose
```

| Flag | Default | Description |
|------|---------|-------------|
| `test_dir` | **required** | Directory of fixture JSON files, or a single fixture file. |
| `--skill-id` | None | Only report on fixtures that include this skill_id. |
| `--format` | `table` | Output format: `table` or `json`. |
| `--verbose` / `-v` | False | Print per-message-type detail rows. |

Fixtures that fail to load or time out booting `MiniCroft` are skipped and
counted; the run still reports coverage for the fixtures that succeeded.

---

## `ovoscope-setup` — Install the skill into AI coding assistants

`ovoscope-setup` is a separate console script (`setup_skill.py`) that installs
the ovoscope Claude Code / Gemini CLI skill — `SKILL.md`, docs, and `FAQ.md` —
downloaded from GitHub at install time.

```bash
ovoscope-setup                     # auto-detect and install all
ovoscope-setup --claude            # Claude Code only
ovoscope-setup --gemini            # Gemini CLI only (project-level)
ovoscope-setup --gemini --path /my/workspace
ovoscope-setup --list              # show detected tools without installing
ovoscope-setup --no-docs           # skip docs download (offline / CI)
ovoscope-setup --uninstall --claude
```

| Flag | Default | Description |
|------|---------|-------------|
| `--claude` | False | Install for Claude Code (`~/.claude/skills/ovoscope/`). |
| `--gemini` | False | Install for Gemini CLI (`<path>/.gemini/skills/ovoscope/`). Project-level. |
| `--path` | current directory | Project root for the Gemini install. |
| `--list` | False | Show which tools are detected on `PATH` without installing anything. |
| `--no-docs` | False | Skip downloading documentation from GitHub (offline / CI). |
| `--uninstall` | False | Remove the skill instead of installing it. |

With no explicit `--claude`/`--gemini` flag, the tool auto-detects which of
`claude`/`gemini` are on `PATH` and installs for those.

---

### `ovoscope golden`: Golden-utterance rows on a real intent service

Runs a skill's `golden_utterances*.jsonl` rows through one `MiniCroft` per
locale and reads the fired intent back from the bus (`cli.py:cmd_golden`).
The loaded skill must come from `--checkout`, and every utterance carries
its row's `lang`.

```bash
ovoscope golden --rows 'test/end2end/golden_utterances_*.jsonl' \
    --skill ovos-skill-parrot.openvoiceos --checkout . --out golden-results
ovoscope golden --rows 'test/end2end/*.jsonl' --skill my-skill.openvoiceos \
    --pipeline m2v-prototype
```

| Flag | Default | Description |
|------|---------|-------------|
| `--rows` | **required** | Glob(s) of `golden_utterances*.jsonl` files. |
| `--skill` | **required** | The skill id (its entry point name). |
| `--checkout` | `.` | The checkout the loaded skill must come from. |
| `--locales` | all | Comma-separated lang list to run. |
| `--pipeline` | `repo` | A preset, or comma-separated pipeline plugin ids. |
| `--out` | None | Directory for `scoreboard.json` and `predictions.jsonl`. |
| `--timeout` | `20` | Seconds to wait per utterance. |
| `--processes` | `auto` | `auto`: one process per locale for the m2v presets, one process for the whole run otherwise. `per-locale`: always one process per locale. `single`: always one process. |

`--pipeline` presets:

| Preset | Boots |
|--------|-------|
| `repo` | The checkout's own list, `[tool.ovoscope] pipeline` in its `pyproject.toml`. When the checkout declares none, MiniCroft's lean default (stop, converse, adapt, padatious, padacioso, fallback). |
| `m2v-prototype` | Prototype mode alone (`M2V_PROTOTYPE_PIPELINE`) on the published model `OpenVoiceOS/ovos-m2v-intents-multilingual`. Every label the skill registers is served from its own `.intent` files; no classifier, no label mask. |
| `m2v-dual` | Padacioso, the classifier and prototype mode in one list (`M2V_DUAL_PIPELINE`) on the published model, padacioso first for the exact template lines, the classifier's label list masked from the prototype stage. |

Both m2v presets boot through `get_m2v_minicroft`, so the model, the label
mask and the tier order are the one implementation the m2v tests use. The
model is loaded before the first row is fired. A preset that cannot boot
here (plugin not installed, model not reachable) exits 5 and prints the
reason. A preset stands alone: it cannot be mixed with plugin ids.

```toml
# pyproject.toml of a skill: what the repo preset boots
[tool.ovoscope]
pipeline = [
  "ovos-padatious-pipeline-plugin-high",
  "ovos-padacioso-pipeline-plugin-high",
  "ovos-padacioso-pipeline-plugin-medium",
  "ovos-padacioso-pipeline-plugin-low",
]
```

### One process per locale

An m2v boot holds its model in memory, and `MiniCroft.stop()` does not give
that memory back. A 16-locale `m2v-dual` run in one process was killed for
memory at locale 5, so the first published dual number came from 16
processes run by hand. The runner now starts those processes itself: under
an m2v preset each locale boots in a fresh interpreter, which the operating
system reclaims in full at exit, and one command measures the whole corpus.
`--processes single` keeps the old one-process behaviour, and
`--processes per-locale` uses one process per locale for any pipeline.

Each worker is bound in time: 900 seconds for the boot plus the locale's
row count times `--timeout`. A worker that passes the bound is killed, and
the run exits 5 naming the locale. `OVOSCOPE_WORKER_TIMEOUT` sets the bound
in seconds instead. A worker that writes no result file, or a file that
cannot be read because the process was killed while it wrote, also exits 5
with the child's return code in the message.

`OVOSCOPE_GOLDEN_FACTORY` is a test hook. It names a `module:callable` that
the worker imports to build a stand-in MiniCroft factory, so a test can
drive the per-locale path without the real boot. A deployment never sets
it, and it grants nothing new: whoever can set it can already set
`PYTHONPATH` for the same interpreter.

The scoreboard records `preset` and `pipeline` beside the counts.

Exit codes: 0 every row matched; 1 a miss; 2 no row loaded; 3 the skill did
not load from `--checkout`; 4 every row was `needs_manual`; 5 the run could
not boot. Exit 5 covers every boot path: the preset check before the run,
and the boot itself, with or without a preset. A boot failure is never
exit 1, because exit 1 is a corpus miss and a failed boot measured
nothing.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success / no differences / all valid |
| 1 | Failure / differences found / validation error |

---
[← Usage Guide](usage-guide.md) · [Home](../README.md) · [CI Integration →](ci-integration.md)
