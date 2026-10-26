# Copyright 2024 Jarbas AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""CLI entry point for ovoscope.

Provides the ``ovoscope`` command with the following subcommands:

* ``record``     — In-process fixture recording (or live via ``--live``).
* ``run``        — Replay a fixture file and exit 1 on failure.
* ``diff``       — Compare two fixture files with colored output.
* ``validate``   — Schema-validate one or more fixture files.
* ``coverage``   — Scan a workspace root and report E2E test coverage.
* ``bus-coverage`` — Run fixtures and report bus handler/emitter coverage.
* ``golden``     — Run golden-utterance rows through one MiniCroft per locale.
* ``generate``   — Draft golden rows from a skill's ``.intent`` templates.

Usage::

    ovoscope record --skill-id ovos-skill-hello-world.openvoiceos \\
        --utterance "hello" --output fixture.json
    ovoscope run fixture.json
    ovoscope diff expected.json actual.json
    ovoscope validate fixture.json
    ovoscope coverage path/to/OpenVoiceOS/
    ovoscope bus-coverage test/fixtures/
    ovoscope generate --skill ovos-skill-hello-world.openvoiceos \\
        --checkout . --lang en-us --out golden_generated_en-US.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, NoReturn, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _die(message: str, code: int = 1) -> NoReturn:
    """Print *message* to stderr and exit with *code*."""
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Sub-command implementations
# ---------------------------------------------------------------------------


def cmd_record(args: argparse.Namespace) -> int:
    """Record a fixture: in-process (default) or live (``--live``).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 = success).
    """
    if args.live:
        return _record_live(args)
    return _record_inprocess(args)


def _record_inprocess(args: argparse.Namespace) -> int:
    """Record a fixture using in-process MiniCroft.

    Args:
        args: Parsed CLI arguments with skill_id, utterance, output, lang, pipeline, timeout.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    try:
        from ovoscope import End2EndTest
        from ovos_utils.messagebus import Message
    except ImportError as exc:
        _die(f"ovoscope import failed: {exc}")

    skill_ids: List[str] = args.skill_id if args.skill_id else []
    lang: str = args.lang or "en-US"
    pipeline: Optional[List[str]] = args.pipeline.split(",") if args.pipeline else None
    timeout: float = args.timeout

    src_msg = Message(
        "recognizer_loop:utterance",
        data={"utterances": [args.utterance], "lang": lang},
    )

    # from_message owns the MiniCroft lifecycle: it loads the skills, emits the
    # source utterance, captures the response sequence, and stops MiniCroft.
    # Loading a MiniCroft here as well would double-load the skill plugins.
    print(f"[record] Loading skills: {skill_ids}")
    print(f"[record] Sending utterance: {args.utterance!r}")
    try:
        from_message_kwargs = {"lang": lang, "timeout": timeout}
        if pipeline is not None:
            # MiniCroft's pipeline override kwarg is `default_pipeline`; it is
            # forwarded through from_message -> get_minicroft -> MiniCroft.
            from_message_kwargs["default_pipeline"] = pipeline
        test = End2EndTest.from_message(src_msg, skill_ids, **from_message_kwargs)
    except TimeoutError:
        _die("MiniCroft did not reach READY state in time.")

    test.save(args.output)
    print(f"[record] Fixture saved to {args.output}")
    return 0


def _record_live(args: argparse.Namespace) -> int:
    """Record a fixture from a running OVOS instance.

    Args:
        args: Parsed CLI arguments with bus_url, skill_id, utterance, output, lang, timeout.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    try:
        from ovoscope.remote_recorder import RemoteRecorder
    except ImportError as exc:
        _die(f"RemoteRecorder import failed: {exc}")

    bus_url: str = args.bus_url or "ws://localhost:8181/core"
    lang: str = args.lang or "en-US"
    skill_ids: List[str] = args.skill_id if args.skill_id else []
    timeout: float = args.timeout

    print(f"[record --live] Connecting to {bus_url}")
    recorder = RemoteRecorder(bus_url=bus_url)
    recorder.connect()

    try:
        skill_id = skill_ids[0] if skill_ids else None
        test = recorder.record(
            utterance=args.utterance,
            skill_id=skill_id,
            lang=lang,
            timeout=timeout,
        )
        test.save(args.output)
        print(f"[record --live] Fixture saved to {args.output}")
        return 0
    finally:
        recorder.disconnect()


def cmd_run(args: argparse.Namespace) -> int:
    """Replay a fixture file.  Exit 1 on failure.

    Args:
        args: Parsed CLI arguments with fixture (path), verbose, timeout.

    Returns:
        Exit code (0 = pass, 1 = fail).
    """
    try:
        from ovoscope import End2EndTest, get_minicroft
    except ImportError as exc:
        _die(f"ovoscope import failed: {exc}")

    fixture_path: str = args.fixture
    timeout: float = args.timeout

    print(f"[run] Loading fixture: {fixture_path}")
    try:
        test = End2EndTest.from_path(fixture_path)
    except Exception as exc:
        _die(f"Could not load fixture: {exc}")

    # Use skill_ids from the test fixture
    skill_ids = test.skill_ids or []

    print(f"[run] Starting MiniCroft with skills: {skill_ids}")
    try:
        mc = get_minicroft(skill_ids, max_wait=60)
    except TimeoutError:
        _die("MiniCroft did not reach READY state in time.")

    try:
        # Hand the already-booted MiniCroft to the test. Without this,
        # execute() boots a SECOND managed MiniCroft and both patch the same
        # process-wide globals. `managed = False` keeps ownership here — the
        # finally block below stops it.
        test.minicroft = mc
        test.managed = False
        test.execute(timeout=timeout)
        print("[run] PASS")
        return 0
    except AssertionError as exc:
        if args.verbose:
            print(f"[run] FAIL: {exc}")
        else:
            print("[run] FAIL")
        return 1
    finally:
        mc.stop()


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare two fixture files with colored output.

    Args:
        args: Parsed CLI arguments with expected, actual, no_color, include_context.

    Returns:
        Exit code (0 = identical, 1 = differences found).
    """
    try:
        from ovoscope.diff import diff_fixtures
    except ImportError as exc:
        _die(f"ovoscope.diff import failed: {exc}")

    try:
        result = diff_fixtures(
            expected_path=args.expected,
            actual_path=args.actual,
            ignore_context=not args.include_context,
        )
    except (OSError, ValueError) as exc:
        _die(f"Could not diff fixtures: {exc}")
    result.print_report(color=not args.no_color)
    return 0 if result.is_identical else 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Schema-validate one or more fixture JSON files.

    Uses :func:`ovoscope.pydantic_helpers.validate_fixture` (per-message
    schema validation against ``OpenVoiceOSMessage``) when the ``pydantic``
    extra is installed, falling back to basic JSON structure validation
    (required top-level keys, ``expected_messages`` is a list) otherwise.

    Args:
        args: Parsed CLI arguments with fixtures (list of paths).

    Returns:
        Exit code (0 = all valid, 1 = validation failure).
    """
    try:
        from ovoscope.pydantic_helpers import _PYDANTIC_AVAILABLE, validate_fixture
    except ImportError:
        _PYDANTIC_AVAILABLE = False
        validate_fixture = None

    all_ok = True
    for path in args.fixtures:
        try:
            # Structural checks always run — pydantic validation is a
            # per-message layer on top, not a replacement (validate_fixture
            # skips sections that are absent entirely).
            _basic_validate(path)
            if _PYDANTIC_AVAILABLE:
                validate_fixture(path)
            print(f"[validate] OK  {path}")
        except Exception as exc:
            print(f"[validate] FAIL  {path}: {exc}")
            all_ok = False

    return 0 if all_ok else 1


def _basic_validate(path: str) -> None:
    """Basic JSON structure validation for a fixture file.

    Args:
        path: Path to the fixture JSON file.

    Raises:
        ValueError: If required keys are missing or types are wrong.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    required_keys = {"source_message", "expected_messages"}
    missing = required_keys - data.keys()
    if missing:
        raise ValueError(f"Missing required keys: {missing}")
    if not isinstance(data["expected_messages"], list):
        raise ValueError("'expected_messages' must be a list")


def cmd_coverage(args: argparse.Namespace) -> int:
    """Scan a workspace root and report E2E test coverage.

    Args:
        args: Parsed CLI arguments with workspace (root path), format.

    Returns:
        Exit code (0 = success).
    """
    try:
        from ovoscope.coverage import scan_workspace
    except ImportError as exc:
        _die(f"ovoscope.coverage import failed: {exc}")

    report = scan_workspace(args.workspace)

    if args.format == "json":
        print(json.dumps(report.to_json(), indent=2))
    else:
        report.print_table()

    return 0


def cmd_bus_coverage(args: argparse.Namespace) -> int:
    """Run fixture files and report bus-level handler and emitter coverage.

    Loads each ``.json`` fixture found under *test_dir*, executes it with
    ``track_bus_coverage=True``, aggregates the results, and prints a table
    (or JSON) report.

    Args:
        args: Parsed CLI arguments with test_dir, skill_id, format, verbose.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    import glob as _glob
    import os

    try:
        from ovoscope import End2EndTest, get_minicroft
        from ovoscope.bus_coverage import BusCoverageReport, SkillBusCoverage, HandlerEntry, EmitterEntry
    except ImportError as exc:
        _die(f"ovoscope import failed: {exc}")

    # Collect fixture files
    test_dir: str = args.test_dir
    if os.path.isfile(test_dir) and test_dir.endswith(".json"):
        fixture_paths = [test_dir]
    else:
        fixture_paths = sorted(
            _glob.glob(os.path.join(test_dir, "**", "*.json"), recursive=True)
        )

    if not fixture_paths:
        _die(f"No fixture JSON files found under: {test_dir}")

    filter_skill_id: Optional[str] = getattr(args, "skill_id", None)

    # Merge buckets: skill_id -> {msg_type -> (handler_count, invocation_count)}
    merged_listeners: dict = {}
    merged_observed: dict = {}
    merged_asserted: dict = {}
    errors: List[str] = []

    for fixture_path in fixture_paths:
        print(f"[bus-coverage] Running fixture: {fixture_path}")
        try:
            test = End2EndTest.from_path(fixture_path)
        except Exception as exc:
            print(f"[bus-coverage] SKIP (load error): {exc}")
            errors.append(fixture_path)
            continue

        skill_ids = test.skill_ids or []
        if filter_skill_id and filter_skill_id not in skill_ids:
            continue

        try:
            mc = get_minicroft(skill_ids, max_wait=60)
        except TimeoutError:
            print(f"[bus-coverage] SKIP (MiniCroft timeout): {fixture_path}")
            errors.append(fixture_path)
            continue

        try:
            test.minicroft = mc
            test.managed = False  # prevent execute() from stopping mc; finally block owns it
            test.track_bus_coverage = True
            test.execute()
        except AssertionError as exc:
            print(f"[bus-coverage] WARN (test failure, coverage still collected): {exc}")
        except Exception as exc:
            print(f"[bus-coverage] SKIP (execution error): {exc}")
            errors.append(fixture_path)
            continue
        finally:
            mc.stop()

        report = test.bus_coverage_report
        if report is None:
            continue

        # Merge into global buckets
        for skill in report.skills:
            sid = skill.skill_id
            if sid not in merged_listeners:
                merged_listeners[sid] = {}
            for h in skill.listeners:
                existing = merged_listeners[sid].get(h.msg_type, (h.handler_count, 0))
                merged_listeners[sid][h.msg_type] = (
                    existing[0],
                    existing[1] + h.invocation_count,
                )
            if sid not in merged_observed:
                merged_observed[sid] = {}
            if sid not in merged_asserted:
                merged_asserted[sid] = {}
            for e in skill.emitters:
                merged_observed[sid][e.msg_type] = (
                    merged_observed[sid].get(e.msg_type, 0) + e.observed_count
                )
                merged_asserted[sid][e.msg_type] = (
                    merged_asserted[sid].get(e.msg_type, 0) + e.asserted_count
                )

    # Build final merged report
    skills = []
    for skill_id in sorted(set(merged_listeners) | set(merged_observed)):
        listeners = [
            HandlerEntry(
                msg_type=mt,
                handler_count=hc,
                invocation_count=ic,
                covered=ic > 0,
            )
            for mt, (hc, ic) in sorted(merged_listeners.get(skill_id, {}).items())
        ]
        all_emitted = set(merged_observed.get(skill_id, {}).keys()) | set(
            merged_asserted.get(skill_id, {}).keys()
        )
        emitters = [
            EmitterEntry(
                msg_type=mt,
                observed_count=merged_observed.get(skill_id, {}).get(mt, 0),
                asserted_count=merged_asserted.get(skill_id, {}).get(mt, 0),
                observed=merged_observed.get(skill_id, {}).get(mt, 0) > 0,
                asserted=merged_asserted.get(skill_id, {}).get(mt, 0) > 0,
            )
            for mt in sorted(all_emitted)
        ]
        skills.append(SkillBusCoverage(skill_id=skill_id, listeners=listeners, emitters=emitters))

    final_report = BusCoverageReport(skills=skills)

    if args.format == "json":
        print(final_report.to_json())
    else:
        final_report.print_report(verbose=args.verbose)

    if errors:
        print(f"\n[bus-coverage] {len(errors)} fixture(s) skipped due to errors.")

    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def cmd_generate(args: argparse.Namespace) -> int:
    """Draft golden-utterance rows from a checkout's ``.intent`` templates.

    Rows go to ``--out`` (or stdout) in the ``golden_utterances*.jsonl``
    format, or with ``--format intent-cases`` to ``<out>/<lang>/
    <Intent>.intent.test`` files. Every row is marked ``source:
    generated``. Skipped templates and warnings go to stderr, and to
    ``--report`` as JSON. Exit 0 when rows were written, 2 when none were
    (no ``.intent`` templates for the languages, or every one skipped),
    3 when an output file exists and ``--force`` was not given.
    """
    from pathlib import Path

    from ovoscope.generate import (EXIT_EXISTS, EXIT_NOTHING_GENERATED,
                                   generate_rows, write_golden_rows,
                                   write_intent_cases)

    langs = [l for part in (args.lang or []) for l in part.split(",") if l]
    slot_values: dict = {}
    for item in args.slot or []:
        name, sep, value = item.partition("=")
        if not sep or not name.strip() or not value.strip():
            _die(f"--slot takes NAME=VALUE, got {item!r}")
        slot_values.setdefault(name.strip(), []).append(value.strip())
    if args.format == "intent-cases" and not args.out:
        _die("--format intent-cases needs --out <cases dir>")
    if args.format == "golden" and args.out and Path(args.out).exists() \
            and not args.force:
        _die(f"{args.out} exists; pass --force to overwrite", EXIT_EXISTS)

    result = generate_rows(Path(args.checkout), args.skill, langs=langs,
                           max_per_intent=args.max_per_intent,
                           slot_values=slot_values)
    for item in result.skipped:
        print(f"SKIPPED [{item.lang}] {item.intent} ({item.reason}): "
              f"{item.template!r} in {item.source_file}", file=sys.stderr)
    for item in result.warnings:
        print(f"WARNING [{item.lang}] {item.intent} ({item.reason}): "
              f"{item.template!r} in {item.source_file}; rows still "
              f"generated", file=sys.stderr)
    if args.report:
        Path(args.report).write_text(
            json.dumps(result.report(), indent=2, ensure_ascii=False),
            encoding="utf-8")

    n_intents = sum(len(v) for v in result.intents.values())
    print(f"{len(result.rows)} rows from {n_intents} intent(s) in "
          f"{len(result.intents)} language(s); {len(result.skipped)} "
          f"skipped, {len(result.warnings)} warning(s)", file=sys.stderr)
    if not result.rows:
        return EXIT_NOTHING_GENERATED

    if args.format == "intent-cases":
        try:
            paths = write_intent_cases(result.rows, Path(args.out),
                                       force=args.force)
        except FileExistsError as exc:
            _die(str(exc), EXIT_EXISTS)
        print(f"wrote {len(paths)} case file(s) under {args.out}",
              file=sys.stderr)
    elif args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            write_golden_rows(result.rows, fh)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        write_golden_rows(result.rows, sys.stdout)
    return 0


def cmd_golden(args: argparse.Namespace) -> int:
    """Run a skill's golden-utterance rows through one MiniCroft per locale.

    Exit 0 when every row matched, 1 on any miss, 2 when no row loaded,
    3 when the skill did not load from ``--checkout``, 4 when every row
    was skipped as ``needs_manual``, 5 when the run could not boot: the
    preset check before the run (plugin not installed, model not reachable)
    or the boot itself, with or without a preset.
    The loaded skill must come from ``--checkout`` (T-3351) and every
    utterance carries its row's ``lang`` (T-3308).
    """
    from ovoscope.golden_minicroft import (EXIT_ROOT_DIR, RootDirMismatch,
                                           run_golden)

    locales = [l for l in (args.locales or "").split(",") if l] or None
    pipeline = [p for p in (args.pipeline or "").split(",") if p] or None
    per_locale = {"auto": None, "per-locale": True, "single": False}[args.processes]
    try:
        return run_golden(args.rows, args.skill, args.checkout,
                          locales=locales, pipeline=pipeline,
                          out_dir=args.out, timeout=args.timeout,
                          per_locale_process=per_locale)
    except RootDirMismatch as exc:
        _die(str(exc), EXIT_ROOT_DIR)


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        prog="ovoscope",
        description="End-to-end test framework for OpenVoiceOS skills.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # --- golden ---
    p_golden = sub.add_parser(
        "golden",
        help="Run golden-utterance rows through a real intent service, "
             "one MiniCroft per locale; exit 1 on any miss.")
    p_golden.add_argument("--rows", nargs="+", required=True,
                          help="glob(s) of golden_utterances*.jsonl files")
    p_golden.add_argument("--skill", required=True,
                          help="skill id (the entry point name)")
    p_golden.add_argument("--checkout", default=".",
                          help="the skill checkout the loaded skill must "
                               "come from (default: .)")
    p_golden.add_argument("--locales", default=None,
                          help="comma-separated lang list to run (default: all)")
    p_golden.add_argument("--pipeline", default=None,
                          help="a preset (repo, m2v-prototype, m2v-dual) or "
                               "comma-separated pipeline ids. Default: repo, "
                               "the checkout's [tool.ovoscope] pipeline, or "
                               "MiniCroft's lean default when none is declared")
    p_golden.add_argument("--out", default=None,
                          help="directory for scoreboard.json and predictions.jsonl")
    p_golden.add_argument("--timeout", type=float, default=20.0,
                          help="seconds to wait per utterance")
    p_golden.add_argument("--processes", default="auto",
                          choices=("auto", "per-locale", "single"),
                          help="how many interpreters the run uses. auto "
                               "(default): one process per locale for the m2v "
                               "presets, one process for the whole run "
                               "otherwise. per-locale: always one process per "
                               "locale. single: always one process")

    # --- generate ---
    p_gen = sub.add_parser(
        "generate",
        help="Draft golden-utterance rows from a skill's .intent/.entity "
             "files; every row is marked source: generated.")
    p_gen.add_argument("--skill", required=True,
                       help="skill id every row carries (the entry point name)")
    p_gen.add_argument("--checkout", default=".",
                       help="the skill checkout to read locale/ from "
                            "(default: .)")
    p_gen.add_argument("--lang", action="append", default=None,
                       help="language to draft for; repeat or comma-separate. "
                            "Default: every language under locale/")
    p_gen.add_argument("--out", default=None,
                       help="output .jsonl file (default: stdout), or the "
                            "cases directory for --format intent-cases")
    p_gen.add_argument("--format", default="golden",
                       choices=("golden", "intent-cases"),
                       help="golden: golden_utterances*.jsonl rows (default). "
                            "intent-cases: <out>/<lang>/<Intent>.intent.test")
    p_gen.add_argument("--max-per-intent", type=int, default=10,
                       help="most rows per intent and language; templates "
                            "take turns (default: 10)")
    p_gen.add_argument("--slot", action="append", default=None,
                       metavar="NAME=VALUE",
                       help="value for a slot with no .entity file; repeatable")
    p_gen.add_argument("--report", default=None,
                       help="write rows per intent, skipped templates and "
                            "warnings as JSON to this file")
    p_gen.add_argument("--force", action="store_true",
                       help="overwrite existing output files")

    # --- record ---
    p_record = sub.add_parser("record", help="Record a fixture file.")
    p_record.add_argument("--skill-id", nargs="*", metavar="ID", help="OPM skill IDs to load.")
    p_record.add_argument("--utterance", required=True, metavar="TEXT", help="Utterance to send.")
    p_record.add_argument("--output", required=True, metavar="FILE", help="Output fixture path.")
    p_record.add_argument("--lang", default="en-US", metavar="LANG", help="Language tag (default: en-US).")
    p_record.add_argument("--pipeline", default=None, metavar="STAGES", help="Comma-separated pipeline stages.")
    p_record.add_argument("--timeout", type=float, default=20.0, metavar="SEC", help="Capture timeout seconds.")
    p_record.add_argument("--live", action="store_true", help="Record from a running OVOS instance.")
    p_record.add_argument("--bus-url", default=None, metavar="URL", help="MessageBus URL for --live mode.")

    # --- run ---
    p_run = sub.add_parser("run", help="Replay a fixture and exit 1 on failure.")
    p_run.add_argument("fixture", metavar="FIXTURE", help="Path to fixture JSON file.")
    p_run.add_argument("--verbose", "-v", action="store_true", help="Show failure details.")
    p_run.add_argument("--timeout", type=float, default=30.0, metavar="SEC", help="Execution timeout seconds.")

    # --- diff ---
    p_diff = sub.add_parser("diff", help="Compare two fixture files.")
    p_diff.add_argument("expected", metavar="EXPECTED", help="Reference fixture file.")
    p_diff.add_argument("actual", metavar="ACTUAL", help="Fixture file to compare.")
    p_diff.add_argument("--no-color", action="store_true", help="Disable ANSI colors.")
    p_diff.add_argument(
        "--include-context",
        action="store_true",
        help="Include context field in comparison (default: skip context).",
    )

    # --- validate ---
    p_validate = sub.add_parser("validate", help="Schema-validate fixture files.")
    p_validate.add_argument("fixtures", nargs="+", metavar="FILE", help="Fixture JSON files to validate.")

    # --- coverage ---
    p_coverage = sub.add_parser("coverage", help="Scan workspace for E2E test coverage.")
    p_coverage.add_argument("workspace", metavar="WORKSPACE", help="Path to workspace root.")
    p_coverage.add_argument("--format", choices=["table", "json"], default="table",
                            help="Output format (default: table).")

    # --- bus-coverage ---
    p_bus = sub.add_parser(
        "bus-coverage",
        help="Run fixture files and report bus handler/emitter coverage.",
    )
    p_bus.add_argument(
        "test_dir",
        metavar="TEST_DIR",
        help="Path to a directory of fixture JSON files (or a single fixture file).",
    )
    p_bus.add_argument(
        "--skill-id",
        default=None,
        metavar="ID",
        help="Only report on fixtures that include this skill_id.",
    )
    p_bus.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table).",
    )
    p_bus.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-msg-type detail rows.",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the ``ovoscope`` command."""
    parser = _build_parser()
    args = parser.parse_args()

    dispatch = {
        "golden": cmd_golden,
        "generate": cmd_generate,
        "record": cmd_record,
        "run": cmd_run,
        "diff": cmd_diff,
        "validate": cmd_validate,
        "coverage": cmd_coverage,
        "bus-coverage": cmd_bus_coverage,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
