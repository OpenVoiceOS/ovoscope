# MiniListener — Listener Pipeline Testing

`MiniListener` extends ovoscope's testing capability beyond the skill pipeline
to cover **audio transformer plugins** — the plugins that process raw audio
chunks before speech reaches the intent engine.

## Conceptual Model

Two pipeline modes are supported:

**Audio transformer testing** (e.g. ggwave):
```
Test
────
audio_bytes ──feed_audio──►  [AudioTransformersService + loaded plugins]
                                        │ (FakeBus in-process)
                         ◄──captured───┤ all emitted Messages
                                        ▼
                   assert against expected_types[]
```

**Full pipeline testing** (audio transformers → STT):
```
Test
────
WAV file / bytes
    │
    ▼ AudioTransformersService.transform()
    │
    ▼ stt_instance.execute(AudioData, language)
    │
    ▼ bus.emit("recognizer_loop:utterance")   [if non-empty]
    │
    ▼ captured Messages
```

Rather than injecting a `recognizer_loop:utterance` (as `MiniCroft` does),
`MiniListener` feeds **raw audio bytes** into `AudioTransformersService` —
`ovos_dinkum_listener/transformers.py:34` — which dispatches them to each
loaded plugin's `feed_audio_chunk()` / `feed_speech_chunk()` / `transform()`
methods.  All `Message` objects emitted on the internal `FakeBus` during that
call are captured and returned.

## Quick Start

**Audio transformer testing** (ggwave):

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

**Full pipeline testing** (STT with real WAV):

```python
from unittest.mock import MagicMock
from ovoscope.listener import get_mini_listener

stt = MagicMock()
stt.execute.return_value = "ask not what your country can do for you"

listener = get_mini_listener()
msgs = listener.listen("path/to/jfk.wav", language="en-us", stt_instance=stt)
utt = next(m for m in msgs if m.msg_type == "recognizer_loop:utterance")
assert utt.data["lang"] == "en-us"
assert "ask not" in utt.data["utterances"][0]
listener.shutdown()
```

## API Reference

### `MiniListener` — `ovoscope/listener.py:97`

| Method | Signature | Description |
|--------|-----------|-------------|
| `feed_audio(chunk)` | `(bytes) → List[Message]` | Calls `AudioTransformersService.feed_audio()` — `transformers.py:84` |
| `feed_speech(chunk)` | `(bytes) → List[Message]` | Calls `AudioTransformersService.feed_speech()` — `transformers.py:100` |
| `transform(chunk)` | `(bytes) → tuple[bytes, dict, List[Message]]` | Full transform pipeline; returns `(audio, ctx, messages)` — `transformers.py:111` |
| `listen(audio, ...)` | `(audio, language, stt_instance, ...) → List[Message]` | Full pipeline: audio → transformers → STT → utterance message |
| `shutdown()` | `() → None` | Gracefully shuts down all loaded plugins |

#### `listen()` — `ovoscope/listener.py:204`

```
listen(
    audio: bytes | str | Path,
    language: str = "en-us",
    stt_instance: Any = None,
    sample_rate: int = 16000,
    sample_width: int = 2,
) → List[Message]
```

Runs the complete listener pipeline:

1. Reads WAV file (or accepts raw bytes)
2. Passes bytes through `AudioTransformersService.transform()` — all loaded transformer plugins run
3. Converts the (possibly modified) bytes to `AudioData` via `_wav_to_audio_data()` — `listener.py:59`
4. Calls `stt_instance.execute(audio_data, language)` if provided
5. Emits `recognizer_loop:utterance` on the FakeBus if the transcript is non-empty
6. Returns all captured messages (from transformers **and** the utterance step)

`_wav_to_audio_data(audio, sample_rate, sample_width)` — `listener.py:59`:

- File path → `AudioData.from_file(path)` (handles WAV/AIFF/FLAC headers)
- Raw bytes → parses WAV header via `wave` stdlib; falls back to raw PCM if not a valid WAV

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
- Real STT models — `listen()` accepts a mock or real STT plugin, but does not load one automatically
- Full `DinkumVoiceLoop` state machine — only `AudioTransformersService`
- Real hardware audio — inject a WAV file path or raw bytes instead

For VAD/wake-word, use `FakeBus` unit tests directly.

## Cross-References

- `AudioTransformersService` — `ovos-dinkum-listener/ovos_dinkum_listener/transformers.py:34`
- `AudioData` — `ovos-plugin-manager/ovos_plugin_manager/utils/audio.py:34`
- `MiniCroft` / `get_minicroft()` — `ovoscope/docs/minicroft.md` (skill pipeline equivalent)
- Audio transformer E2E test: `Transformer plugins/ovos-audio-transformer-plugin-ggwave/test/end2end/test_ggwave_transformer.py`
- STT pipeline E2E test: `STT plugins/ovos-stt-plugin-rover/test/end2end/test_rover_listener_e2e.py`
