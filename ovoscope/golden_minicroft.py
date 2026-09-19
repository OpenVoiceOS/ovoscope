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
  the intent;
- a machine-drafted row that misses is a coverage gap only when the name
  it expects exists in that locale's resources. A row that names a
  resource nobody ships is a defect in the row and stays a miss, with the
  missing name in the message (T-3140: nine machine-drafted rows named
  pre-rename dialogs and a per-repo runner turned every one of them into
  an expected failure, so the run was green on a name the skill had never
  shipped).

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
from typing import Dict, Iterable, List, Optional, Sequence, Union

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
#: every loaded row is a coverage gap: the corpus exists and nothing
#: in it is measurable yet. Not the same as an empty corpus (4).
EXIT_ALL_GAPS = 6
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
    #: a machine-drafted row that missed while the name it expects does
    #: exist in the locale's resources: a coverage gap, not a defect
    gap: bool = False
    #: why the row was skipped, or why a miss is a missing resource
    reason: Optional[str] = None

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


def assert_res_dir(minicroft, skill_id: str, checkout: Path,
                   root: Path) -> Path:
    """The directory the loaded skill reads its resources from.

    ovos-workshop sets ``self.res_dir = resources_dir or self.root_dir``
    (``ovos_workshop/skills/ovos.py``), and every resource loader reads
    ``res_dir``, never ``root_dir``: ``load_lang``, ``load_dialog_files``,
    ``load_vocab_files``, ``load_regex_files`` and ``find_resource`` all
    take it. A skill constructed with ``resources_dir=`` therefore ships
    its locale tree somewhere ``root_dir`` does not hold, and a bound read
    off ``root_dir`` alone finds nothing there: the skill's OWN resource
    then reads as a name nobody ships, which fails a row that should pass.

    *res_dir* gets the same two checks ``assert_root_dir`` puts on *root*,
    because it is read for the same purpose. A path outside the checkout,
    or one under an ``INSTALL_SEGMENTS`` directory inside it, is REFUSED
    rather than accepted: the names read out of such a tree cannot be shown
    to be the checkout's own source, and accepting them lets another copy's
    resource excuse a wrong gold row, which is T-3140 from a new direction.
    A refusal is loud and exits ``EXIT_ROOT_DIR``; the alternative is a
    green run on a name this checkout never shipped.

    Returns *root* unchanged when the skill sets no ``resources_dir``,
    which is every skill that does not ask for one.
    """
    loader = minicroft.plugin_skills.get(skill_id)
    instance = getattr(loader, "instance", None) if loader else None
    if instance is None:
        raise RootDirMismatch(f"skill {skill_id!r} did not load")
    res = Path(getattr(instance, "res_dir", None) or root).resolve()
    if res == root:
        return root
    checkout = Path(checkout).resolve()
    if checkout != res and checkout not in res.parents:
        raise RootDirMismatch(
            f"skill {skill_id!r} reads its resources from {res}, which is "
            f"not under the checkout {checkout}. The run would read another "
            f"tree's names, so a gold row naming a resource this checkout "
            f"does not ship would pass. Point resources_dir inside the "
            f"checkout, or measure the skill where its resources live.")
    between = res.relative_to(checkout).parts if res != checkout else ()
    installed = [p for p in between if p in INSTALL_SEGMENTS]
    if installed:
        raise RootDirMismatch(
            f"skill {skill_id!r} reads its resources from {res}, an installed "
            f"copy under {'/'.join(installed)} inside the checkout "
            f"{checkout}, not the checkout's own source. Install the checkout "
            f"editable.")
    return res


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


#: the resource kinds a gold row may name: an intent file or a dialog
RESOURCE_SUFFIXES = (".intent", ".dialog", ".voc")


class _NoPackage:
    """The type of :data:`NO_PACKAGE`. One instance, compared with ``is``.

    Deliberately not a string and deliberately truthy. An empty string would
    have read the same as ``None`` to any consumer that tested the value's
    truthiness, and the third state would have collapsed back into the second
    in silence, which is the failure this whole bound is recovering from. A
    consumer that writes ``if package:`` instead of ``if package is None:``
    now takes the name branch and raises on ``root / package``, which is loud.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "NO_PACKAGE"


#: ``own_package``'s answer meaning "the skill ships no package directory under
#: *root*": its module sits directly there, so *root* alone holds its locale
#: tree. Distinct from ``None``, which means the package could not be
#: determined at all. The two shared one value once, and that is why this bound
#: never ran in production: a skill's ``root_dir`` IS its class module's
#: directory (ovos-workshop ``skills/ovos.py``), so the relative path always
#: has exactly one part and every real skill looked undetermined.
NO_PACKAGE = _NoPackage()

#: what ``own_package`` returns and every consumer below accepts
OwnPackage = Union[str, _NoPackage, None]

#: appended to a coverage gap's reason when the row was judged under the WIDE
#: bound, so the run's own output says the bound was not applied. A gap excused
#: by a neighbour's resource is otherwise invisible in the result, and a log
#: line is not something a CI reader opens.
WIDE_BOUND_NOTE = ("judged under the wide bound: the skill's own package could "
                   "not be determined, so a neighbour's locale tree may have "
                   "answered for it")


def own_package(minicroft, skill_id: str, root: Path) -> OwnPackage:
    """Which package directory under *root* holds the skill.

    Three answers, and they are three because conflating two of them is what
    made this bound dead code:

    - a package name, when the class's module sits inside a directory under
      *root*. No production caller reaches this arm today: ``own_package`` is
      called with the ``root_dir`` ovos-workshop derives from the class
      module's own directory, so the relative path has exactly one part. The
      arm needs a caller that passes a root ABOVE that directory, and none
      does. It is kept because a future caller passing the checkout, or a
      workshop that stops deriving ``root_dir`` from the module, makes it
      live, and it is the NARROWING answer: losing it widens the bound;
    - :data:`NO_PACKAGE`, when the class's module sits directly in *root*. The
      skill ships no package directory, so *root* alone holds its locale tree
      and no child of *root* belongs to it. This is the answer for BOTH
      production layouts, because ``root_dir`` is the class module's own
      directory: in the packaged layout ``root_dir`` IS the package, and in the
      legacy top-level layout it is the checkout;
    - ``None``, when the package genuinely cannot be determined: no module in
      ``sys.modules``, no ``__file__``, or a module file outside *root*. Only
      this answer widens the bound, and the caller logs it.
    """
    loader = minicroft.plugin_skills.get(skill_id)
    instance = getattr(loader, "instance", None) if loader else None
    if instance is None:
        return None
    module = sys.modules.get(type(instance).__module__)
    filename = getattr(module, "__file__", None)
    if not filename:
        return None
    try:
        parts = Path(filename).resolve().relative_to(Path(root).resolve()).parts
    except ValueError:
        return None
    return parts[0] if len(parts) > 1 else NO_PACKAGE


def _own_locale_roots(root: Path,
                      package: OwnPackage = None) -> List[Path]:
    """The directories whose ``locale`` tree belongs to the skill at *root*.

    A skill ships its locale tree at ``<root>/locale/<lang>`` (the legacy
    top-level layout) or at ``<root>/<package>/locale/<lang>`` (the
    packaged layout), and nothing deeper belongs to it. A recursive walk
    of the checkout reads any other skill's tree as well: a ``.venv`` or a
    ``site-packages`` under the checkout makes the name set fleet-wide,
    and an installed skill's file then answers for this skill (T-3140).

    *package* is :func:`own_package`'s answer and has three cases.

    A NAME accepts that one directory beside *root*, so a second skill
    vendored as a direct child package of the checkout does not answer for
    this one. The child needs only to be a directory outside
    ``INSTALL_SEGMENTS``: ``own_package`` has already proved the skill's own
    module file lives inside it, which is stronger evidence than an
    ``__init__.py`` marker, and a PEP 420 namespace package carries no such
    marker.

    :data:`NO_PACKAGE` accepts *root* ALONE. The skill's module sits directly
    in *root*, so its locale tree is ``<root>/locale`` and no child of *root*
    is part of it. Every child package there is a different skill, which is
    the ``sibling_dialog`` hole this closes. This is the case both production
    layouts take.

    ``None`` means undetermined, and only then is the wide bound used: every
    direct child package is accepted, which over-reads rather than
    under-reads. The caller logs when it happens.
    """
    roots = [root]
    if package is NO_PACKAGE:
        return roots
    if package is not None:
        child = root / package
        if child.name not in INSTALL_SEGMENTS and child.is_dir():
            roots.append(child)
        return roots
    try:
        children = sorted(root.iterdir())
    except OSError:
        return roots
    for child in children:
        if child.name in INSTALL_SEGMENTS or not child.is_dir():
            continue
        if (child / "__init__.py").is_file():
            roots.append(child)
    return roots


def locale_resources(root: Path, lang: str,
                     package: OwnPackage = None) -> set:
    """The resource names the skill at *root* ships for *lang*.

    Every ``<base>/locale/<lang>/<name>.<kind>``, for each base
    :func:`_own_locale_roots` names, gives ``<name>``. The name is taken as
    written: a gold row that says ``who.is`` where the skill ships
    ``who_is`` names a resource that does not exist, and that is the case
    this set is read for.
    """
    names = set()
    for base in _own_locale_roots(Path(root).resolve(), package):
        folder = base / "locale" / lang
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            for suffix in RESOURCE_SUFFIXES:
                if path.name.endswith(suffix):
                    names.add(path.name[:-len(suffix)])
                    break
    return names


def _expected_name(skill_id: str, expected: str) -> str:
    """The bare resource name a row's ``expected_intent`` states."""
    name = expected.split(":", 1)[1] if expected.startswith(f"{skill_id}:") \
        else expected
    if name.endswith(".intent"):
        name = name[:-len(".intent")]
    return name


def _machine_generated(row: GoldenRow) -> bool:
    return bool(row.provenance.get("machine_generated"))


def missing_resource(row: GoldenRow, skill_id: str, root: Path,
                     known_labels: Optional[Iterable[str]] = None,
                     package: OwnPackage = None) -> Optional[str]:
    """The resource name *row* expects and the locale does not ship.

    ``None`` means the name is real: the locale ships a file under it, or
    the run itself fired that label in *this row's locale*, which proves
    the intent exists even where no file declares it (an Adapt intent
    built in code). ``known_labels`` is the caller's set for ``row.lang``
    alone: a label fired in another locale says nothing here.

    This is what separates a coverage gap from a wrong name. A
    machine-drafted row that misses while its name exists is a gap: a
    native speaker has not confirmed the phrase yet. A row that names a
    resource nobody ships is a defect in the row, whoever drafted it, and
    a runner that turns it into an expected failure keeps a wrong name
    green (T-3140: nine kab and oc-FR rows named pre-rename dialogs).
    """
    if not row.expected_intent:
        return None
    name = _expected_name(skill_id, row.expected_intent)
    if name in locale_resources(root, row.lang, package):
        return None
    forms = _label_forms(skill_id, row.expected_intent)
    if known_labels and any(f in set(known_labels) for f in forms):
        return None
    return name


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

    #: the package that belongs to the skill, read off the loaded instance
    #: once it boots; a lang holding only skipped rows leaves it unset
    skill_package: OwnPackage = None
    results: List[RowResult] = []
    #: the GoldenRow behind each RowResult, for the coverage-gap pass below
    sources: List[Optional[GoldenRow]] = []
    #: the tree the skill reads its resources from: its ``res_dir``, which
    #: is its ``root_dir`` unless it was built with ``resources_dir=``. The
    #: coverage-gap pass reads resources from this tree and no other.
    skill_root = Path(checkout).resolve()
    #: the labels the run fired, per locale. A label fired in one locale
    #: proves nothing about another: its resources are a different tree.
    fired_labels: Dict[str, set] = {}
    for lang in sorted(by_lang):
        fired_here = fired_labels.setdefault(lang, set())
        active = [r for r in by_lang[lang] if not _skipped(r)]
        for r in by_lang[lang]:
            if _skipped(r):
                results.append(RowResult(r.utterance, r.lang, r.expected_intent,
                                         [], True, r.core, 0.0, skipped=True,
                                         reason="needs_manual"))
                sources.append(None)
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
            root = assert_root_dir(mc, skill_id, checkout)
            skill_root = assert_res_dir(mc, skill_id, checkout, root)
            if skill_root != root:
                # the skill DECLARED where its resources live, which is
                # stronger evidence than any inference from the module's
                # path: that directory alone holds its locale tree, and no
                # child of it belongs to it. Same answer as NO_PACKAGE.
                skill_package = NO_PACKAGE
            else:
                # which package under the skill root holds it. NO_PACKAGE
                # means the root alone, which is what both production
                # layouts give.
                skill_package = own_package(mc, skill_id, skill_root)
            if skill_package is None:
                # the only case that widens the bound, so it is never silent:
                # every direct child package of the root answers, and another
                # skill vendored there can mask a wrong gold row (T-3140)
                LOG.warning(
                    f"could not determine the package of {skill_id!r} under "
                    f"{skill_root}; reading every child package's locale tree "
                    f"as well, so another skill vendored there may answer for "
                    f"it")
            for row in active:
                fired, handlers, latency = _fired_types(mc, skill_id, row,
                                                        session_pipeline, timeout)
                if row.expected_intent is None:
                    matched = not fired
                else:
                    forms = _label_forms(skill_id, row.expected_intent)
                    matched = any(f in forms for f in fired) or \
                        any(h in forms for h in handlers)
                fired_here.update(fired)
                fired_here.update(h for h in handlers if h)
                results.append(RowResult(row.utterance, row.lang,
                                         row.expected_intent, fired, matched,
                                         row.core, latency))
                sources.append(row)
        finally:
            mc.stop()
    _mark_coverage_gaps(results, sources, skill_id, skill_root, fired_labels,
                        skill_package)
    return results


def _mark_coverage_gaps(results: List[RowResult],
                        sources: List[Optional[GoldenRow]], skill_id: str,
                        skill_root: Path,
                        fired_labels: Dict[str, set],
                        skill_package: OwnPackage = None) -> None:
    """Split the machine-drafted misses into gaps and wrong names.

    A machine-drafted row that misses is a coverage gap only when the name
    it expects exists for its locale. Otherwise the row names a resource
    nobody ships, and it stays a miss that says which name is missing.

    ``fired_labels`` is keyed by lang, and each row reads its own locale's
    set alone. ``skill_root`` is the tree the skill READS its resources from,
    its ``res_dir``, not the checkout and not always its ``root_dir``, and
    ``skill_package`` is the one package directory under it that belongs to
    this skill: another skill's file never answers for this one, whether it
    sits in a ``.venv``, under a ``vendor`` directory, or as a sibling
    package of the checkout.
    """
    for result, row in zip(results, sources):
        if row is None or result.matched or not _machine_generated(row):
            continue
        missing = missing_resource(row, skill_id, skill_root,
                                   fired_labels.get(row.lang, set()),
                                   skill_package)
        if missing is None:
            result.gap = True
            result.reason = ("coverage-gap (machine-drafted, pending native "
                             "validation)")
            if skill_package is None:
                # the name may belong to another skill beside this one; say so
                # where the result is read, not only in the log
                result.reason += f". {WIDE_BOUND_NOTE}"
        else:
            result.reason = (f"{row.lang} ships no resource named "
                             f"{missing!r}: the row names one that does not "
                             f"exist, which is a defect in the row")


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
    # Each child runs :func:`run_rows` on one locale, so the coverage-gap
    # pass and its ``fired_labels`` are per locale here by construction.
    # That is deliberate, and it is the same rule the one-process path
    # applies with a set keyed by lang; the two paths must not drift.
    # ``gap`` and ``reason`` come back through the JSON result file:
    # ``as_dict`` writes them and ``RowResult(**r)`` reads them.
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
    scored = [r for r in results if not r.skipped and not r.gap]
    entry = {
        "gating": True,
        "preset": preset,
        "pipeline": list(pipeline) if pipeline else None,
        "total": len(scored),
        "matched": sum(1 for r in scored if r.matched),
        "core_total": sum(1 for r in scored if r.core),
        "core_matched": sum(1 for r in scored if r.core and r.matched),
        "skipped": sum(1 for r in results if r.skipped),
        "coverage_gap": sum(1 for r in results if r.gap),
        "gaps": [{"utterance": r.utterance, "lang": r.lang,
                  "expected": r.expected, "got": r.fired,
                  "reason": r.reason}
                 for r in results if r.gap],
        "failures": [{"utterance": r.utterance, "lang": r.lang,
                      "expected": r.expected, "got": r.fired,
                      "confidence": None, "core": r.core,
                      "reason": r.reason}
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
    if entry["total"] == 0 and entry["coverage_gap"] == 0:
        echo(f"ALL SKIPPED: {entry['skipped']} row(s) loaded, every one "
             f"needs_manual, nothing measured")
        if out_dir:
            for path in write_results(results, board, Path(out_dir)):
                echo(f"wrote {path}")
        return EXIT_ALL_SKIPPED
    for gap in entry["gaps"]:
        echo(f"COVERAGE GAP [{gap['lang']}] {gap['utterance']!r}: expected "
             f"{gap['expected']!r}, fired {gap['got']}. Machine-drafted, and "
             f"the name it expects does exist here")
    widened = [g for g in entry["gaps"]
               if WIDE_BOUND_NOTE in (g.get("reason") or "")]
    if widened:
        echo(f"WIDE BOUND: {len(widened)} coverage gap(s) were judged without "
             f"knowing which package is the skill's, so a second skill beside "
             f"it may have supplied the name. Treat those gaps as unproven.")
    for failure in entry["failures"]:
        line = (f"MISS [{failure['lang']}] {failure['utterance']!r}: expected "
                f"{failure['expected']!r}, fired {failure['got']}")
        if failure.get("reason"):
            line += f". {failure['reason']}"
        echo(line)
    echo(f"{entry['total']} rows, {entry['matched']} matched, "
         f"{entry['total'] - entry['matched']} failed, "
         f"{entry['skipped']} skipped (needs_manual), "
         f"{entry['coverage_gap']} coverage gap(s)")
    if entry["total"] == 0:
        echo(f"ALL GAPS: {entry['coverage_gap']} row(s) measured, every one "
             f"a coverage gap, nothing scored. The gap lines above say which "
             f"rows a native speaker must confirm.")
    if out_dir:
        for path in write_results(results, board, Path(out_dir)):
            echo(f"wrote {path}")
    if entry["total"] == 0:
        return EXIT_ALL_GAPS
    return 0 if entry["gate_passed"] else EXIT_MISS
