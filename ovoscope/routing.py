"""End2end suites on the m2v prototype pipeline, gated by a routing rate.

The m2v prototype pipeline builds its intent prototypes at boot from the
skills' own ``.intent`` files, embedded with the published model. It gives
some requests a different intent on each boot, so an end2end test that
demands one exact intent per request is red by chance. A suite on this
pipeline instead records every routing check in :data:`TALLY`:

- a request that reaches the expected intent keeps its test, and the test
  goes on to assert what the skill does;
- a request that m2v routes elsewhere skips its test, and the skip names
  the intents it got;
- at the end of the session the ovoscope pytest plugin fails the run when
  the routing rate is below the ``ovoscope_min_routing_rate`` ini value
  (default 0.8).

The rate is the expected routes reached, divided by those plus every
misroute. A negative check that nothing claimed is not counted, so a boot
that routes nothing cannot pass on negative checks alone.

Usage::

    from ovoscope.routing import TALLY, get_prototype_minicroft

    minicroft = get_prototype_minicroft(["my-skill.author"], lang="en-US")
    ...
    TALLY.assert_routed(utterance, "my-skill.author:my_intent", fired_types)
"""
from typing import Iterable, List, Optional, Set, Union
from unittest import SkipTest

from ovos_spec_tools import canonical_intent_topic

from ovoscope import (M2V_PROTOTYPE_PIPELINE, M2V_PUBLISHED_MODEL, MiniCroft,
                      get_m2v_minicroft)
from ovoscope.golden_minicroft import warm_m2v_models

__all__ = ["PIPELINE", "DEFAULT_MIN_ROUTING_RATE", "RoutingTally", "TALLY",
           "get_prototype_minicroft"]

PIPELINE: List[str] = list(M2V_PROTOTYPE_PIPELINE)
DEFAULT_MIN_ROUTING_RATE = 0.8
UNMATCHED = "ovos.intent.unmatched"

Topics = Union[str, Iterable[str]]


def get_prototype_minicroft(skill_ids: Union[List[str], str],
                            lang: Optional[str] = None,
                            **kwargs) -> MiniCroft:
    """A READY MiniCroft on the m2v prototype pipeline, its models loaded.

    The boot uses the published model with no classifier stage, so every
    label the loaded skills register from their ``.intent`` files is served
    by prototype mode. ``kwargs`` go to :func:`ovoscope.get_m2v_minicroft`
    and from there to :func:`ovoscope.get_minicroft` (``extra_pipelines``,
    ``max_wait``, ``secondary_langs``, ...).
    """
    minicroft = get_m2v_minicroft(skill_ids, model=M2V_PUBLISHED_MODEL,
                                  lang=lang, classifier=False, **kwargs)
    warm_m2v_models(minicroft)
    return minicroft


def _topics(topics: Topics) -> Set[str]:
    """Canonical topics; a single string is one topic."""
    if isinstance(topics, str):
        topics = [topics]
    return {canonical_intent_topic(t) for t in topics}


def _routed_to(fired: Set[str]) -> List[str]:
    """The fired topics that name where the request went."""
    return sorted(t for t in fired if t == UNMATCHED
                  or (":" in t and not t.startswith("recognizer_loop:")))


class RoutingTally:
    """The routing checks an end2end session made, and which went right."""

    def __init__(self):
        self.hits: List[str] = []
        self.misses: List[str] = []

    @property
    def total(self) -> int:
        return len(self.hits) + len(self.misses)

    @property
    def rate(self) -> Optional[float]:
        """Expected routes reached over those plus misroutes, or None when
        nothing was recorded."""
        return len(self.hits) / self.total if self.total else None

    def miss(self, utterance: str, detail: str) -> None:
        """Count a misroute and skip the calling test."""
        self.misses.append(f"{utterance!r}: {detail}")
        raise SkipTest(f"m2v routed {utterance!r} wrong: {detail}")

    def record(self, utterance: str, routed: bool, detail: str) -> None:
        """Count one expected route; skip the calling test when it missed."""
        if not routed:
            self.miss(utterance, detail)
        self.hits.append(utterance)

    def assert_routed(self, utterance: str, expected: Topics,
                      types: Topics) -> None:
        """``utterance`` fired one of the ``expected`` intent topics.

        ``types`` are the message types the request put on the bus. A topic
        with or without the ``.intent`` suffix of older ovos-workshop
        releases matches both forms.
        """
        wanted, fired = _topics(expected), _topics(types)
        self.record(utterance, bool(wanted & fired),
                    f"expected {sorted(wanted)}, got {_routed_to(fired)}")

    def assert_not_routed(self, utterance: str, forbidden: Topics,
                          types: Topics) -> None:
        """``utterance`` fired none of the ``forbidden`` intent topics.

        A clean result is not counted in the rate; a claimed one is a miss.
        """
        claimed = _topics(forbidden) & _topics(types)
        if claimed:
            self.miss(utterance, f"{sorted(claimed)} claimed it")

    def failure(self, min_rate: float) -> Optional[str]:
        """Why the session fails the routing gate, or None when it passes."""
        if self.rate is None or self.rate >= min_rate:
            return None
        return (f"{self.rate:.1%} of {self.total} routing checks went right "
                f"on m2v, below {min_rate:.0%}")

    def clear(self) -> None:
        self.hits.clear()
        self.misses.clear()


TALLY = RoutingTally()
