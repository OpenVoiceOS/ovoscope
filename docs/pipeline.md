# Pipeline Plugin Testing

`ovoscope.pipeline` provides `PipelineHarness` for testing intent / pipeline
plugins in isolation — no skill is needed.

## What Is Tested

Pipeline plugins (Adapt, Padatious, Padacioso, OCP, etc.) match utterances to
intents. `PipelineHarness` loads the specified stages on a `MiniCroft` that
has no skills, so only the pipeline matching logic is exercised.

## `PipelineHarness` — Context Manager

`PipelineHarness` — `pipeline.py:PipelineHarness`

```python
from ovoscope.pipeline import PipelineHarness

with PipelineHarness(
    pipeline=["ovos-adapt-pipeline-plugin.openvoiceos"],
    lang="en-US",
) as harness:
    msg = harness.assert_matches("turn on the kitchen lights")
    harness.assert_no_match("garbled nonsense xyz 123")
```

### Constructor Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `pipeline` | `List[str]` | `[]` | Pipeline stage IDs to load. |
| `pipeline_config` | `Dict[str, Dict]` | `{}` | Per-stage config overrides. |
| `lang` | `str` | `"en-US"` | Language tag. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `match(utterance, timeout=5.0)` — `ovoscope/pipeline.py:135` | `Optional[Message]` | Send utterance; return matched `Message` or `None` if no pipeline stage matched within `timeout` seconds. |
| `assert_matches(utterance, intent_type=None, timeout=5.0)` — `ovoscope/pipeline.py:183` | `Message` | Assert at least one pipeline stage matches. Raises `AssertionError` if no match. If `intent_type` is provided, the matched message's `msg_type` must **contain** `intent_type` as a substring (case-sensitive). |
| `assert_no_match(utterance, timeout=2.0)` — `ovoscope/pipeline.py:213` | `None` | Assert the utterance is NOT matched by any loaded stage within `timeout` seconds. Raises `AssertionError` if a match is found. |

#### `assert_matches(intent_type=...)` semantics

`intent_type` is a **substring** check on the matched message's `msg_type`:

```python
# Pass: msg_type "padatious:0.95:LightsOnIntent" contains "LightsOnIntent"
msg = harness.assert_matches("turn on the lights", intent_type="LightsOnIntent")

# Pass: no intent_type check — any match accepted
msg = harness.assert_matches("turn on the lights")

# Fail: "LightsOffIntent" not in "padatious:0.95:LightsOnIntent"
msg = harness.assert_matches("turn on the lights", intent_type="LightsOffIntent")
# → AssertionError: Expected intent type to contain 'LightsOffIntent', got '...'
```

## Implementation Note

`PipelineHarness.__enter__` — `pipeline.py:PipelineHarness.__enter__` creates
a `MiniCroft` with `skill_ids=[]` and the specified pipeline. Intent-matched
messages are captured via a `threading.Event` subscription on
`intent.service.skills.activated`.
