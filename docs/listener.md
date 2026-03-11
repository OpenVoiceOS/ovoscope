# MiniListener — Listener Pipeline Testing

`MiniListener` extends ovoscope's testing capability beyond the skill pipeline
to cover **audio transformer plugins** — the plugins that process raw audio
chunks before speech reaches the intent engine.

## Conceptual Model

```
Test
────
audio_bytes ──feed_audio──►  [AudioTransformersService + loaded plugins]
                                        │ (FakeBus in-process)
                         ◄──captured───┤ all emitted Messages
                                        ▼
                   assert against expected_types[]
```

Rather than injecting a `recognizer_loop:utterance` (as `MiniCroft` does),
`MiniListener` feeds **raw audio bytes** into `AudioTransformersService` —
`ovos_dinkum_listener/transformers.py:34` — which dispatches them to each
loaded plugin's `feed_audio_chunk()` / `feed_speech_chunk()` / `transform()`
methods.  All `Message` objects emitted on the internal `FakeBus` during that
call are captured and returned.

## Quick Start

```python
import types, sys
from unittest.mock import MagicMock

# Stub native ggwave before importing the plugin
_stub = types.ModuleType("ggwave")
_stub.init = MagicMock(return_value=MagicMock())
_stub.free = MagicMock()
_stub.decode = MagicMock(return_value=b"UTT:turn on the lights")
sys.modules.setdefault("ggwave", _stub)

from ovos_audio_transformer_plugin_ggwave import GGWavePlugin
from ovoscope.listener import get_mini_listener

plugin = GGWavePlugin(config={"start_enabled": True})
listener = get_mini_listener(
    plugin_instances={"ovos-audio-transformer-plugin-ggwave": plugin}
)
msgs = listener.feed_audio(b"\x00" * 1024)
assert any(m.msg_type == "recognizer_loop:utterance" for m in msgs)
listener.shutdown()
```

## API Reference

### `MiniListener` — `ovoscope/listener.py:43`

| Method | Description |
|--------|-------------|
| `feed_audio(chunk)` | Calls `AudioTransformersService.feed_audio()` — `transformers.py:84` |
| `feed_speech(chunk)` | Calls `AudioTransformersService.feed_speech()` — `transformers.py:100` |
| `transform(chunk)` | Full transform pipeline; returns `(audio, ctx, messages)` — `transformers.py:111` |
| `shutdown()` | Gracefully shuts down all loaded plugins |

**Constructor parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `config` | `dict` | Full OVOS config with `listener.audio_transformers` key |
| `plugin_instances` | `dict[str, Any]` | Pre-instantiated plugins; bypasses OPM discovery |

### `get_mini_listener()` — `ovoscope/listener.py:133`

Factory function. Two usage modes:

**Mode A — OPM discovery** (plugin registered as entry point):
```python
listener = get_mini_listener(
    transformer_plugins=["ovos-audio-transformer-plugin-ggwave"]
)
```

**Mode B — direct injection** (bypass OPM, full control over plugin config):
```python
plugin = GGWavePlugin(config={"start_enabled": True})
listener = get_mini_listener(
    plugin_instances={"ovos-audio-transformer-plugin-ggwave": plugin}
)
```

### `ListenerTest` — `ovoscope/listener.py:181`

Declarative test runner, analogous to `End2EndTest`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `plugin_instances` | `dict` | `{}` | Pre-instantiated plugins |
| `transformer_plugins` | `list[str]` | `[]` | OPM plugin names |
| `config` | `dict` | `{}` | Full config override |
| `audio_input` | `bytes` | `b"\x00" * 1024` | Audio to inject |
| `feed_method` | `str` | `"feed_audio"` | Which method to call |
| `expected_types` | `list[str]` | `[]` | Message types that must appear |
| `forbidden_types` | `list[str]` | `[]` | Message types that must NOT appear |

`execute()` — runs the test, raises `AssertionError` on failure, returns the
captured message list on success.

## Plugin Injection vs OPM Discovery

`AudioTransformersService.load_plugins()` — `transformers.py:46` — uses
`find_audio_transformer_plugins()` from `ovos-plugin-manager` to discover
plugins by entry point.  If a plugin is registered under a legacy group (e.g.
`neon.plugin.audio` instead of `opm.plugin.audio_transformer`), or is not
installed in the test environment, OPM discovery will not find it.

Use **Mode B** (`plugin_instances`) in these cases. The plugin's behaviour
through `AudioTransformersService`'s pipeline methods is identical regardless
of how the plugin was loaded.

## What MiniListener Does NOT Cover

- VAD (Voice Activity Detection) — no voice activity detection pipeline
- Wake-word detection — no hotword engine
- STT — no speech-to-text conversion
- Full `DinkumVoiceLoop` state machine — only `AudioTransformersService`
- Real hardware audio — inject synthetic bytes instead

For those, consider unit tests with `FakeBus` directly, or extend this
framework with `MiniVAD` / `MiniSTT` equivalents (see `SUGGESTIONS.md`).

## Cross-References

- `AudioTransformersService` — `ovos-dinkum-listener/ovos_dinkum_listener/transformers.py:34`
- `MiniCroft` / `get_minicroft()` — `ovoscope/minicroft.md` (skill pipeline equivalent)
- First concrete test: `Transformer plugins/ovos-audio-transformer-plugin-ggwave/test/end2end/test_ggwave_transformer.py`
