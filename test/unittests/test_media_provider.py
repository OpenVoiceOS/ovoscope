"""Tests for ovoscope.media_provider.MediaProviderHarness.

The harness is duck-typed, so these tests use a dependency-free ``_DummyProvider``
(no mediavocab / ovos-plugin-manager import) and ``SimpleNamespace`` stand-ins for
``Signals`` / ``QueryContext`` / ``Release``.
"""
import types

import pytest

from ovoscope import MediaProviderHarness
from ovoscope.media_provider import DEFAULT_GROUP


# --------------------------------------------------------------------------
# duck-typed fixtures (no real mediavocab / opm types)
# --------------------------------------------------------------------------

def _signals(title="x", medium="music", artist=None):
    return types.SimpleNamespace(title=title, medium=medium, artist=artist)


def _context(supported_playback_types=None, blocked_genres=None):
    return types.SimpleNamespace(
        supported_playback_types=supported_playback_types or set(),
        blocked_genres=blocked_genres or set(),
    )


def _release(uri, title="T", mc=0.5):
    return types.SimpleNamespace(
        uri=uri, match_confidence=mc,
        work=types.SimpleNamespace(title=title),
    )


class _DummyProvider:
    """Minimal MediaProvider look-alike: serves music, returns library:// uris."""

    name = "dummy"

    def __init__(self, config=None):
        self.config = config or {}
        self._api = None
        self._served = {"music", "radio"}

    def is_available(self):
        return self._api is not None

    def serves(self, signals, context=None):
        if getattr(signals, "medium", None) not in self._served:
            return False
        if context is not None:
            spt = getattr(context, "supported_playback_types", set())
            if spt and "audio" not in spt:
                return False
        return True

    def search(self, signals, lang="en-us"):
        if self._api is None:
            return []
        return [_release("library://track/1", "Hit", 0.9),
                _release("library://track/2", "Miss", 0.3)]

    def search_safe(self, signals, context=None, lang="en-us"):
        try:
            return self.search(signals, lang=lang)
        except Exception:
            return []

    def featured_media(self, lang="en-us"):
        return [_release("library://track/3", "Featured", 0.0)]


class _ExplodingProvider(_DummyProvider):
    def search(self, signals, lang="en-us"):
        raise RuntimeError("backend exploded")


def _harness(mock_api="client", provider_cls=_DummyProvider):
    return MediaProviderHarness.from_class(
        provider_cls, config={"url": "http://x"}, mock_api=mock_api)


# --------------------------------------------------------------------------
# from_class + injection
# --------------------------------------------------------------------------

def test_from_class_instantiates_and_injects_api():
    sentinel = object()
    h = _harness(mock_api=sentinel)
    assert isinstance(h.provider, _DummyProvider)
    assert h.provider._api is sentinel
    assert h.api is sentinel
    assert h.provider.config == {"url": "http://x"}


def test_from_class_custom_api_attr():
    sentinel = object()
    h = MediaProviderHarness.from_class(_DummyProvider, mock_api=sentinel,
                                        api_attr="config")
    assert h.provider.config is sentinel


def test_is_available_reflects_injected_client():
    assert _harness(mock_api="client").is_available() is True
    assert MediaProviderHarness.from_class(_DummyProvider).is_available() is False


# --------------------------------------------------------------------------
# routing / serves drivers + asserts
# --------------------------------------------------------------------------

def test_serves_and_assert_routes():
    h = _harness()
    assert h.serves(_signals(medium="music")) is True
    h.assert_routes(_signals(medium="music"))
    h.assert_routes(_signals(medium="music"),
                    _context(supported_playback_types={"audio"}))


def test_assert_not_routes_unserved_medium():
    h = _harness()
    assert h.serves(_signals(medium="movie")) is False
    h.assert_not_routes(_signals(medium="movie"))


def test_assert_not_routes_video_only_device():
    h = _harness()
    h.assert_not_routes(_signals(medium="music"),
                        _context(supported_playback_types={"video"}))


def test_assert_routes_raises_when_not_served():
    h = _harness()
    with pytest.raises(AssertionError):
        h.assert_routes(_signals(medium="movie"))


# --------------------------------------------------------------------------
# search / search_safe drivers + playable asserts
# --------------------------------------------------------------------------

def test_search_safe_returns_playables():
    h = _harness()
    results = h.assert_returns_playables(_signals())
    assert [r.work.title for r in results] == ["Hit", "Miss"]
    assert all(r.uri.startswith("library://") for r in results)


def test_search_safe_swallows_backend_error():
    h = _harness(provider_cls=_ExplodingProvider)
    assert h.search_safe(_signals()) == []


def test_assert_returns_playables_fails_on_empty():
    h = MediaProviderHarness.from_class(_DummyProvider)  # no api -> search returns []
    with pytest.raises(AssertionError):
        h.assert_returns_playables(_signals())


def test_assert_returns_playables_fails_on_bad_confidence():
    class _BadProvider(_DummyProvider):
        def search(self, signals, lang="en-us"):
            return [_release("library://track/9", "Bad", mc=5.0)]  # out of [0,1]

    h = _harness(provider_cls=_BadProvider)
    with pytest.raises(AssertionError):
        h.assert_returns_playables(_signals())


def test_featured_media():
    h = _harness()
    feats = h.featured_media()
    assert [r.work.title for r in feats] == ["Featured"]


# --------------------------------------------------------------------------
# from_entrypoint (monkeypatched discovery)
# --------------------------------------------------------------------------

def _fake_entry_points(monkeypatch, eps):
    monkeypatch.setattr("ovoscope.media_provider.entry_points",
                        lambda group=None: eps)


def test_from_entrypoint_discovers_and_loads(monkeypatch):
    ep = types.SimpleNamespace(name="dummy", load=lambda: _DummyProvider)
    _fake_entry_points(monkeypatch, [ep])

    h = MediaProviderHarness.from_entrypoint("dummy", config={"url": "u"},
                                             mock_api="client")
    assert isinstance(h.provider, _DummyProvider)
    assert h.provider._api == "client"
    assert h.entrypoint_name == "dummy"
    assert h.entrypoint_group == DEFAULT_GROUP
    h.assert_entrypoint_registered()  # "dummy" present in the patched group


def test_from_entrypoint_missing_raises(monkeypatch):
    _fake_entry_points(monkeypatch, [])
    with pytest.raises(AssertionError):
        MediaProviderHarness.from_entrypoint("nope")


def test_from_entrypoint_ambiguous_raises(monkeypatch):
    ep1 = types.SimpleNamespace(name="dummy", load=lambda: _DummyProvider)
    ep2 = types.SimpleNamespace(name="dummy", load=lambda: _DummyProvider)
    _fake_entry_points(monkeypatch, [ep1, ep2])
    with pytest.raises(AssertionError):
        MediaProviderHarness.from_entrypoint("dummy")


def test_assert_entrypoint_registered_without_name_raises():
    h = MediaProviderHarness.from_class(_DummyProvider)  # no entrypoint name
    with pytest.raises(AssertionError):
        h.assert_entrypoint_registered()
