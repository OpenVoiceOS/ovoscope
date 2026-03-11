# ovoscope CLI

The `ovoscope` command-line tool provides five subcommands for recording,
replaying, diffing, validating, and scanning E2E test fixtures.

## Installation

After installing the package (``pip install ovoscope``), the ``ovoscope``
command is available on your ``$PATH``.

```bash
ovoscope --help
```

---

## Subcommands

### `ovoscope record` — Record a fixture

**In-process recording** (default): loads the skill(s) inside the current
process using `MiniCroft` — `cli.py:cmd_record`.

```bash
ovoscope record \
    --skill-id ovos-skill-hello-world.openvoiceos \
    --utterance "hello" \
    --output fixture.json \
    --lang en-US \
    --timeout 20
```

**Live recording** from a running OVOS instance (`RemoteRecorder` —
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
| `--skill-id` | — | OPM skill IDs to load (repeatable). |
| `--utterance` | **required** | User utterance text. |
| `--output` | **required** | Output fixture JSON path. |
| `--lang` | `en-US` | Language tag. |
| `--pipeline` | None | Comma-separated pipeline stage IDs. |
| `--timeout` | `20.0` | Capture timeout in seconds. |
| `--live` | False | Use live OVOS instance via `RemoteRecorder`. |
| `--bus-url` | `ws://localhost:8181/core` | MessageBus URL (only for `--live`). |

---

### `ovoscope run` — Replay a fixture

Replays a saved fixture file and exits with code 1 on failure —
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

### `ovoscope diff` — Compare two fixtures

Compares two fixture files and prints a colored report —
`diff.py:diff_fixtures`, `cli.py:cmd_diff`.

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

### `ovoscope validate` — Schema-validate fixtures

Validates one or more fixture files against the expected schema —
`cli.py:cmd_validate`.

```bash
ovoscope validate test/fixtures/*.json
```

Uses `pydantic_helpers.validate_fixture` when available (requires
`pip install ovoscope[pydantic]`); falls back to basic JSON structure
validation (checks required top-level keys and that `expected_messages`
is a list) when the `pydantic` extra is not installed.

---

### `ovoscope coverage` — Ecosystem coverage scan

Scans a workspace root for OVOS plugin repos and reports E2E test coverage —
`coverage.py:scan_workspace`, `cli.py:cmd_coverage`.

```bash
ovoscope coverage "OpenVoiceOS Workspace/" --format table
ovoscope coverage "OpenVoiceOS Workspace/" --format json
```

| Flag | Default | Description |
|------|---------|-------------|
| `workspace` | **required** | Workspace root directory. |
| `--format` | `table` | Output format: `table` or `json`. |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success / no differences / all valid |
| 1 | Failure / differences found / validation error |
