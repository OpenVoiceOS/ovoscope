# Pre-release quirks

Behavior changes since the last stable release, newest first. This file is
reset at each stable release.

## next alpha

- `intent_cases` now asserts the OVOS-INTENT-4 canonical (suffixless) intent
  id: matcher plugins (ovos-padatious 2.0+) fold the legacy `<file>.intent`
  suffix off at registration, so the expected dispatch topic is
  `<skill_id>:<IntentName>`, not `<skill_id>:<IntentName>.intent`. Case files
  keep their `<Intent>.intent.test` naming; suffixed entries in
  `known_intents` and `handlers` are still accepted and folded the same way,
  so existing suites keep working unchanged.
