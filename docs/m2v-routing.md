# End2end tests on the m2v prototype pipeline

`ovoscope.routing` runs a skill's end2end suite on the m2v prototype pipeline and gates the suite on its routing rate.

## Why a rate and not one assertion per request

The prototype pipeline builds its intent prototypes at boot from the skill's own `.intent` files, embedded with the published model `OpenVoiceOS/ovos-m2v-intents-multilingual`. The same request can reach a different intent on a different boot. A test that demands one exact intent for every request is therefore red by chance. The tally keeps two things apart:

- whether m2v routed the request, which the session measures as a rate;
- whether the skill did the right thing once routed, which each test still asserts.

## Boot

```python
from ovoscope.routing import PIPELINE, TALLY, get_prototype_minicroft

minicroft = get_prototype_minicroft(["my-skill.author"], lang="en-US")
```

`get_prototype_minicroft` calls `get_m2v_minicroft` with the published model and `classifier=False`, then loads the models before the first request. Other keyword arguments, such as `extra_pipelines` or `max_wait`, go to `get_minicroft`. `PIPELINE` is the prototype tier list, for a test that sets `session.pipeline`.

## Record each routed request

```python
TALLY.assert_routed(utterance, "my-skill.author:my_intent", fired_types)
TALLY.assert_not_routed(utterance, ["my-skill.author:my_intent"], fired_types)
```

`fired_types` are the message types the request put on the bus. Each argument can be one topic string or a collection of topics. A topic with or without the `.intent` suffix matches both forms, because older ovos-workshop releases add the suffix.

When the request reaches its intent, the call returns and the test continues with its behaviour assertions. When m2v routes it elsewhere, the call raises `unittest.SkipTest`, and the skip reason names the intents it got.

The rate is the expected routes reached, divided by those plus every misroute. A negative check that nothing claimed is not counted. A forbidden intent that fires is a misroute. A boot that routes nothing therefore cannot pass on negative checks.

Write each expected intent by the handler the test then checks. When only one handler does what the test asserts, expect only that intent. A broader set turns a misroute into a behaviour failure instead of a counted miss.

## The gate

At the end of the session the ovoscope pytest plugin prints the rate and every miss. It sets a non-zero exit status when the rate is below `ovoscope_min_routing_rate`. The default is 0.8. The value must be a number from 0 to 1, or the run stops with a usage error. A skill adds its own value to its existing pytest configuration:

```toml
[tool.pytest.ini_options]
ovoscope_min_routing_rate = 0.75
```

A session that records no check is not gated. Under `pytest-xdist` each worker hands its checks to the controller, which gates the whole run.
