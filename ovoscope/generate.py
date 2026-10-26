"""Draft golden-utterance rows from a skill's own ``.intent`` templates.

Most skills ship no golden file, but every skill that registers Padatious
intents already states what it was trained on: its ``locale/<lang>/
*.intent`` templates and ``*.entity`` value sets. A sentence drawn from
that training data should always reach its own intent; when it does not,
the install, the pipeline or the registration is broken. This module turns
those templates into rows ``ovoscope golden`` can run, for any skill,
with or without hand-written golden files.

Nothing here re-implements the OVOS template grammar:

- ``ovos_spec_tools.expand`` (OVOS-INTENT-1) expands every template, the
  same call ovos-workshop makes when it registers the intent;
- ``ovos_spec_tools.inline_keywords`` resolves ``<voc>`` references;
- ``ovos_utils.bracket_expansion.expand_slots`` fills the ``{slot}``s,
  one sample at a time, so the slot-value product (the part that explodes)
  is only built for the rows actually taken;
- ``ovos_spec_tools.LocaleResources`` finds the ``.entity``/``.voc``
  files, in subdirectories too and whatever the case of the lang folder.

A template is skipped, and reported, exactly when ovos-workshop 9.x would
drop it: when ``expand`` raises ``MalformedTemplate`` (adjacent slots, an
empty sample, a slot-only template, ...). Two more cases are reported:

- a single-branch group ``(word)``: ovos-spec-tools folds it to the bare
  branch with a warning, and ovos-workshop registers it, so its rows are
  still generated and the template is listed under ``warnings``;
- a slot-only *sample* such as ``{x}`` from ``{x} [please]``: ``expand``
  yields it without raising, but a row made of one slot value says
  nothing about the intent, so that sample is skipped.

A slot is filled from its ``.entity`` file first, then from a ``--slot``
value the caller gave, then from a small table of defaults (by the
slot's declared OVOS-INTENT-1 type, then by its name). A template with a
slot none of these fill is skipped and reported: a guessed value would
be a false miss, not a finding.

Every row is marked ``"source": "generated"`` (and ``machine_generated``,
the flag drafted rows already carry in the fleet), so a report can tell
generated rows from hand-written golden ones. They are weaker: Padatious
was trained on exactly these sentences, so a pass proves the intent is
*reachable*, not that the skill understands natural phrasing. A pass
still catches intents that never register, intent theft by another skill
or pipeline stage, and handlers that crash.

Rows per intent are capped. Templates take turns (every template line
gives one row before any gives a second), because the bugs this finds are
per line (e.g. a line ending in a slot). The same checkout always gives
the same rows, in the same order.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "SOURCE_GENERATED",
    "DEFAULT_MAX_PER_INTENT",
    "DEFAULT_SLOT_VALUES",
    "DEFAULT_TYPE_VALUES",
    "GeneratedRow",
    "SkippedTemplate",
    "GenerateResult",
    "find_locale_dir",
    "generate_rows",
    "write_golden_rows",
    "write_intent_cases",
]

#: the ``source`` value every generated row carries
SOURCE_GENERATED = "generated"
DEFAULT_MAX_PER_INTENT = 10
#: exit codes of ``ovoscope generate`` besides 0
EXIT_NOTHING_GENERATED, EXIT_EXISTS = 2, 3

#: skip reasons, stable ids a consumer can key off
REASON_ADJACENT_SLOTS = "adjacent-slots"
REASON_EMPTY_SAMPLE = "empty-sample"
REASON_SLOT_ONLY = "slot-only"
REASON_SLOT_ONLY_SAMPLE = "slot-only-sample"
REASON_UNFILLED_SLOT = "unfilled-slot"
REASON_MALFORMED = "malformed"
WARNING_SINGLE_BRANCH = "single-branch-group"

#: where a slot value came from, per row
SLOT_FROM_ENTITY = "entity"
SLOT_FROM_ARG = "argument"
SLOT_FROM_DEFAULT = "default"

#: default values by OVOS-INTENT-1 registered slot type, per primary
#: language subtag; ``"*"`` holds values that read the same everywhere.
DEFAULT_TYPE_VALUES: Dict[str, Dict[str, str]] = {
    "*": {"number": "10"},
    "en": {
        "number": "10",
        "duration": "5 minutes",
        "date": "tomorrow",
        "color": "red",
        "language": "english",
        "location": "london",
        "timezone": "london",
    },
}

#: default values by slot name, per primary language subtag. Only slots
#: whose meaning the name makes plain; a free-text slot (``{query}``,
#: ``{sentence}``) is left to ``--slot`` rather than guessed.
DEFAULT_SLOT_VALUES: Dict[str, Dict[str, str]] = {
    "*": {name: "10" for name in (
        "number", "num", "value", "quantity", "amount", "count", "n",
        "percent", "level")},
    "en": {
        "location": "london",
        "city": "london",
        "place": "london",
        "country": "france",
        "date": "tomorrow",
        "day": "tomorrow",
        "weekday": "monday",
        "time": "8 am",
        "duration": "5 minutes",
        "color": "red",
        "colour": "red",
        "language": "english",
        "lang": "english",
        "timezone": "london",
    },
}

_SLOT_RE = re.compile(r"\{([^{}]+)\}")
#: ovos-spec-tools logs a single-branch group here instead of raising
_EXPANSION_LOGGER = "ovos_spec_tools.expansion"


@dataclasses.dataclass(frozen=True)
class GeneratedRow:
    """One drafted golden row; :meth:`as_dict` is the JSONL line."""
    skill_id: str
    utterance: str
    lang: str
    intent_label: str
    template: str
    source_file: str
    slot_sources: Dict[str, str] = dataclasses.field(default_factory=dict)

    def as_dict(self) -> dict:
        row = {
            "skill_id": self.skill_id,
            "utterance": self.utterance,
            "lang": self.lang,
            "intent_label": self.intent_label,
            "intent_type": "padatious",
            "needs_manual": False,
            "machine_generated": True,
            "source": SOURCE_GENERATED,
            "template": self.template,
            "source_file": self.source_file,
        }
        if self.slot_sources:
            row["slot_sources"] = dict(self.slot_sources)
        return row


@dataclasses.dataclass(frozen=True)
class SkippedTemplate:
    """A template (or one of its samples) no row was drafted from."""
    lang: str
    intent: str
    source_file: str
    template: str
    reason: str
    detail: str

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class GenerateResult:
    """Everything one generation produced, per language."""
    skill_id: str
    rows: List[GeneratedRow] = dataclasses.field(default_factory=list)
    skipped: List[SkippedTemplate] = dataclasses.field(default_factory=list)
    warnings: List[SkippedTemplate] = dataclasses.field(default_factory=list)
    #: ``{lang: {intent: {"templates": n, "rows": n, "capped": bool}}}``
    intents: Dict[str, Dict[str, dict]] = dataclasses.field(default_factory=dict)

    def report(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "source": SOURCE_GENERATED,
            "rows": len(self.rows),
            "intents": self.intents,
            "skipped": [s.as_dict() for s in self.skipped],
            "warnings": [w.as_dict() for w in self.warnings],
        }


# ---------------------------------------------------------------------------
# Finding the resources
# ---------------------------------------------------------------------------
_NOT_SOURCE = frozenset({".git", "test", "tests", "build", "dist", ".venv",
                         "venv", "site-packages", "node_modules"})


def find_locale_dir(checkout: Path) -> Optional[Path]:
    """The skill's ``locale/`` directory: ``<checkout>/locale`` or the
    shallowest ``locale/`` inside the package, never one under tests or a
    build/venv folder."""
    checkout = Path(checkout)
    direct = checkout / "locale"
    if direct.is_dir():
        return direct
    found = [p for p in checkout.rglob("locale")
             if p.is_dir()
             and not _NOT_SOURCE.intersection(p.relative_to(checkout).parts)]
    if not found:
        return None
    return min(found, key=lambda p: (len(p.parts), str(p)))


def _lang_dirs(locale_dir: Path, langs: Optional[Sequence[str]]
               ) -> List[Tuple[str, Path]]:
    """``(standardized lang, dir)`` for each requested language, or for
    every language the skill ships when ``langs`` is empty."""
    from ovos_spec_tools import find_lang_dir, standardize_lang
    if not langs:
        return sorted((standardize_lang(p.name), p)
                      for p in locale_dir.iterdir() if p.is_dir())
    out = []
    for lang in langs:
        lang_dir = find_lang_dir(locale_dir, lang, max_distance=0)
        if lang_dir is not None:
            out.append((standardize_lang(lang), lang_dir))
    return out


def _intent_files(lang_dir: Path) -> Dict[str, List[Path]]:
    """``{intent name: [files]}`` for every ``.intent`` under ``lang_dir``,
    subdirectories included, in a stable order."""
    files: Dict[str, List[Path]] = {}
    for path in sorted(lang_dir.rglob("*.intent")):
        files.setdefault(path.stem, []).append(path)
    return files


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------
class _CaptureWarnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: List[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _classify(message: str) -> str:
    text = message.lower()
    if "adjacent slots" in text:
        return REASON_ADJACENT_SLOTS
    if "slot-only" in text:
        return REASON_SLOT_ONLY
    if "empty sample" in text or "empty group" in text:
        return REASON_EMPTY_SAMPLE
    return REASON_MALFORMED


def _expand(template: str, vocab: Mapping[str, List[str]]
            ) -> Tuple[List[str], List[str]]:
    """``(samples, single-branch warnings)``.

    Eager on purpose: ovos-workshop validates a template with ``expand`` and
    drops the whole line when any sample is malformed (``(on|)`` yields
    ``on`` before its empty sample), so a lazy expansion would draft rows
    from a line OVOS never registers. Raises ``MalformedTemplate``.
    """
    from ovos_spec_tools import expand, inline_keywords
    logger = logging.getLogger(_EXPANSION_LOGGER)
    capture = _CaptureWarnings()
    logger.addHandler(capture)
    try:
        inlined = inline_keywords(template, dict(vocab)) if "<" in template else template
        samples = expand(inlined)
    finally:
        logger.removeHandler(capture)
    warnings = [m for m in capture.messages if "single-branch" in m]
    return samples, warnings


def _spread(values: Sequence[str], k: int, offset: int) -> List[str]:
    """``k`` values spread evenly over ``values``, rotated by ``offset`` so
    successive templates do not all start on the first value."""
    n = len(values)
    if n <= k:
        picks = list(values)
    else:
        picks = [values[(i * n) // k] for i in range(k)]
    offset %= len(picks)
    return picks[offset:] + picks[:offset]


def _default_for(slot: str, slot_type: Optional[str], lang: str
                 ) -> Optional[str]:
    primary = lang.split("-")[0].lower()
    tables = []
    if slot_type:
        tables += [DEFAULT_TYPE_VALUES.get(primary, {}).get(slot_type),
                   DEFAULT_TYPE_VALUES["*"].get(slot_type)]
    tables += [DEFAULT_SLOT_VALUES.get(primary, {}).get(slot),
               DEFAULT_SLOT_VALUES["*"].get(slot)]
    return next((v for v in tables if v), None)


def _slot_values(slots: Sequence[str], lang: str,
                 entities: Mapping[str, List[str]],
                 overrides: Mapping[str, List[str]],
                 slot_types: Mapping[str, str]
                 ) -> Tuple[Dict[str, List[str]], Dict[str, str], List[str]]:
    """``(values per slot, source per slot, unfilled slots)``."""
    values: Dict[str, List[str]] = {}
    sources: Dict[str, str] = {}
    unfilled: List[str] = []
    for slot in slots:
        if entities.get(slot):
            values[slot], sources[slot] = list(entities[slot]), SLOT_FROM_ENTITY
        elif overrides.get(slot):
            values[slot], sources[slot] = list(overrides[slot]), SLOT_FROM_ARG
        else:
            default = _default_for(slot, slot_types.get(slot), lang)
            if default is None:
                unfilled.append(slot)
            else:
                values[slot], sources[slot] = [default], SLOT_FROM_DEFAULT
    return values, sources, unfilled


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def generate_rows(checkout: Path, skill_id: str,
                  langs: Optional[Sequence[str]] = None,
                  max_per_intent: int = DEFAULT_MAX_PER_INTENT,
                  slot_values: Optional[Mapping[str, List[str]]] = None,
                  ) -> GenerateResult:
    """Draft golden rows for ``skill_id`` from the templates in ``checkout``.

    Args:
        checkout: the skill's source checkout.
        skill_id: the id every row carries (the skill's entry point name).
        langs: languages to draft for; empty or ``None`` means every
            language under the skill's ``locale/``.
        max_per_intent: the most rows one intent gets, per language.
        slot_values: ``{slot: [values]}`` used for a slot that has no
            ``.entity`` file, before the default table.

    Returns:
        A :class:`GenerateResult`; its ``rows`` are empty when the skill has
        no ``.intent`` templates for the requested languages.
    """
    from ovos_spec_tools import (LocaleResources, MalformedTemplate,
                                 declared_slot_types, read_resource_file)
    from ovos_utils.bracket_expansion import expand_slots

    if max_per_intent < 1:
        raise ValueError("max_per_intent must be at least 1")
    checkout = Path(checkout).resolve()
    overrides = {k: list(v) for k, v in (slot_values or {}).items()}
    result = GenerateResult(skill_id=skill_id)
    locale_dir = find_locale_dir(checkout)
    if locale_dir is None:
        return result
    resources = LocaleResources(str(locale_dir))

    for lang, lang_dir in _lang_dirs(locale_dir, langs):
        entities = resources.entities(lang_dir.name)
        vocab = resources.vocabularies(lang_dir.name)
        per_intent: Dict[str, dict] = {}
        for intent, paths in _intent_files(lang_dir).items():
            streams = []
            n_templates = 0
            for path in paths:
                rel = path.relative_to(checkout).as_posix()
                templates = read_resource_file(path)
                slot_types = declared_slot_types(templates)
                for template in templates:
                    n_templates += 1

                    def skip(reason, detail, _t=template, _rel=rel):
                        result.skipped.append(SkippedTemplate(
                            lang, intent, _rel, _t, reason, detail))
                    try:
                        samples, warns = _expand(template, vocab)
                    except MalformedTemplate as err:
                        skip(_classify(str(err)), str(err))
                        continue
                    for warn in warns:
                        result.warnings.append(SkippedTemplate(
                            lang, intent, rel, template,
                            WARNING_SINGLE_BRANCH, warn))
                    streams.append(_fill(
                        samples, template, rel, lang, intent, skill_id,
                        entities, overrides, slot_types, max_per_intent,
                        len(streams), skip, expand_slots))
            rows, capped = _take_round_robin(streams, max_per_intent)
            result.rows.extend(rows)
            per_intent[intent] = {"templates": n_templates, "rows": len(rows),
                                  "capped": capped}
        if per_intent:
            result.intents[lang] = per_intent
    return result


def _fill(samples, template, rel, lang, intent, skill_id, entities,
          overrides, slot_types, k, index, skip, expand_slots
          ) -> Iterator[GeneratedRow]:
    """Rows for one template's samples, lazily; problems go to ``skip``."""
    reported = set()
    for sample in samples:
        slots = list(dict.fromkeys(_SLOT_RE.findall(sample)))
        if slots and not _SLOT_RE.sub("", sample).strip():
            if REASON_SLOT_ONLY_SAMPLE not in reported:
                reported.add(REASON_SLOT_ONLY_SAMPLE)
                skip(REASON_SLOT_ONLY_SAMPLE,
                     f"sample {sample!r} is only a slot; skipped")
            continue
        values, sources, unfilled = _slot_values(
            slots, lang, entities, overrides, slot_types)
        if unfilled:
            if REASON_UNFILLED_SLOT not in reported:
                reported.add(REASON_UNFILLED_SLOT)
                names = ", ".join("{%s}" % s for s in unfilled)
                skip(REASON_UNFILLED_SLOT,
                     f"sample {sample!r} (and any other sample needing "
                     f"{names}) skipped: no .entity file, --slot value or "
                     f"default for {names}")
            continue
        narrowed = {s: _spread(v, k, index) for s, v in values.items()}
        for utterance in expand_slots(sample, narrowed):
            yield GeneratedRow(
                skill_id=skill_id, utterance=" ".join(utterance.split()),
                lang=lang, intent_label=intent, template=template,
                source_file=rel, slot_sources=sources)


def _take_round_robin(streams: List[Iterator[GeneratedRow]], cap: int
                      ) -> Tuple[List[GeneratedRow], bool]:
    """Up to ``cap`` distinct rows, one per template in turn.
    ``capped`` is true when rows were left over."""
    rows: List[GeneratedRow] = []
    seen = set()
    live = list(streams)
    while live and len(rows) < cap:
        still = []
        for stream in live:
            if len(rows) >= cap:
                still.append(stream)
                continue
            for row in stream:
                if row.utterance not in seen:
                    seen.add(row.utterance)
                    rows.append(row)
                    still.append(stream)
                    break
        live = still
    capped = False
    for stream in live:
        if any(row.utterance not in seen for row in stream):
            capped = True
            break
    return rows, capped


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_golden_rows(rows: Sequence[GeneratedRow], fh) -> int:
    """Write ``rows`` as ``golden_utterances*.jsonl`` lines to ``fh``."""
    for row in rows:
        fh.write(json.dumps(row.as_dict(), ensure_ascii=False) + "\n")
    return len(rows)


def write_intent_cases(rows: Sequence[GeneratedRow], cases_dir: Path,
                       force: bool = False) -> List[Path]:
    """Write ``rows`` as ``<cases_dir>/<lang>/<Intent>.intent.test`` files
    (the :mod:`ovoscope.intent_cases` layout).

    A case file has no per-line fields, so each file opens with a comment
    saying it was generated and from which ``.intent`` file(s). An existing
    file is never overwritten unless ``force`` is set: it may hold a
    developer's hand-written cases.

    Raises:
        FileExistsError: a target file exists and ``force`` is false.
    """
    grouped: Dict[Tuple[str, str], List[GeneratedRow]] = {}
    for row in rows:
        grouped.setdefault((row.lang, row.intent_label), []).append(row)
    targets = {key: Path(cases_dir) / key[0] / f"{key[1]}.intent.test"
               for key in grouped}
    existing = [p for p in targets.values() if p.exists()]
    if existing and not force:
        raise FileExistsError(
            "refusing to overwrite existing case file(s): "
            + ", ".join(str(p) for p in existing))
    written = []
    for key, group in grouped.items():
        path = targets[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        sources = ", ".join(dict.fromkeys(r.source_file for r in group))
        lines = [
            f"# source: {SOURCE_GENERATED}, by `ovoscope generate` from {sources}",
            "# These are the skill's own training sentences, so a pass proves",
            "# the intent is reachable, not that it understands other phrasings.",
            "# Edit them and add your own before treating this file as golden.",
        ]
        lines += [r.utterance for r in group]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(path)
    return written
