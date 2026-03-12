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
"""Bus-level coverage tracking for ovoscope end-to-end tests.

Measures two independent dimensions of coverage:

1. **Listener coverage** — which ``bus.on(msg_type, handler)`` registrations
   were actually invoked (i.e. ``bus.emit`` was called for that msg_type)
   during the test, grouped by owning skill.

2. **Emitter coverage** — which message types were:

   * *observed*: appeared in ``CaptureSession.responses``
   * *asserted*: appeared in ``End2EndTest.expected_messages``

   Both sub-metrics are tracked per-skill via ``msg.context["skill_id"]``.

Usage example::

    from ovoscope import End2EndTest

    test = End2EndTest(
        skill_ids=["my-skill.author"],
        source_message=message,
        expected_messages=[...],
        track_bus_coverage=True,
        print_bus_coverage=True,
    )
    test.execute()
    report = test.bus_coverage_report
    print(report.to_json())

See ``docs/bus-coverage.md`` for the full reference.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict, List, Optional

from ovos_bus_client.message import Message


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class HandlerEntry:
    """Coverage record for a single message-type listener registration.

    Attributes:
        msg_type: Bus message type this handler was registered for.
        handler_count: Number of distinct handlers registered for this type
            within the owning skill.
        invocation_count: Number of times ``bus.emit`` was called for this
            msg_type during the tracked test session.
        covered: ``True`` when ``invocation_count > 0``.
    """

    msg_type: str
    handler_count: int
    invocation_count: int
    covered: bool

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict.

        Returns:
            Dict with keys ``msg_type``, ``handler_count``,
            ``invocation_count``, ``covered``.
        """
        return {
            "msg_type": self.msg_type,
            "handler_count": self.handler_count,
            "invocation_count": self.invocation_count,
            "covered": self.covered,
        }


@dataclasses.dataclass
class EmitterEntry:
    """Coverage record for a single message type emitted by a skill.

    Attributes:
        msg_type: Bus message type that was emitted.
        observed_count: Times this type appeared in
            ``CaptureSession.responses``.
        asserted_count: Times this type appeared in
            ``End2EndTest.expected_messages``.
        observed: ``True`` when ``observed_count > 0``.
        asserted: ``True`` when ``asserted_count > 0``.
    """

    msg_type: str
    observed_count: int
    asserted_count: int
    observed: bool
    asserted: bool

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict.

        Returns:
            Dict with keys ``msg_type``, ``observed_count``,
            ``asserted_count``, ``observed``, ``asserted``.
        """
        return {
            "msg_type": self.msg_type,
            "observed_count": self.observed_count,
            "asserted_count": self.asserted_count,
            "observed": self.observed,
            "asserted": self.asserted,
        }


@dataclasses.dataclass
class SkillBusCoverage:
    """Bus coverage data for a single skill.

    Attributes:
        skill_id: OPM skill identifier.
        listeners: Per-msg-type listener coverage entries.
        emitters: Per-msg-type emitter coverage entries.
    """

    skill_id: str
    listeners: List[HandlerEntry] = dataclasses.field(default_factory=list)
    emitters: List[EmitterEntry] = dataclasses.field(default_factory=list)

    @property
    def listener_coverage_pct(self) -> float:
        """Return the percentage of registered listener msg_types that were invoked.

        Returns:
            Float in [0.0, 100.0].  Returns 0.0 when no listeners are registered.
        """
        if not self.listeners:
            return 0.0
        covered = sum(1 for h in self.listeners if h.covered)
        return 100.0 * covered / len(self.listeners)

    @property
    def observed_emitter_pct(self) -> float:
        """Return the percentage of emitter entries that were observed.

        Returns:
            Float in [0.0, 100.0].  Returns 0.0 when no emitters are tracked.
        """
        if not self.emitters:
            return 0.0
        observed = sum(1 for e in self.emitters if e.observed)
        return 100.0 * observed / len(self.emitters)

    @property
    def asserted_emitter_pct(self) -> float:
        """Return the percentage of emitter entries that appear in expected_messages.

        Returns:
            Float in [0.0, 100.0].  Returns 0.0 when no emitters are tracked.
        """
        if not self.emitters:
            return 0.0
        asserted = sum(1 for e in self.emitters if e.asserted)
        return 100.0 * asserted / len(self.emitters)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict.

        Returns:
            Dict with summary percentages and full ``listeners`` /
            ``emitters`` lists.
        """
        return {
            "skill_id": self.skill_id,
            "listener_coverage_pct": round(self.listener_coverage_pct, 1),
            "observed_emitter_pct": round(self.observed_emitter_pct, 1),
            "asserted_emitter_pct": round(self.asserted_emitter_pct, 1),
            "listeners": [h.to_dict() for h in self.listeners],
            "emitters": [e.to_dict() for e in self.emitters],
        }


@dataclasses.dataclass
class BusCoverageReport:
    """Aggregated bus coverage report across all skills in a test run.

    Attributes:
        skills: Per-skill coverage data, one entry per skill that had any
            listener or emitter activity.
    """

    skills: List[SkillBusCoverage] = dataclasses.field(default_factory=list)

    def summary_line(self) -> str:
        """Return per-skill single-line summaries joined by newlines.

        Suitable for inline test output (``print_bus_coverage=True``).

        Returns:
            Multi-line string, one line per skill.
        """
        lines: List[str] = []
        for skill in self.skills:
            n_l = len(skill.listeners)
            c_l = sum(1 for h in skill.listeners if h.covered)
            n_e = len(skill.emitters)
            c_obs = sum(1 for e in skill.emitters if e.observed)
            c_ass = sum(1 for e in skill.emitters if e.asserted)
            pct = f"{skill.listener_coverage_pct:.1f}%"
            lines.append(
                f"[bus-coverage] {skill.skill_id} — "
                f"listeners: {c_l}/{n_l} ({pct}) | "
                f"observed: {c_obs}/{n_e} | asserted: {c_ass}/{n_e}"
            )
        return "\n".join(lines)

    def print_report(self, verbose: bool = False) -> None:
        """Print a formatted coverage table to stdout.

        Args:
            verbose: When ``True``, print per-msg-type detail rows for every
                skill after the summary table.
        """
        print()
        print("━" * 66)
        print("Bus Coverage Report")
        print("━" * 66)
        header = f"{'Skill':<34} {'Listeners':>14}  {'Observed':>8}  {'Asserted':>8}"
        print(header)
        print("─" * 66)

        total_l = total_cl = total_e = total_obs = total_ass = 0
        for skill in self.skills:
            n_l = len(skill.listeners)
            c_l = sum(1 for h in skill.listeners if h.covered)
            n_e = len(skill.emitters)
            c_obs = sum(1 for e in skill.emitters if e.observed)
            c_ass = sum(1 for e in skill.emitters if e.asserted)
            total_l += n_l
            total_cl += c_l
            total_e += n_e
            total_obs += c_obs
            total_ass += c_ass

            pct = f"{skill.listener_coverage_pct:.1f}%"
            listener_col = f"{c_l}/{n_l}  {pct}"
            print(
                f"{skill.skill_id:<34} {listener_col:>14}  "
                f"{c_obs}/{n_e:>6}  {c_ass}/{n_e:>6}"
            )

        if self.skills:
            print("─" * 66)
            total_pct = (100.0 * total_cl / total_l) if total_l else 0.0
            total_listener_col = f"{total_cl}/{total_l}  {total_pct:.1f}%"
            print(
                f"{'TOTAL':<34} {total_listener_col:>14}  "
                f"{total_obs}/{total_e:>6}  {total_ass}/{total_e:>6}"
            )

        if verbose:
            for skill in self.skills:
                print()
                print(f"LISTENERS — {skill.skill_id}")
                for h in sorted(skill.listeners, key=lambda x: (not x.covered, x.msg_type)):
                    mark = "✓" if h.covered else "✗"
                    detail = f"{h.invocation_count} invocation(s)" if h.covered else "NOT TESTED"
                    print(f"  {mark} {h.msg_type:<50} {detail}")

                print()
                print(f"EMITTERS — {skill.skill_id}")
                for e in sorted(skill.emitters, key=lambda x: (not x.observed, x.msg_type)):
                    obs_mark = "✓" if e.observed else "✗"
                    ass_tag = "✓ asserted" if e.asserted else "✗ not asserted"
                    obs_detail = f"observed {e.observed_count}x" if e.observed else "not observed"
                    print(f"  {obs_mark} {e.msg_type:<50} {obs_detail}  {ass_tag}")

    def to_json(self) -> str:
        """Serialize the full report to a JSON string.

        Returns:
            Pretty-printed JSON with ``skills`` and ``totals`` keys.
        """
        data = {
            "skills": [s.to_dict() for s in self.skills],
            "totals": self._totals_dict(),
        }
        return json.dumps(data, indent=2)

    def _totals_dict(self) -> Dict[str, Any]:
        """Compute aggregate totals across all skills.

        Returns:
            Dict with total listener/emitter counts and percentages.
        """
        total_l = sum(len(s.listeners) for s in self.skills)
        total_cl = sum(sum(1 for h in s.listeners if h.covered) for s in self.skills)
        total_e = sum(len(s.emitters) for s in self.skills)
        total_obs = sum(sum(1 for e in s.emitters if e.observed) for s in self.skills)
        total_ass = sum(sum(1 for e in s.emitters if e.asserted) for s in self.skills)
        return {
            "listener_covered": total_cl,
            "listener_total": total_l,
            "listener_coverage_pct": round(100.0 * total_cl / total_l, 1) if total_l else 0.0,
            "observed_count": total_obs,
            "asserted_count": total_ass,
            "emitter_total": total_e,
        }


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


class BusCoverageTracker:
    """Tracks bus listener and emitter coverage for one or more test sessions.

    Call order::

        tracker = BusCoverageTracker(bus, minicroft)
        tracker.snapshot_listeners()   # after MiniCroft READY
        tracker.start_tracking()
        # ... run test / CaptureSession.capture() ...
        tracker.stop_tracking()
        tracker.record_session(session.responses, test.expected_messages)
        report = tracker.build_report()

    Multiple ``record_session`` calls accumulate data across test sessions
    before a single ``build_report`` call.

    Args:
        bus: The :class:`~ovos_utils.fakebus.FakeBus` instance in use.
        minicroft: The running :class:`~ovoscope.MiniCroft` instance.
    """

    def __init__(self, bus: Any, minicroft: Any) -> None:
        self._bus = bus
        self._minicroft = minicroft
        # skill_id -> {msg_type -> handler_count}
        self._registered: Dict[str, Dict[str, int]] = {}
        # msg_type -> invocation_count (total across all emits during tracking)
        self._invocations: Dict[str, int] = {}
        # skill_id -> {msg_type -> observed_count}
        self._observed: Dict[str, Dict[str, int]] = {}
        # skill_id -> {msg_type -> asserted_count}
        self._asserted: Dict[str, Dict[str, int]] = {}
        self._original_emit: Optional[Any] = None
        self._tracking: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot_listeners(self) -> None:
        """Introspect the FakeBus handler registry and map handlers to skills.

        Must be called **after** ``MiniCroft`` reaches READY state so that all
        skill handlers have been registered via ``bus.on(...)``.

        Handlers whose ``__self__`` is not a loaded skill instance (e.g.
        IntentService, SkillManager internals) are silently skipped.
        """
        skill_map = self._skill_instance_map()
        listener_map: Dict[str, Dict[str, int]] = {}

        for msg_type, handlers in self._get_bus_events().items():
            if not handlers:
                continue
            for handler in self._iter_handlers(handlers):
                skill_id = self._skill_id_for_handler(handler, skill_map)
                if skill_id is None:
                    continue
                if skill_id not in listener_map:
                    listener_map[skill_id] = {}
                listener_map[skill_id][msg_type] = (
                    listener_map[skill_id].get(msg_type, 0) + 1
                )

        self._registered = listener_map

    def start_tracking(self) -> None:
        """Monkey-patch ``bus.emit`` to count per-msg-type invocations.

        Each call to ``bus.emit(msg)`` increments the invocation counter for
        ``msg.msg_type``.  Call :meth:`stop_tracking` to restore the original.
        """
        if self._tracking:
            return
        original_emit = self._bus.emit
        invocations = self._invocations

        def _patched_emit(message: Any) -> None:
            msg_type = getattr(message, "msg_type", None) or getattr(message, "type", None)
            if msg_type:
                invocations[msg_type] = invocations.get(msg_type, 0) + 1
            original_emit(message)

        self._original_emit = original_emit
        self._bus.emit = _patched_emit
        self._tracking = True

    def stop_tracking(self) -> None:
        """Restore the original ``bus.emit`` and stop counting invocations."""
        if not self._tracking:
            return
        self._bus.emit = self._original_emit
        self._original_emit = None
        self._tracking = False

    def record_session(
        self,
        responses: List[Message],
        expected_messages: List[Message],
    ) -> None:
        """Accumulate observed and asserted emitter data from one test session.

        Can be called multiple times (once per ``End2EndTest.execute()`` call)
        before :meth:`build_report`.

        Args:
            responses: Messages from ``CaptureSession.responses`` (observed).
            expected_messages: Messages from ``End2EndTest.expected_messages``
                (asserted).
        """
        skill_map = self._skill_instance_map()

        # Observed: messages that actually appeared in CaptureSession
        for msg in responses:
            skill_id = self._skill_id_for_message(msg)
            if skill_id is None:
                continue
            if skill_id not in self._observed:
                self._observed[skill_id] = {}
            self._observed[skill_id][msg.msg_type] = (
                self._observed[skill_id].get(msg.msg_type, 0) + 1
            )

        # Asserted: messages listed in expected_messages
        for msg in expected_messages:
            skill_id = self._skill_id_for_message(msg)
            if skill_id is None:
                # Fall back: attribute to the first skill that already observed
                # this msg_type so the assertion still shows up in the report.
                for sid, obs in self._observed.items():
                    if msg.msg_type in obs:
                        skill_id = sid
                        break
            if skill_id is None:
                continue
            if skill_id not in self._asserted:
                self._asserted[skill_id] = {}
            self._asserted[skill_id][msg.msg_type] = (
                self._asserted[skill_id].get(msg.msg_type, 0) + 1
            )

    def build_report(self) -> BusCoverageReport:
        """Compile a :class:`BusCoverageReport` from all accumulated data.

        Returns:
            Fully populated :class:`BusCoverageReport` instance.
        """
        all_skill_ids = (
            set(self._registered)
            | set(self._observed)
            | set(self._asserted)
        )
        skills: List[SkillBusCoverage] = []

        for skill_id in sorted(all_skill_ids):
            # --- listener entries ---
            listener_entries: List[HandlerEntry] = []
            for msg_type, handler_count in sorted(
                (self._registered.get(skill_id) or {}).items()
            ):
                invocations = self._invocations.get(msg_type, 0)
                listener_entries.append(
                    HandlerEntry(
                        msg_type=msg_type,
                        handler_count=handler_count,
                        invocation_count=invocations,
                        covered=invocations > 0,
                    )
                )

            # --- emitter entries ---
            all_emitted = set(
                (self._observed.get(skill_id) or {}).keys()
            ) | set(
                (self._asserted.get(skill_id) or {}).keys()
            )
            emitter_entries: List[EmitterEntry] = []
            for msg_type in sorted(all_emitted):
                obs_count = (self._observed.get(skill_id) or {}).get(msg_type, 0)
                ass_count = (self._asserted.get(skill_id) or {}).get(msg_type, 0)
                emitter_entries.append(
                    EmitterEntry(
                        msg_type=msg_type,
                        observed_count=obs_count,
                        asserted_count=ass_count,
                        observed=obs_count > 0,
                        asserted=ass_count > 0,
                    )
                )

            skills.append(
                SkillBusCoverage(
                    skill_id=skill_id,
                    listeners=listener_entries,
                    emitters=emitter_entries,
                )
            )

        return BusCoverageReport(skills=skills)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_bus_events(self) -> Dict[str, Any]:
        """Return the raw event-name → handlers mapping from the bus.

        Tries ``bus.ee._events`` (pyee v8+) first, then ``bus._events`` as a
        fallback for older versions or custom subclasses.

        Returns:
            Dict mapping event name strings to handler containers.
        """
        ee = getattr(self._bus, "ee", None)
        if ee is not None:
            events = getattr(ee, "_events", None)
            if events is not None:
                return dict(events)
        # Fallback: FakeBus exposes handlers directly
        events = getattr(self._bus, "_events", None)
        if events is not None:
            return dict(events)
        return {}

    @staticmethod
    def _iter_handlers(handlers: Any):
        """Yield raw handler callables from a pyee handler container.

        pyee stores handlers in different container types depending on version:

        * v8 / v9: ``OrderedDict`` mapping ``{handler: handler}`` — iterate
          keys.
        * v8 with wrappers: list of ``_ListenerWrapper`` objects with a ``.fn``
          attribute.
        * Legacy: a single callable.

        Args:
            handlers: The handler container from ``bus.ee._events[msg_type]``.

        Yields:
            Unwrapped callable objects (the registered handler functions).
        """
        import collections

        # pyee v9: OrderedDict {handler: handler} — keys are the raw callables
        if isinstance(handlers, dict):
            for key in handlers.keys():
                # unwrap pyee listener wrappers if present
                yield getattr(key, "fn", key)
            return

        # Single callable (not a container)
        if callable(handlers) and not isinstance(handlers, (list, tuple)):
            yield getattr(handlers, "fn", handlers)
            return

        # List / tuple of handlers or wrappers
        try:
            it = iter(handlers)
        except TypeError:
            return
        for item in it:
            yield getattr(item, "fn", item)

    def _skill_instance_map(self) -> Dict[int, str]:
        """Build a mapping from ``id(skill_instance)`` to ``skill_id``.

        Returns:
            Dict of ``{id(skill_obj): skill_id}`` for all loaded plugin skills.
        """
        mapping: Dict[int, str] = {}
        plugin_skills: Dict[str, Any] = (
            getattr(self._minicroft, "plugin_skills", {}) or {}
        )
        for skill_id, skill_obj in plugin_skills.items():
            mapping[id(skill_obj)] = skill_id
        return mapping

    @staticmethod
    def _skill_id_for_handler(
        handler: Any,
        skill_instance_map: Dict[int, str],
    ) -> Optional[str]:
        """Attribute a bound-method handler to its owning skill.

        Args:
            handler: A callable that was registered via ``bus.on``.
            skill_instance_map: Mapping returned by :meth:`_skill_instance_map`.

        Returns:
            The ``skill_id`` string, or ``None`` if the handler does not
            belong to any loaded skill.
        """
        owner = getattr(handler, "__self__", None)
        if owner is None:
            return None
        return skill_instance_map.get(id(owner))

    @staticmethod
    def _skill_id_for_message(msg: Message) -> Optional[str]:
        """Extract ``skill_id`` from a message's context field.

        Args:
            msg: A bus :class:`~ovos_bus_client.message.Message`.

        Returns:
            The ``skill_id`` value from ``msg.context``, or ``None``.
        """
        if not msg.context:
            return None
        return msg.context.get("skill_id")
