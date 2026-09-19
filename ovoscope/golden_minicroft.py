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

``--pipeline`` takes an explicit list of plugin ids or one of three named
presets. ``repo`` (the default) is the checkout's own list, read from
``[tool.ovoscope] pipeline`` in its ``pyproject.toml``, and MiniCroft's
lean default when the checkout declares none. ``m2v-prototype`` and
``m2v-dual`` boot through :func:`ovoscope.get_m2v_minicroft` on the
published model, so the model, the label mask and the tier order are the
one implementation the ovoscope m2v tests already use.
"""
from __future__ import annotations

import dataclasses
import glob
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope.golden import GoldenRow, load_golden_rows

RUNNER_ID = "minicroft"
#: path segments that mark an installed copy rather than a checkout's source
INSTALL_SEGMENTS = frozenset({"site-packages", "dist-packages", ".venv", "venv"})
#: exit codes of ``ovoscope golden``
EXIT_MISS, EXIT_NO_ROWS, EXIT_ROOT_DIR, EXIT_ALL_SKIPPED = 1, 2, 3, 4
EXIT_PRESET = 5
#: the named ``--pipeline`` presets
PRESET_REPO, PRESET_M2V_PROTOTYPE, PRESET_M2V_DUAL = ("repo", "m2v-prototype",
                                                      "m2v-dual")
PRESETS = (PRESET_REPO, PRESET_M2V_PROTOTYPE, PRESET_M2V_DUAL)
M2V_PRESETS = (PRESET_M2V_PROTOTYPE, PRESET_M2V_DUAL)
#: the module one locale of an isolated run boots in
WORKER_MODULE = "ovoscope.golden_worker"
#: seconds a worker gets for the boot, on top of its rows' own timeouts.
#: An m2v boot downloads and loads the model before the first row.
WORKER_BOOT_ALLOWANCE = 900.0
#: seconds one worker may take in total; unset, the bound is derived from
#: the locale's row count (see ``worker_timeout``)
WORKER_TIMEOUT_ENV = "OVOSCOPE_WORKER_TIMEOUT"
#: a test names ``module:callable`` here; the worker calls it with the
#: preset name and boots the ``minicroft_factory`` it returns
WORKER_FACTORY_ENV = "OVOSCOPE_GOLDEN_FACTORY"


class RootDirMismatch(RuntimeError):
    """The loaded skill did not come from the checkout under test."""


class PresetUnavailable(RuntimeError):
    """A ``--pipeline`` preset cannot boot here; the message says why."""


def repo_pipeline(checkout: Path) -> Optional[List[str]]:
    """The checkout's own pipeline list, or ``None`` when it declares none.

    Read from ``[tool.ovoscope] pipeline`` in ``<checkout>/pyproject.toml``.
    """
    path = Path(checkout) / "pyproject.toml"
    if not path.is_file():
        return None
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover - 3.10 only
        import tomli as tomllib
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    stages = data.get("tool", {}).get("ovoscope", {}).get("pipeline")
    if stages is None:
        return None
    if not isinstance(stages, list) or not all(isinstance(s, str) for s in stages):
        raise PresetUnavailable(
            f"[tool.ovoscope] pipeline in {path} must be a list of plugin ids")
    return list(stages) or None


def m2v_model_unreachable(model: str) -> Optional[str]:
    """Why ``model`` cannot be loaded here, or ``None`` when it can.

    A local directory or a Hub checkpoint already in the cache is reachable
    offline; otherwise one ``config.json`` download decides. The reason is
    the text a test gives ``skipTest`` and the CLI prints before exit 5.
    """
    if os.path.isdir(model):
        if os.path.isfile(os.path.join(model, "config.json")):
            return None
        return f"{model} is a directory without config.json"
    try:
        import huggingface_hub
    except ImportError:
        return "huggingface_hub is not installed"
    try:
        huggingface_hub.hf_hub_download(model, "config.json")
    except Exception as exc:  # network, 401/404, offline mode
        return f"{model} is not reachable: {type(exc).__name__}: {exc}"
    return None


def preset_unavailable(preset: str) -> Optional[str]:
    """Why an m2v preset cannot boot here, or ``None`` when it can."""
    from ovoscope import (M2V_DUAL_PIPELINE, M2V_PROTOTYPE_PIPELINE,
                          M2V_PUBLISHED_MODEL, is_pipeline_available)
    stages = (M2V_DUAL_PIPELINE if preset == PRESET_M2V_DUAL
              else M2V_PROTOTYPE_PIPELINE)
    if not is_pipeline_available(stages):
        return f"preset {preset!r} needs ovos-m2v-pipeline installed"
    reason = m2v_model_unreachable(M2V_PUBLISHED_MODEL)
    if reason:
        return f"preset {preset!r}: {reason}"
    return None


def resolve_pipeline(spec: Optional[Sequence[str]], checkout: Path
                     ) -> tuple:
    """Turn ``--pipeline`` into ``(preset, stages)``.

    ``spec`` is ``None`` or a list with one preset name, or a list of plugin
    ids. A preset returns ``(name, None)``; ``repo`` returns ``(None,
    <declared list or None>)`` since it is an explicit list once read; an
    explicit list returns ``(None, list)``. Raises :class:`PresetUnavailable`
    when an m2v preset cannot boot here.
    """
    if not spec:
        spec = [PRESET_REPO]
    if len(spec) == 1 and spec[0] in PRESETS:
        preset = spec[0]
        if preset == PRESET_REPO:
            return None, repo_pipeline(checkout)
        reason = preset_unavailable(preset)
        if reason:
            raise PresetUnavailable(reason)
        return preset, None
    unknown = [s for s in spec if s in PRESETS]
    if unknown:
        raise PresetUnavailable(
            f"a preset stands alone: {unknown} cannot be mixed with plugin ids")
    return None, list(spec)


def preset_factory(preset: str, **boot_kwargs):
    """The ``minicroft_factory`` of an m2v preset: one boot implementation.

    Both presets call :func:`ovoscope.get_m2v_minicroft` on
    ``M2V_PUBLISHED_MODEL``; ``m2v-prototype`` passes ``classifier=False``.
    ``boot_kwargs`` reach the boot unchanged (a test passes
    ``extra_skills``).
    """
    from ovoscope import M2V_PUBLISHED_MODEL, get_m2v_minicroft

    def factory(skill_id, lang, pipe):
        mc = get_m2v_minicroft([skill_id], model=M2V_PUBLISHED_MODEL,
                               lang=lang,
                               classifier=preset == PRESET_M2V_DUAL,
                               **boot_kwargs)
        warm_m2v_models(mc)
        return mc
    return factory


def warm_m2v_models(mc) -> None:
    """Load every m2v stage's model now, before the first row is fired.

    ovos-m2v-pipeline defers the model load to the first utterance and
    answers that utterance with "still warming up", so a golden run that
    fires straight after READY loses its first row per locale to the load.
    """
    for plugin in mc.intents.pipeline_plugins.values():
        ensure = getattr(plugin, "_ensure_model", None)
        if ensure is not None:
            ensure(background_ok=False)


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
    # a venv inside the checkout holds a non-editable copy of the skill
    # under site-packages; that copy is on disk under the checkout and is
    # still not the checkout's own source
    between = root.relative_to(checkout).parts if root != checkout else ()
    installed = [p for p in between if p in INSTALL_SEGMENTS]
    if installed:
        raise RootDirMismatch(
            f"skill {skill_id!r} loaded from {root}, an installed copy under "
            f"{'/'.join(installed)} inside the checkout {checkout}, not the "
            f"checkout's own source. Install the checkout editable.")
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
             preset: Optional[str] = None,
             timeout: float = 20.0, minicroft_factory=None) -> List[RowResult]:
    """Run every row, one MiniCroft per locale, locale order, never two alive.

    ``minicroft_factory(skill_id, lang, pipeline)`` returns a started
    MiniCroft; the default calls :func:`ovoscope.get_minicroft`, or
    :func:`ovoscope.get_m2v_minicroft` for an m2v ``preset``. Under a
    preset every Session carries the booted MiniCroft's own pipeline, so
    the tier order on the wire is the one the boot chose.

    A boot that raises, on any path, becomes a :class:`PresetUnavailable`
    with the locale and the reason. The caller reports exit 5 for it, since
    exit 1 is a corpus miss and a boot failure measured nothing.
    """
    from ovoscope import get_minicroft

    def default_factory(sid, lang, pipe):
        kwargs = {"lang": lang}
        if pipe:
            kwargs["default_pipeline"] = list(pipe)
        return get_minicroft([sid], **kwargs)

    if preset in M2V_PRESETS:
        factory = minicroft_factory or preset_factory(preset)
    elif preset is not None:
        raise PresetUnavailable(f"unknown preset {preset!r}; one of {PRESETS}")
    else:
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
        try:
            mc = factory(skill_id, lang, pipeline)
        except PresetUnavailable:
            raise
        except Exception as exc:
            what = f"preset {preset!r}" if preset else "the MiniCroft boot"
            raise PresetUnavailable(
                f"{what} could not boot for {lang}: "
                f"{type(exc).__name__}: {exc}") from exc
        session_pipeline = pipeline
        if preset is not None:
            session_pipeline = list(mc.pipeline)
        try:
            assert_root_dir(mc, skill_id, checkout)
            for row in active:
                fired, handlers, latency = _fired_types(mc, skill_id, row,
                                                        session_pipeline, timeout)
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


def worker_timeout(rows: int, timeout: float) -> float:
    """Seconds one locale's worker may take, boot included.

    The per-row ``timeout`` bounds one utterance inside the child, not the
    child. Without a bound of its own a child whose boot hangs blocks the
    run until the CI job is cancelled, and a cancelled job carries no exit
    code to read. ``OVOSCOPE_WORKER_TIMEOUT`` overrides the derived value.
    """
    override = os.environ.get(WORKER_TIMEOUT_ENV)
    if override:
        try:
            return float(override)
        except ValueError:
            LOG.warning(f"{WORKER_TIMEOUT_ENV}={override!r} is not a number; "
                        f"using the derived bound")
    return WORKER_BOOT_ALLOWANCE + max(rows, 1) * max(timeout, 1.0)


def _run_locale(rows: List[GoldenRow], skill_id: str, checkout: Path, *,
                pipeline: Optional[Sequence[str]], preset: Optional[str],
                timeout: float) -> List[RowResult]:
    """One locale in its own interpreter; the results come back as rows."""
    import subprocess
    import tempfile

    lang = rows[0].lang
    with tempfile.TemporaryDirectory(prefix="ovoscope-golden-") as tmp:
        job = Path(tmp) / "job.json"
        out = Path(tmp) / "out.json"
        job.write_text(json.dumps({
            "rows": [dataclasses.asdict(r) for r in rows],
            "skill_id": skill_id,
            "checkout": str(checkout),
            "pipeline": list(pipeline) if pipeline else None,
            "preset": preset,
            "timeout": timeout,
        }, ensure_ascii=False), encoding="utf-8")
        bound = worker_timeout(len(rows), timeout)
        try:
            proc = subprocess.run([sys.executable, "-m", WORKER_MODULE,
                                   str(job), str(out)], timeout=bound)
        except subprocess.TimeoutExpired:
            raise PresetUnavailable(
                f"the golden worker for {lang} did not finish in "
                f"{bound:.0f}s and was killed. That is {len(rows)} row(s) at "
                f"{timeout:.0f}s each plus {WORKER_BOOT_ALLOWANCE:.0f}s for "
                f"the boot; set OVOSCOPE_WORKER_TIMEOUT to change it.")
        if not out.is_file():
            raise PresetUnavailable(
                f"the golden worker for {lang} ended with exit code "
                f"{proc.returncode} and wrote no result. A kill for memory "
                f"reads as exit code -9.")
        try:
            answer = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # a kill that lands while the child writes leaves a part of the
            # file; that is the same "could not boot" case as no file at all
            raise PresetUnavailable(
                f"the golden worker for {lang} ended with exit code "
                f"{proc.returncode} and wrote a result that cannot be read: "
                f"{type(exc).__name__}: {exc}") from exc
    if "error" in answer:
        cls = {"RootDirMismatch": RootDirMismatch}.get(
            answer.get("error_type"), PresetUnavailable)
        raise cls(f"[{lang}] {answer['error']}")
    try:
        return [RowResult(**r) for r in answer["results"]]
    except (AttributeError, KeyError, TypeError) as exc:
        raise PresetUnavailable(
            f"the golden worker for {lang} ended with exit code "
            f"{proc.returncode} and wrote a result of the wrong shape: "
            f"{type(exc).__name__}: {exc}") from exc


def run_rows_per_locale(rows: List[GoldenRow], skill_id: str, checkout: Path,
                        *, pipeline: Optional[Sequence[str]] = None,
                        preset: Optional[str] = None,
                        timeout: float = 20.0) -> List[RowResult]:
    """:func:`run_rows`, one interpreter per locale, results concatenated.

    An m2v boot holds its model in memory, and ``MiniCroft.stop()`` does
    not give that memory back. A 16-locale ``m2v-dual`` run in one process
    was killed for memory at locale 5 (T-3533), so the published 202/319
    came from 16 processes run by hand. Here the runner starts those
    processes itself: each locale boots in a fresh interpreter, which the
    operating system reclaims in full at exit, and one command measures the
    whole corpus.
    """
    by_lang: Dict[str, List[GoldenRow]] = {}
    for row in rows:
        by_lang.setdefault(row.lang, []).append(row)
    results: List[RowResult] = []
    for lang in sorted(by_lang):
        results.extend(_run_locale(by_lang[lang], skill_id, checkout,
                                   pipeline=pipeline, preset=preset,
                                   timeout=timeout))
    return results


def scoreboard(results: List[RowResult], skill_id: str,
               pipeline: Optional[Sequence[str]] = None,
               preset: Optional[str] = None) -> Dict[str, dict]:
    """The ``run_golden_suite`` scoreboard shape, one engine: the MiniCroft.

    ``pipeline`` and ``preset`` record what the run booted, so a board
    read later says which engine produced its numbers.
    """
    scored = [r for r in results if not r.skipped]
    entry = {
        "gating": True,
        "preset": preset,
        "pipeline": list(pipeline) if pipeline else None,
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
               minicroft_factory=None, echo=print,
               per_locale_process: Optional[bool] = None) -> int:
    """The ``ovoscope golden`` command body. Returns the exit code.

    ``pipeline`` is the ``--pipeline`` value split on commas: a preset name
    alone, an explicit list, or ``None`` for the ``repo`` preset.

    ``per_locale_process`` puts each locale in its own interpreter. It
    defaults to on for the m2v presets, whose models stay in memory after
    ``stop()``, and off for every other pipeline. A ``minicroft_factory``
    is a callable of this process, so it keeps the run in one process.
    """
    rows = collect_rows(rows_patterns, locales)
    if not rows:
        echo(f"no golden rows under {list(rows_patterns)}")
        return EXIT_NO_ROWS
    try:
        preset, stages = resolve_pipeline(pipeline, Path(checkout))
    except PresetUnavailable as exc:
        echo(f"PRESET UNAVAILABLE: {exc}")
        return EXIT_PRESET
    echo(f"pipeline: {preset or (stages if stages else 'MiniCroft default')}")
    if per_locale_process is None:
        per_locale_process = preset in M2V_PRESETS and minicroft_factory is None
    try:
        if per_locale_process:
            echo("one process per locale: the model memory goes back to the "
                 "operating system between locales")
            results = run_rows_per_locale(rows, skill_id, Path(checkout),
                                          pipeline=stages, preset=preset,
                                          timeout=timeout)
        else:
            results = run_rows(rows, skill_id, Path(checkout), pipeline=stages,
                               preset=preset, timeout=timeout,
                               minicroft_factory=minicroft_factory)
    except PresetUnavailable as exc:
        echo(f"PRESET UNAVAILABLE: {exc}")
        return EXIT_PRESET
    if preset in M2V_PRESETS:
        from ovoscope import M2V_DUAL_PIPELINE, M2V_PROTOTYPE_PIPELINE
        stages = (M2V_DUAL_PIPELINE if preset == PRESET_M2V_DUAL
                  else M2V_PROTOTYPE_PIPELINE)
    board = scoreboard(results, skill_id, pipeline=stages, preset=preset)
    entry = board[f"{RUNNER_ID}:{skill_id}"]
    if entry["total"] == 0:
        echo(f"ALL SKIPPED: {entry['skipped']} row(s) loaded, every one "
             f"needs_manual, nothing measured")
        if out_dir:
            for path in write_results(results, board, Path(out_dir)):
                echo(f"wrote {path}")
        return EXIT_ALL_SKIPPED
    for failure in entry["failures"]:
        echo(f"MISS [{failure['lang']}] {failure['utterance']!r}: expected "
             f"{failure['expected']!r}, fired {failure['got']}")
    echo(f"{entry['total']} rows, {entry['matched']} matched, "
         f"{entry['total'] - entry['matched']} failed, "
         f"{entry['skipped']} skipped (needs_manual)")
    if out_dir:
        for path in write_results(results, board, Path(out_dir)):
            echo(f"wrote {path}")
    return 0 if entry["gate_passed"] else EXIT_MISS
