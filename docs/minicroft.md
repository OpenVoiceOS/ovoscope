# MiniCroft
`MiniCroft` is a minimal, in-process OVOS Core that loads real skill plugins and runs the full intent pipeline on a `FakeBus`. It is the execution engine behind every OvoScope test.
## Class: `MiniCroft`
```python
from ovoscope import MiniCroft
```
Subclass of `ovos_core.skill_manager.SkillManager`. Replaces the real WebSocket bus with `FakeBus`, disables components not needed for testing, and only loads the skills you specify.
### Constructor
```python
MiniCroft(
    skill_ids: list[str],
    enable_installer: bool = False,
    enable_intent_service: bool = True,
    enable_event_scheduler: bool = False,
    enable_file_watcher: bool = False,
    enable_skill_api: bool = True,
    extra_skills: dict[str, OVOSSkill] | None = None,
    isolate_config: bool = True,
    default_pipeline: list[str] | None = DEFAULT_TEST_PIPELINE,
    lang: str | None = None,
    secondary_langs: list[str] | None = None,
    *args, **kwargs,
)
```
| Parameter | Default | Description |
|---|---|---|
| `skill_ids` | required | Skill plugin IDs to load (from installed entry points) |
| `enable_installer` | `False` | Enable the runtime pip installer service |
| `enable_intent_service` | `True` | Enable intent matching pipeline |
| `enable_event_scheduler` | `False` | Enable scheduled event service |
| `enable_file_watcher` | `False` | Enable settings file watcher |
| `enable_skill_api` | `True` | Enable skill API exposure |
| `extra_skills` | `None` | Inject skill instances directly (useful for testing a skill class before packaging) |
| `isolate_config` | `True` | Clear user XDG configs so tests are reproducible |
| `default_pipeline` | `DEFAULT_TEST_PIPELINE` | Override the session pipeline for deterministic intent matching |
| `lang` | `None` | Override the system default language (`Configuration()["lang"]`). Patched before Adapt/Padatious init so vocab is registered for this language. |
| `secondary_langs` | `None` | Set `Configuration()["secondary_langs"]`. Adapt and Padatious create per-language engines for each language in this list, enabling multilingual intent matching. |
### Key attributes
| Attribute | Type | Description |
|---|---|---|
| `bus` | `FakeBus` | The in-process message bus |
| `boot_messages` | `list[Message]` | All messages captured during startup |
| `status` | `ProcessState` | Current lifecycle state |
### `MiniCroft.run()`
Loads plugins and marks the runtime as ready. Called internally by `start()`. Does not block — returns after all skills are loaded.
### `MiniCroft.stop()`
Shuts down skills and closes the bus.
---
## Factory: `get_minicroft()`
```python
from ovoscope import get_minicroft
croft = get_minicroft(
    skill_ids: list[str] | str,
    **kwargs  # forwarded to MiniCroft constructor
)
```
Creates, starts, and waits for a `MiniCroft` to reach `READY` state. Returns the ready instance.
```python
croft = get_minicroft(["skill-weather.openvoiceos", "skill-timer.openvoiceos"])
# croft.status.state == ProcessState.READY
```
---
## Injecting Skills Under Test
To test a skill class that isn't installed as a plugin, inject it directly via `extra_skills`:
```python
from my_skill import MySkill
croft = get_minicroft(
    skill_ids=[],
    extra_skills={"my-skill.test": MySkill},
)
```
The skill ID key must match what the skill would normally register under.
---
## Multilingual Testing
By default, Adapt and Padatious only register vocab/intents for the system's configured default language. To test skills in other languages, pass `secondary_langs`:
```python
croft = get_minicroft(
    ["my-skill.openvoiceos"],
    secondary_langs=["pt-PT", "de-DE", "es-ES"],
)
```
This patches `Configuration()["secondary_langs"]` before `IntentService` initializes, so Adapt creates per-language engines and registers vocab from all locale directories.
To also change the primary language:
```python
croft = get_minicroft(
    ["my-skill.openvoiceos"],
    lang="pt-PT",
    secondary_langs=["en-US", "de-DE"],
)
```
---
## Boot Sequence
On startup, MiniCroft captures all messages emitted during skill loading into `boot_messages`. These can be asserted in `End2EndTest.expected_boot_sequence`. The typical boot sequence includes:
1. `mycroft.skills.train` — intent pipeline training request
2. `mycroft.skills.initialized` — skills initialized
3. `mycroft.skills.ready` — skills service ready
4. `mycroft.ready` — all core services ready
Skills that participate in `converse` or `fallback` registration also emit messages during boot (e.g. `ovos.skills.fallback.register`).
