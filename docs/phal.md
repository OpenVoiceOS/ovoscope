# PHAL Plugin Testing

`ovoscope.phal` provides `MiniPHAL` and `PHALTest` for testing PHAL
(Plugin Hardware Abstraction Layer) plugins without physical hardware.

## Why PHAL is Testable

PHAL plugins communicate **exclusively via the MessageBus**, accepting a
`bus` argument in their constructors. `MiniPHAL` injects a `FakeBus` so
plugins behave identically to a real deployment, but no hardware or OS
device access is required.

## Testable Plugins (No Hardware Required)

| Plugin | Trigger | Expected Response |
|--------|---------|-------------------|
| `ovos-PHAL-plugin-connectivity-events` | `network.connected` | `mycroft.internet.connected` |
| `ovos-PHAL-plugin-oauth` | auth-flow messages | auth-result messages |
| `ovos-PHAL-plugin-ipgeo` | `mycroft.internet.connected` | `mycroft.location.update` |
| `ovos-PHAL-plugin-system` | `system.reboot` / `system.shutdown` | confirmation messages |

## Hardware-Dependent Plugins (Out of Scope)

Plugins that require physical hardware are **not suitable** for in-process
testing and should use hardware-in-the-loop integration tests instead:

- `ovos-PHAL-plugin-alsa` — requires ALSA audio subsystem
- `ovos-PHAL-plugin-mk1` — requires Mark 1 hardware
- `ovos-PHAL-plugin-dotstar` — requires APA102 LED ring

## `MiniPHAL` — Context Manager

`MiniPHAL` — `phal.py:MiniPHAL`

```python
from ovos_utils.messagebus import Message
from ovoscope.phal import MiniPHAL

with MiniPHAL(
    plugin_ids=["ovos-PHAL-plugin-connectivity-events.openvoiceos"],
) as phal:
    phal.emit(Message("network.connected"))
    msg = phal.assert_emitted("mycroft.internet.connected", timeout=2.0)
    assert msg.data.get("connected") is True
```

### Constructor Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `plugin_ids` | `List[str]` | OPM entry-point IDs to load. |
| `plugin_instances` | `Dict[str, Any]` | Pre-built plugin instances (keyed by ID). |
| `config` | `Dict[str, Dict]` | Per-plugin config overrides. |

### Methods

| Method | Description |
|--------|-------------|
| `emit(msg, wait=0.05)` | Emit a message and briefly wait for handlers. |
| `assert_emitted(msg_type, timeout=2.0)` | Assert message type was emitted; returns the `Message`. |
| `assert_not_emitted(msg_type, wait=0.2)` | Assert message type was NOT emitted. |
| `clear_captured()` | Clear the captured message list. |

## `PHALTest` — Declarative Style

`PHALTest` — `phal.py:PHALTest`

```python
from ovos_utils.messagebus import Message
from ovoscope.phal import PHALTest

PHALTest(
    plugin_ids=["ovos-PHAL-plugin-system.openvoiceos"],
    trigger_message=Message("system.reboot"),
    expected_types=["system.reboot.confirmed"],
    forbidden_types=["system.shutdown.confirmed"],
    timeout=5.0,
).execute()
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `plugin_ids` | `List[str]` | **required** | Plugins to load. |
| `trigger_message` | `Message` | **required** | Message to emit as stimulus. |
| `expected_types` | `List[str]` | `[]` | Types that MUST appear. |
| `forbidden_types` | `List[str]` | `[]` | Types that MUST NOT appear. |
| `plugin_instances` | `Dict` | `{}` | Pre-built instances. |
| `config` | `Dict` | `{}` | Per-plugin config. |
| `timeout` | `float` | `5.0` | Wait timeout in seconds. |
