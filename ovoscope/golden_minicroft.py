"""The shared golden-utterance runner: one MiniCroft per locale.

Every per-repo golden runner in the skill fleet boots a real intent
service, loads the skill, puts the row's ``lang`` on the Session and reads
the fired ``skill_id:intent`` back from the bus. This module is that runner
written once, so a skill repository ships its ``.jsonl`` rows and nothing
else. ``run_golden_suite`` in :mod:`ovoscope.golden` is a different
instrument (engines driven directly, no bus, no skill); this one reports
in the same scoreboard shape so the two read alike.

Three constraints the fleet learned the hard way, each enforced here:

- the loaded skill's ``root_dir`` must be the checkout under test, else a
  stale site-packages copy of the same skill is what gets measured
  (T-3351);
- the row's ``lang`` goes on the Session of every utterance; the runner
  never defaults to ``en-US`` (T-3308);
- no slot is supplied: a slot proves which template line matched, not
  the intent.
"""
from __future__ import annotations

import dataclasses
import glob
import json
import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from ovoscope.golden import GoldenRow, load_golden_rows

RUNNER_ID = "minicroft"


class RootDirMismatch(RuntimeError):
    """The loaded skill did not come from the checkout under test."""


@dataclasses.dataclass
class RowResult:
    utterance: str
    lang: str
    expected: Optional[str]
    fired: List[str]
    matched: bool
    core: bool
    latency_ms: float
    skipped: bool = False

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def collect_rows(patterns: Sequence[str], locales: Optional[Iterable[str]] = None
                 ) -> List[GoldenRow]:
    """Load every row the glob patterns name; narrow to ``locales`` if given."""
    paths: List[str] = []
    for pattern in patterns:
        paths.extend(sorted(glob.glob(pattern, recursive=True)))
    rows: List[GoldenRow] = []
    for path in dict.fromkeys(paths):
        rows.extend(load_golden_rows(path))
    if locales:
        wanted = set(locales)
        rows = [r for r in rows if r.lang in wanted]
    return rows


def _skipped(row: GoldenRow) -> bool:
    return bool(row.provenance.get("needs_manual"))


def _label_forms(skill_id: str, expected: str) -> set:
    """The fired types that count as a hit for ``expected``.

    A row states ``IntentName``, ``IntentName.intent`` or the full
    ``skill_id:IntentName``; the bus carries ``skill_id:IntentName``.
    """
    name = expected.split(":", 1)[1] if expected.startswith(f"{skill_id}:") else expected
    forms = {f"{skill_id}:{name}"}
    if name.endswith(".intent"):
        forms.add(f"{skill_id}:{name[:-len('.intent')]}")
    return forms


def assert_root_dir(minicroft, skill_id: str, checkout: Path) -> Path:
    """Fail unless the loaded skill's ``root_dir`` is inside ``checkout``."""
    loader = minicroft.plugin_skills.get(skill_id)
    if loader is None or getattr(loader, "instance", None) is None:
        raise RootDirMismatch(f"skill {skill_id!r} did not load")
    root = Path(loader.instance.root_dir).resolve()
    checkout = checkout.resolve()
    if checkout != root and checkout not in root.parents:
        raise RootDirMismatch(
            f"skill {skill_id!r} loaded from {root}, which is not under the "
            f"checkout {checkout}. Install the checkout editable, or the run "
            f"measures another copy of the skill.")
    return root


def _fired_types(minicroft, skill_id: str, row: GoldenRow, pipeline,
                 timeout: float) -> tuple:
    """Fire the row's utterance with its own lang and read what the skill ran."""
    from ovoscope import CaptureSession

    sess = Session(session_id=f"golden-{row.lang}", lang=row.lang)
    if pipeline:
        sess.pipeline = list(pipeline)
    message = Message("recognizer_loop:utterance",
                      {"utterances": [row.utterance], "lang": row.lang},
                      {"session": sess.serialize(), "source": "golden",
                       "destination": "skills"})
    capture = CaptureSession(minicroft=minicroft)
    started = time.monotonic()
    capture.capture(message, timeout=timeout)
    latency = (time.monotonic() - started) * 1000
    seen = capture.finish()
    prefix = f"{skill_id}:"
    fired = [m.msg_type for m in seen
             if m.msg_type.startswith(prefix) or
             (m.msg_type == "mycroft.skill.handler.start"
              and str(m.data.get("name", "")).startswith(prefix))]
    handler_names = [m.data.get("name") for m in seen
                     if m.msg_type == "mycroft.skill.handler.start"
                     and str(m.data.get("name", "")).startswith(prefix)]
    return fired, handler_names, latency


def run_rows(rows: List[GoldenRow], skill_id: str, checkout: Path, *,
             pipeline: Optional[Sequence[str]] = None,
             timeout: float = 20.0, minicroft_factory=None) -> List[RowResult]:
    """Run every row, one MiniCroft per locale, locale order, never two alive.

    ``minicroft_factory(skill_id, lang, pipeline)`` returns a started
    MiniCroft; the default calls :func:`ovoscope.get_minicroft`.
    """
    from ovoscope import get_minicroft

    def default_factory(sid, lang, pipe):
        kwargs = {"lang": lang}
        if pipe:
            kwargs["default_pipeline"] = list(pipe)
        return get_minicroft([sid], **kwargs)

    factory = minicroft_factory or default_factory
    by_lang: Dict[str, List[GoldenRow]] = {}
    for row in rows:
        by_lang.setdefault(row.lang, []).append(row)

    results: List[RowResult] = []
    for lang in sorted(by_lang):
        active = [r for r in by_lang[lang] if not _skipped(r)]
        for r in by_lang[lang]:
            if _skipped(r):
                results.append(RowResult(r.utterance, r.lang, r.expected_intent,
                                         [], True, r.core, 0.0, skipped=True))
        if not active:
            continue
        mc = factory(skill_id, lang, pipeline)
        try:
            assert_root_dir(mc, skill_id, checkout)
            for row in active:
                fired, handlers, latency = _fired_types(mc, skill_id, row,
                                                        pipeline, timeout)
                if row.expected_intent is None:
                    matched = not fired
                else:
                    forms = _label_forms(skill_id, row.expected_intent)
                    matched = any(f in forms for f in fired) or \
                        any(h in forms for h in handlers)
                results.append(RowResult(row.utterance, row.lang,
                                         row.expected_intent, fired, matched,
                                         row.core, latency))
        finally:
            mc.stop()
    return results


def scoreboard(results: List[RowResult], skill_id: str) -> Dict[str, dict]:
    """The ``run_golden_suite`` scoreboard shape, one engine: the MiniCroft."""
    scored = [r for r in results if not r.skipped]
    entry = {
        "gating": True,
        "total": len(scored),
        "matched": sum(1 for r in scored if r.matched),
        "core_total": sum(1 for r in scored if r.core),
        "core_matched": sum(1 for r in scored if r.core and r.matched),
        "skipped": sum(1 for r in results if r.skipped),
        "failures": [{"utterance": r.utterance, "lang": r.lang,
                      "expected": r.expected, "got": r.fired,
                      "confidence": None, "core": r.core}
                     for r in scored if not r.matched],
    }
    entry["pct"] = (entry["matched"] / entry["total"]) if entry["total"] else 1.0
    entry["gate_passed"] = entry["matched"] == entry["total"]
    entry["gate_reason"] = None if entry["gate_passed"] else (
        f"{entry['total'] - entry['matched']} row(s) missed")
    return {f"{RUNNER_ID}:{skill_id}": entry}


def write_results(results: List[RowResult], board: Dict[str, dict],
                  out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    board_path = out_dir / "scoreboard.json"
    board_path.write_text(json.dumps(board, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    pred_path = out_dir / "predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.as_dict(), ensure_ascii=False) + "\n")
    return [board_path, pred_path]


def run_golden(rows_patterns: Sequence[str], skill_id: str, checkout: str,
               locales: Optional[Sequence[str]] = None,
               pipeline: Optional[Sequence[str]] = None,
               out_dir: Optional[str] = None, timeout: float = 20.0,
               minicroft_factory=None, echo=print) -> int:
    """The ``ovoscope golden`` command body. Returns the exit code."""
    rows = collect_rows(rows_patterns, locales)
    if not rows:
        echo(f"no golden rows under {list(rows_patterns)}")
        return 2
    results = run_rows(rows, skill_id, Path(checkout), pipeline=pipeline,
                       timeout=timeout, minicroft_factory=minicroft_factory)
    board = scoreboard(results, skill_id)
    entry = board[f"{RUNNER_ID}:{skill_id}"]
    for failure in entry["failures"]:
        echo(f"MISS [{failure['lang']}] {failure['utterance']!r}: expected "
             f"{failure['expected']!r}, fired {failure['got']}")
    echo(f"{entry['total']} rows, {entry['matched']} matched, "
         f"{entry['total'] - entry['matched']} failed, "
         f"{entry['skipped']} skipped (needs_manual)")
    if out_dir:
        for path in write_results(results, board, Path(out_dir)):
            echo(f"wrote {path}")
    return 0 if entry["gate_passed"] else 1
