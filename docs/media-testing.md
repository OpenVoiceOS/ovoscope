# Media / OCP Testing with ovoscope

This document describes how to test `ovos-media` services — specifically the
`OCPMediaPlayer` state machine — using the harness classes provided in
`ovoscope.media`.

> **Prerequisite:** Media testing harnesses require `ovos-media` to be installed.
> Install it with: `pip install ovoscope ovos-media`

## When to Use Which Class

| Scenario | Class |
|---|---|
| Testing `OCPMediaPlayer` play/pause/stop/next/prev state machine | `OCPPlayerHarness` |
| Testing duck/unduck (volume lowering) and cork/uncork (pause on listen) | `OCPPlayerHarness` |
| Capturing and asserting OCP bus message sequences | `OCPCaptureSession` |
| Simulating a broken or unplayable stream | `MockOCPBackend.simulate_invalid_stream()` |
| Simulating end-of-track to trigger auto-advance | `MockOCPBackend.simulate_end()` |

## OCPPlayerHarness

`OCPPlayerHarness` — `ovoscope/media.py`

Wraps a real `OCPMediaPlayer` (`ovos_media.player`) with a `MockOCPBackend` on a
`FakeBus`. All heavy dependencies are patched out:

- `ovos_media.player.AudioService` — mocked; `MockOCPBackend` injected as the
  sole audio backend
- `ovos_media.player.VideoService` — mocked
- `ovos_media.player.WebService` — mocked
- `ovos_media.player.OcpMprisExporter` — mocked (no D-Bus session required)
- `ovos_media.player.GUIInterface` — mocked (exposed as `harness.gui`)
- `ovos_media.player.OCPMediaCatalog` — mocked
- `ovos_media.player.Configuration` — returns `{"media": {}}`

### Basic Usage

```python
from ovoscope.media import OCPPlayerHarness
from ovos_utils.ocp import MediaEntry, PlaybackType, PlayerState

with OCPPlayerHarness() as h:
    entry = MediaEntry(
        uri="http://example.com/song.mp3",
        playback=PlaybackType.AUDIO,
        title="Test Track",
    )
    h.play(entry)
    h.assert_player_state(PlayerState.PLAYING)
    assert h.backend.is_playing

    h.pause()
    h.assert_player_state(PlayerState.PAUSED)

    h.resume()
    h.assert_player_state(PlayerState.PLAYING)

    h.stop()
    h.assert_player_state(PlayerState.STOPPED)
```

### Queue Navigation

```python
from ovoscope.media import OCPPlayerHarness
from ovos_utils.ocp import MediaEntry, PlaybackType, PlayerState
from ovos_bus_client.message import Message

with OCPPlayerHarness() as h:
    track1 = MediaEntry(uri="http://example.com/1.mp3",
                        playback=PlaybackType.AUDIO)
    track2 = MediaEntry(uri="http://example.com/2.mp3",
                        playback=PlaybackType.AUDIO)

    # Emit play with a playlist so the queue has two tracks
    h.bus.emit(Message("ovos.common_play.play", {
        "media": track1.as_dict,
        "playlist": [track1.as_dict, track2.as_dict],
    }))
    import time; time.sleep(0.05)

    h.assert_now_playing_uri("http://example.com/1.mp3")
    h.next_track()
    h.assert_now_playing_uri("http://example.com/2.mp3")
```

### Duck / Unduck

```python
from ovoscope.media import OCPPlayerHarness
from ovos_utils.ocp import MediaEntry, PlaybackType, PlayerState

with OCPPlayerHarness() as h:
    entry = MediaEntry(uri="http://example.com/song.mp3",
                       playback=PlaybackType.AUDIO)
    h.play(entry)
    h.duck()   # recognizer_loop:audio_output_start — lowers volume
    h.unduck() # recognizer_loop:audio_output_end — restores volume
```

### Simulating Stream End

```python
from ovoscope.media import OCPPlayerHarness
from ovos_utils.ocp import MediaEntry, MediaState, PlaybackType

with OCPPlayerHarness() as h:
    entry = MediaEntry(uri="http://example.com/song.mp3",
                       playback=PlaybackType.AUDIO)
    h.play(entry)
    h.simulate_track_end()  # backend emits END_OF_MEDIA
    # Player auto-advances or stops depending on queue + autoplay config
```

## OCPCaptureSession

`OCPCaptureSession` — `ovoscope/media.py`

Captures all `ovos.common_play.*` and `ovos.audio.*` bus messages during a
block of code and lets you assert that specific message types appeared in order.

```python
from ovoscope.media import OCPPlayerHarness, OCPCaptureSession
from ovos_utils.ocp import MediaEntry, PlaybackType

with OCPPlayerHarness() as h:
    entry = MediaEntry(uri="http://example.com/song.mp3",
                       playback=PlaybackType.AUDIO)
    with OCPCaptureSession(h.bus) as session:
        h.play(entry)

    # Check that player.state was announced after play
    session.assert_sequence("ovos.common_play.player.state")
```

### Custom Prefixes

```python
from ovoscope.media import OCPCaptureSession

with OCPPlayerHarness() as h:
    with OCPCaptureSession(h.bus,
                           track_prefixes=["ovos.common_play.player."]) as s:
        h.play(entry)
    print(s.message_types)  # ['ovos.common_play.player.state']
```

## API Reference

### MockOCPBackend

`MockOCPBackend` — `ovoscope/media.py`

| Attribute / Method | Type | Description |
|---|---|---|
| `played_uris` | `List[str]` | All URIs passed to `add_list()` or `load_track()` |
| `is_playing` | `bool` | True after `play()`, False after `stop()` |
| `is_paused` | `bool` | True after `pause()`, False after `resume()` |
| `current_uri` | `Optional[str]` | Most recently loaded URI |
| `namespace` | `str` | Backend namespace string (default `"audio"`) |
| `stop()` | `bool` | Always returns `True` (required by BaseMediaService) |
| `simulate_end()` | `None` | Emit `END_OF_MEDIA` on the bus |
| `simulate_invalid_stream()` | `None` | Emit `INVALID_MEDIA` on the bus |
| `reset()` | `None` | Clear all recorded state |

### OCPPlayerHarness

`OCPPlayerHarness` — `ovoscope/media.py`

**Control methods** (each emits the corresponding bus message + `time.sleep(0.05)`):

| Method | Bus message emitted |
|---|---|
| `play(track: MediaEntry)` | `ovos.common_play.play` |
| `pause()` | `ovos.common_play.pause` |
| `resume()` | `ovos.common_play.resume` |
| `stop()` | `ovos.common_play.stop` |
| `next_track()` | `ovos.common_play.next` |
| `prev_track()` | `ovos.common_play.previous` |
| `duck()` | `recognizer_loop:audio_output_start` |
| `unduck()` | `recognizer_loop:audio_output_end` |
| `simulate_track_end()` | `ovos.common_play.media.state` END_OF_MEDIA |
| `simulate_invalid_stream()` | `ovos.common_play.media.state` INVALID_MEDIA |

**Assertion helpers:**

| Method | Description |
|---|---|
| `assert_player_state(state)` | Raise if `player.state != state` |
| `assert_media_state(state)` | Raise if `player.media_state != state` |
| `assert_backend_playing()` | Raise if `backend.is_playing` is False |
| `assert_backend_paused()` | Raise if `backend.is_paused` is False |
| `assert_backend_stopped()` | Raise if `is_playing` or `is_paused` is True |
| `assert_now_playing_uri(uri)` | Raise if `now_playing.uri != uri` |

**Exposed attributes:**

| Attribute | Type | Description |
|---|---|---|
| `player` | `OCPMediaPlayer` | Real player instance |
| `bus` | `FakeBus` | Shared in-process bus |
| `backend` | `MockOCPBackend` | Injected mock audio backend |
| `gui` | `MagicMock` | Mocked GUIInterface |

### OCPCaptureSession

`OCPCaptureSession` — `ovoscope/media.py`

| Method / Property | Description |
|---|---|
| `start()` / `stop()` | Subscribe/unsubscribe from FakeBus |
| `__enter__` / `__exit__` | Context manager interface |
| `messages` | List of captured `Message` objects |
| `message_types` | List of captured `msg_type` strings |
| `assert_sequence(*types)` | Assert types appear in order as a subsequence |

Default `track_prefixes` captures: `"ovos.common_play."`, `"ovos.audio."`.

## Limitations

- **No real audio**: `MockOCPBackend` never plays audio. Use `simulate_end()` to
  trigger end-of-track logic.
- **No MPRIS**: `OcpMprisExporter` is mocked out — MPRIS D-Bus integration is
  not exercised.
- **No GUI rendering**: `GUIInterface` is a `MagicMock`. Test GUI calls via
  `harness.gui.show_media_player.assert_called_with(...)`.
- **No VideoService / WebService**: Only audio playback (`PlaybackType.AUDIO`)
  is wired with a real mock backend.
- **FakeBus is synchronous**: Handlers run in the same thread that calls
  `bus.emit()`. The `time.sleep(0.05)` in control methods is sufficient for
  synchronous delivery; async or threaded handlers may need explicit waits.

## Cross-References

- `OCPMediaPlayer` — `ovos-media/ovos_media/player.py`
- `BaseMediaService` — `ovos-media/ovos_media/media_backends/base.py`
- `AudioBackend` (base class) — `ovos_plugin_manager.templates.audio.AudioBackend`
- `MediaEntry`, `PlayerState`, `MediaState` — `ovos_utils.ocp`
- `MockAudioBackend` / `AudioServiceHarness` (audio pattern) — `ovoscope/audio.py`
- End-to-end tests — `ovos-media/test/end2end/test_ocp_player.py`
