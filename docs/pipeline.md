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
| `match(utterance, timeout=5.0)` | `Optional[Message]` | Send utterance; return matched message or `None`. |
| `assert_matches(utterance, intent_type=None, timeout=5.0)` | `Message` | Assert match; optionally check intent type substring. |
| `assert_no_match(utterance, timeout=2.0)` | `None` | Assert the utterance is NOT matched. |

## Implementation Note

`PipelineHarness.__enter__` — `pipeline.py:PipelineHarness.__enter__` creates
a `MiniCroft` with `skill_ids=[]` and the specified pipeline. Intent-matched
messages are captured via a `threading.Event` subscription on
`intent.service.skills.activated`.
