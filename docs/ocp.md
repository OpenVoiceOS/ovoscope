# OCP / Common Play Testing

`ovoscope.ocp` provides `OCPTest` and `assert_ocp_query_response` for
testing OCP (OpenVoiceOS Common Play) skills that handle media queries.

## OCP Message Flow

```
recognizer_loop:utterance
  → ovos.common_play.query              (broadcast to all OCP skills)
  → ovos.common_play.query.response     (skill replies with MediaEntry list)
  → ovos.common_play.start              (selected track)
```

## `OCPTest` — Declarative Style

`OCPTest` — `ocp.py:OCPTest`

```python
from ovoscope.ocp import OCPTest

result = OCPTest(
    skill_ids=["ovos-skill-youtube.openvoiceos"],
    utterance="play lofi hip hop",
    mock_responses={
        "youtube.com": {"items": [{"title": "Lofi Radio", "url": "..."}]},
    },
    expected_media=[{"title": "Lofi Radio"}],
    lang="en-US",
    timeout=20.0,
).execute()
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `skill_ids` | `List[str]` | **required** | OCP skill IDs to load. |
| `utterance` | `str` | **required** | User utterance. |
| `mock_responses` | `Dict[str, Any]` | `{}` | URL-substring → JSON response body. |
| `expected_media` | `List[Dict]` | `[]` | Partial dicts; each must match one `media_list` item. |
| `expected_stream_url` | `Optional[str]` | `None` | Substring expected in `ovos.common_play.start` URI. |
| `lang` | `str` | `"en-US"` | Language tag. |
| `timeout` | `float` | `20.0` | Max wait in seconds. |
| `patch_targets` | `List[str]` | `[]` | Additional `requests`-like modules to patch. |

## HTTP Mocking

HTTP calls are intercepted via `unittest.mock.patch` on `requests.Session.get`
and `requests.get` — `ocp.py:_build_mock_response`.

For skills using non-standard HTTP clients (e.g. `aiohttp`), pass the module
path in `patch_targets`:

```python
OCPTest(
    skill_ids=["..."],
    utterance="play jazz",
    mock_responses={"api.example.com": {"results": [...]}},
    patch_targets=["my_skill.http.aiohttp.ClientSession.get"],
).execute()
```

## `assert_ocp_query_response`

`assert_ocp_query_response` — `ocp.py:assert_ocp_query_response`

```python
from ovoscope.ocp import assert_ocp_query_response

assert_ocp_query_response(
    messages,
    min_results=1,
    media_type="audio",
    expected_media=[{"title": "My Song"}],
    stream_url_contains="cdn.example.com",
)
```

| Argument | Description |
|----------|-------------|
| `messages` | Captured message list. |
| `min_results` | Minimum `media_list` length. |
| `media_type` | All items must have this `media_type`. |
| `expected_media` | Partial-dict subset matching. |
| `stream_url_contains` | Substring in `ovos.common_play.start` URI. |
