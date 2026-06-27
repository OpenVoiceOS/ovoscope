# Changelog

## [1.0.2a1](https://github.com/OpenVoiceOS/ovoscope/tree/1.0.2a1) (2026-06-27)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/1.0.1a1...1.0.2a1)

**Merged pull requests:**

- fix: MockTTS destructor must not stop the shared playback thread [\#100](https://github.com/OpenVoiceOS/ovoscope/pull/100) ([JarbasAl](https://github.com/JarbasAl))

## [1.0.1a1](https://github.com/OpenVoiceOS/ovoscope/tree/1.0.1a1) (2026-06-27)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/1.0.0a1...1.0.1a1)

**Merged pull requests:**

- fix: guard None blacklisted\_skills/intents in final-session check [\#98](https://github.com/OpenVoiceOS/ovoscope/pull/98) ([JarbasAl](https://github.com/JarbasAl))

## [1.0.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/1.0.0a1) (2026-06-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.22.1a1...1.0.0a1)

**Breaking changes:**

- feat!: audio harness on OVOS spec bus namespace [\#92](https://github.com/OpenVoiceOS/ovoscope/pull/92) ([JarbasAl](https://github.com/JarbasAl))

## [0.22.1a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.22.1a1) (2026-06-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.22.0a1...0.22.1a1)

**Merged pull requests:**

- fix: pytest 9 compatibility for the pytest11 plugin [\#88](https://github.com/OpenVoiceOS/ovoscope/pull/88) ([JarbasAl](https://github.com/JarbasAl))

## [0.22.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.22.0a1) (2026-06-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.21.1a1...0.22.0a1)

**Merged pull requests:**

- feat: stream audio frames through MiniListener for multi-frame decoders [\#86](https://github.com/OpenVoiceOS/ovoscope/pull/86) ([JarbasAl](https://github.com/JarbasAl))

## [0.21.1a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.21.1a1) (2026-06-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.21.0a1...0.21.1a1)

**Merged pull requests:**

- fix: repair ovoscope record in-process path \(default\_pipeline kwarg + from\_message skill\_ids\) [\#85](https://github.com/OpenVoiceOS/ovoscope/pull/85) ([JarbasAl](https://github.com/JarbasAl))

## [0.21.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.21.0a1) (2026-06-25)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.20.0a1...0.21.0a1)

**Merged pull requests:**

- feat: export ovos-media OCP harness from the package + add \[media\] extra [\#89](https://github.com/OpenVoiceOS/ovoscope/pull/89) ([JarbasAl](https://github.com/JarbasAl))

## [0.20.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.20.0a1) (2026-06-24)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.19.4a1...0.20.0a1)

**Merged pull requests:**

- feat: assert\_template\_shown for SYSTEM\_\* GUI templates [\#83](https://github.com/OpenVoiceOS/ovoscope/pull/83) ([JarbasAl](https://github.com/JarbasAl))

## [0.19.4a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.19.4a1) (2026-06-17)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.19.3a1...0.19.4a1)

**Merged pull requests:**

- fix\(tts-intelligibility\): normalise rendered audio to 16kHz mono before STT [\#81](https://github.com/OpenVoiceOS/ovoscope/pull/81) ([JarbasAl](https://github.com/JarbasAl))

## [0.19.3a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.19.3a1) (2026-06-17)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.19.2a1...0.19.3a1)

**Merged pull requests:**

- fix\(tts-intelligibility\): transcode non-WAV engine output before scoring [\#79](https://github.com/OpenVoiceOS/ovoscope/pull/79) ([JarbasAl](https://github.com/JarbasAl))

## [0.19.2a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.19.2a1) (2026-06-16)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.19.1a2...0.19.2a1)

**Merged pull requests:**

- fix\(tts-intelligibility\): score synthesis failures as total miss, not abort [\#77](https://github.com/OpenVoiceOS/ovoscope/pull/77) ([JarbasAl](https://github.com/JarbasAl))

## [0.19.1a2](https://github.com/OpenVoiceOS/ovoscope/tree/0.19.1a2) (2026-06-15)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.19.1a1...0.19.1a2)

**Merged pull requests:**

- feat: TTS end-to-end intelligibility harness [\#75](https://github.com/OpenVoiceOS/ovoscope/pull/75) ([JarbasAl](https://github.com/JarbasAl))

## [0.19.1a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.19.1a1) (2026-06-14)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.19.0a3...0.19.1a1)

**Merged pull requests:**

- fix: drop removed 'path' arg from pytest\_pycollect\_makemodule hook \(pytest\>=8 compat\) [\#73](https://github.com/OpenVoiceOS/ovoscope/pull/73) ([JarbasAl](https://github.com/JarbasAl))

## [0.19.0a3](https://github.com/OpenVoiceOS/ovoscope/tree/0.19.0a3) (2026-06-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.19.0a2...0.19.0a3)

**Merged pull requests:**

- chore: remove agent-audit scratch files [\#71](https://github.com/OpenVoiceOS/ovoscope/pull/71) ([JarbasAl](https://github.com/JarbasAl))

## [0.19.0a2](https://github.com/OpenVoiceOS/ovoscope/tree/0.19.0a2) (2026-06-13)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.19.0a1...0.19.0a2)

**Merged pull requests:**

- docs: standardize NGI0 Commons Fund attribution [\#69](https://github.com/OpenVoiceOS/ovoscope/pull/69) ([JarbasAl](https://github.com/JarbasAl))

## [0.19.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.19.0a1) (2026-06-12)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.18.0a1...0.19.0a1)

**Merged pull requests:**

- feat: MiniVoiceLoop + simple/classic listener bus-sequence harnesses [\#67](https://github.com/OpenVoiceOS/ovoscope/pull/67) ([JarbasAl](https://github.com/JarbasAl))

## [0.18.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.18.0a1) (2026-06-10)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.17.1a1...0.18.0a1)

**Merged pull requests:**

- feat\(phal\): plugin\_factories for MiniPHAL and PHALTest [\#65](https://github.com/OpenVoiceOS/ovoscope/pull/65) ([JarbasAl](https://github.com/JarbasAl))

## [0.17.1a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.17.1a1) (2026-05-20)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.17.0a1...0.17.1a1)

**Merged pull requests:**

- fix\(pipeline-harness\): default \_SinkSkill bus to FakeBus [\#62](https://github.com/OpenVoiceOS/ovoscope/pull/62) ([JarbasAl](https://github.com/JarbasAl))

## [0.17.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.17.0a1) (2026-05-14)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.16.0a1...0.17.0a1)

**Merged pull requests:**

- feat\(intent-cases\): markdown reporter, baseline diff, auto-discovery, deterministic m2v warmup [\#60](https://github.com/OpenVoiceOS/ovoscope/pull/60) ([JarbasAl](https://github.com/JarbasAl))

## [0.16.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.16.0a1) (2026-05-14)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.15.0a1...0.16.0a1)

**Merged pull requests:**

- feat\(intent-cases\): file-based intent test layout + pytest accuracy gate [\#58](https://github.com/OpenVoiceOS/ovoscope/pull/58) ([JarbasAl](https://github.com/JarbasAl))

## [0.15.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.15.0a1) (2026-05-14)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.14.0a1...0.15.0a1)

**Merged pull requests:**

- feat\(e2e\): reusable harness, bus helpers, and intent-registration shims [\#55](https://github.com/OpenVoiceOS/ovoscope/pull/55) ([JarbasAl](https://github.com/JarbasAl))

## [0.14.0a1](https://github.com/OpenVoiceOS/ovoscope/tree/0.14.0a1) (2026-05-14)

[Full Changelog](https://github.com/OpenVoiceOS/ovoscope/compare/0.13.1...0.14.0a1)

**Merged pull requests:**

- feat: add NEBULENTO\_PIPELINE and PALAVREADO\_PIPELINE stage groups [\#54](https://github.com/OpenVoiceOS/ovoscope/pull/54) ([JarbasAl](https://github.com/JarbasAl))



\* *This Changelog was automatically generated by [github_changelog_generator](https://github.com/github-changelog-generator/github-changelog-generator)*
