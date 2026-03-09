# CaptureSession

`CaptureSession` subscribes to all messages on the `FakeBus` and records them during a single test interaction. It handles synchronous responses (ordered, from the intent pipeline) and asynchronous responses (from external threads, unordered).

## Class: `CaptureSession`

```python
from ovoscope import CaptureSession
```

A `dataclass` that wraps a `MiniCroft` and manages message collection for one test interaction.

### Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `minicroft` | `MiniCroft` | required | The runtime to capture from |
| `responses` | `list[Message]` | `[]` | Ordered synchronous messages captured |
| `async_responses` | `list[Message]` | `[]` | Async messages (arrive from external threads, unordered) |
| `eof_msgs` | `list[str]` | `["ovos.utterance.handled"]` | Message types that signal end of interaction |
| `ignore_messages` | `list[str]` | `["ovos.skills.settings_changed"]` | Message types to discard |
| `async_messages` | `list[str]` | `[]` | Message types to route to `async_responses` instead |
| `done` | `threading.Event` | — | Set when an EOF message is received |

### Methods

#### `capture(source_message, timeout=20)`

Emits `source_message` on the bus and waits for an EOF message (or timeout). Subsequent calls on the same session accumulate into `responses`.

```python
capture = CaptureSession(croft, eof_msgs=["ovos.utterance.handled"])
capture.capture(utterance_msg, timeout=10)
```

#### `finish() -> list[Message]`

Signals end of capture, unsubscribes from the bus, and returns the collected `responses`.

---

## Message Routing

Messages are sorted into three buckets on arrival:

```
incoming message
        │
        ├─ msg_type in async_messages?  → async_responses (unordered)
        ├─ msg_type in ignore_messages? → discarded
        └─ otherwise                   → responses (ordered)

eof_msgs trigger done.set() → capture.wait() returns
```

### Default ignored messages

```python
DEFAULT_IGNORED = ["ovos.skills.settings_changed"]
```

### Default GUI ignored (when `ignore_gui=True` on `End2EndTest`)

```python
GUI_IGNORED = [
    "gui.clear.namespace",
    "gui.value.set",
    "mycroft.gui.screen.close",
    "gui.page.show",
]
```

These are excluded by default because GUI namespace updates are frequent and rarely the focus of skill logic tests.

---

## Direct Usage

`CaptureSession` can be used without `End2EndTest` for lower-level scenarios:

```python
from ovoscope import get_minicroft, CaptureSession
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

croft = get_minicroft(["skill-weather.openvoiceos"])

session = Session("test-123")
utterance = Message(
    "recognizer_loop:utterance",
    {"utterances": ["what is the weather?"], "lang": "en-us"},
    {"session": session.serialize(), "source": "A", "destination": "B"},
)

capture = CaptureSession(croft)
capture.capture(utterance, timeout=15)
messages = capture.finish()

for msg in messages:
    print(msg.msg_type, msg.data)

croft.stop()
```

---

## Multi-turn Capture

Emit multiple source messages into the same `CaptureSession` to simulate a multi-turn conversation. The session from the last received message is propagated into each subsequent source message:

```python
capture = CaptureSession(croft, eof_msgs=["ovos.utterance.handled"])

capture.capture(first_utterance, timeout=10)
# inject session from last received message into follow-up
follow_up.context["session"] = capture.responses[-1].context["session"]
capture.capture(follow_up, timeout=10)

all_messages = capture.finish()
```

`End2EndTest` does this automatically when `source_message` is a list.
