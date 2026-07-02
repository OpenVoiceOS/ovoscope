# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for ovoscope.tts_intelligibility.

These tests use a MockTTS (silent WAV) and a MockSTT that echoes a fixed
transcript — no model download, no real audio. They cover WER/CER math, report
aggregation, serialisation, and that playback interception captures a wav path.
"""

import importlib.util
import subprocess
import sys
import unittest

TTS_AVAILABLE = (
    importlib.util.find_spec("jiwer") is not None
    and importlib.util.find_spec("ovos_audio") is not None
    and importlib.util.find_spec("ovos_utterance_normalizer") is not None
)


@unittest.skipUnless(TTS_AVAILABLE, "tts extra (jiwer/ovos-audio/normalizer) not installed")
class TestScoring(unittest.TestCase):
    """WER/CER math, normalisation and report aggregation — no synthesis."""

    def setUp(self):
        from ovoscope import tts_intelligibility as ti
        self.ti = ti

    def test_perfect_match_is_zero(self):
        wer, cer = self.ti._score_pair("hello world", "hello world")
        self.assertEqual(wer, 0.0)
        self.assertEqual(cer, 0.0)

    def test_one_wrong_word_half_wer(self):
        wer, _ = self.ti._score_pair("hello world", "hello there")
        self.assertAlmostEqual(wer, 0.5, places=3)

    def test_empty_reference_handling(self):
        self.assertEqual(self.ti._score_pair("", ""), (0.0, 0.0))
        self.assertEqual(self.ti._score_pair("", "noise"), (1.0, 1.0))

    def test_normalize_strips_case_and_punctuation(self):
        # "Hello, World!" should normalise to "hello world" so it scores 0
        # against the lowercased ground truth.
        wer, _ = self.ti._score_pair(
            self.ti._normalize("Hello, World!", "en-US"),
            self.ti._normalize("hello world", "en-US"),
        )
        self.assertEqual(wer, 0.0)

    def test_report_aggregation(self):
        UtteranceScore = self.ti.UtteranceScore
        IntelligibilityReport = self.ti.IntelligibilityReport
        report = IntelligibilityReport(lang="en-US", voice="alan")
        report.scores.append(UtteranceScore("a", "a", 0.0, 0.0, lang="en-US"))
        report.scores.append(UtteranceScore("b", "x", 1.0, 1.0, lang="en-US"))
        self.assertAlmostEqual(report.mean_wer, 0.5)
        self.assertAlmostEqual(report.mean_cer, 0.5)

    def test_empty_report_means_zero(self):
        report = self.ti.IntelligibilityReport()
        self.assertEqual(report.mean_wer, 0.0)
        self.assertEqual(report.mean_cer, 0.0)

    def test_to_dict_and_markdown_row(self):
        UtteranceScore = self.ti.UtteranceScore
        report = self.ti.IntelligibilityReport(lang="en-US", voice="alan")
        report.scores.append(UtteranceScore("a", "a", 0.0, 0.0, lang="en-US"))
        d = report.to_dict()
        self.assertEqual(d["lang"], "en-US")
        self.assertEqual(d["voice"], "alan")
        self.assertEqual(d["n_utterances"], 1)
        self.assertEqual(d["mean_wer"], 0.0)
        self.assertIn("scores", d)
        row = report.to_markdown_row()
        self.assertIn("alan", row)
        self.assertIn("en-US", row)
        self.assertTrue(row.startswith("|") and row.endswith("|"))


class MockSTT:
    """Reference STT stub that echoes a fixed transcript regardless of audio."""

    def __init__(self, transcript="hello world"):
        self.transcript = transcript
        self.calls = 0

    def execute(self, audio, language=None):
        self.calls += 1
        return self.transcript


@unittest.skipUnless(TTS_AVAILABLE, "tts extra (jiwer/ovos-audio/normalizer) not installed")
class TestHarnessDirectMode(unittest.TestCase):
    """Direct mode: tts.get_tts only, MockSTT echo — no bus, no model."""

    def test_direct_mode_perfect_score(self):
        from ovoscope.audio import MockTTS
        from ovoscope.tts_intelligibility import score_tts_intelligibility

        stt = MockSTT("hello world")
        report = score_tts_intelligibility(
            MockTTS(), ["hello world"],
            reference_stt=stt, mode="direct",
        )
        self.assertEqual(len(report.scores), 1)
        self.assertEqual(report.mean_wer, 0.0)
        self.assertEqual(stt.calls, 1)
        self.assertIsNotNone(report.scores[0].wav_path)

    def test_direct_mode_mismatch_scores_high(self):
        from ovoscope.audio import MockTTS
        from ovoscope.tts_intelligibility import score_tts_intelligibility

        report = score_tts_intelligibility(
            MockTTS(), ["completely different text here"],
            reference_stt=MockSTT("hello world"), mode="direct",
        )
        self.assertGreater(report.mean_wer, 0.0)


@unittest.skipUnless(TTS_AVAILABLE, "tts extra (jiwer/ovos-audio/normalizer) not installed")
class TestHarnessPlaybackMode(unittest.TestCase):
    """Playback mode: full ovos-audio stack drives MockTTS; wav is captured."""

    def test_playback_captures_wav_and_scores(self):
        from ovoscope.audio import MockTTS
        from ovoscope.tts_intelligibility import TTSIntelligibilityHarness

        tts = MockTTS()
        stt = MockSTT("hello world")
        with TTSIntelligibilityHarness(
            tts, reference_stt=stt, mode="playback", speak_timeout=15.0,
        ) as h:
            report = h.score(["hello world"])

        self.assertEqual(len(report.scores), 1)
        score = report.scores[0]
        # Playback interception must have captured a rendered wav path.
        self.assertIsNotNone(score.wav_path, "no wav captured from playback")
        self.assertIn("hello world", tts.spoken_utterances)
        self.assertEqual(report.mean_wer, 0.0)


class TestGracefulImport(unittest.TestCase):
    """Core ``import ovoscope`` must succeed even without the [tts] extra."""

    def test_import_without_tts_extra(self):
        # Run in a subprocess with the optional tts deps blocked at import time,
        # simulating an environment that never installed ovoscope[tts].
        code = (
            "import sys, importlib.abc, importlib.machinery\n"
            "BLOCKED = {'jiwer', 'ovos_utterance_normalizer', "
            "'ovos_stt_plugin_fasterwhisper', 'faster_whisper'}\n"
            "class _Block(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path, target=None):\n"
            "        if name.split('.')[0] in BLOCKED:\n"
            "            raise ModuleNotFoundError(name=name.split('.')[0])\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n"
            "for m in list(sys.modules):\n"
            "    if m.split('.')[0] in BLOCKED:\n"
            "        del sys.modules[m]\n"
            "import ovoscope\n"
            "assert not hasattr(ovoscope, 'TTSIntelligibilityHarness'), "
            "'harness should be absent without the tts extra'\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            f"core import failed without tts extra:\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("OK", result.stdout)


@unittest.skipUnless(TTS_AVAILABLE, "tts extra (jiwer/ovos-audio/normalizer) not installed")
class TestSynthesisFailureResilience(unittest.TestCase):
    """A get_tts crash must score as a total miss, not abort the whole run."""

    def test_synthesis_failure_scores_total_miss(self):
        from ovoscope import tts_intelligibility as ti

        class BoomTTS:
            def get_tts(self, *args, **kwargs):
                raise RuntimeError("synthesis exploded")

        class EchoSTT:
            def execute(self, audio, language=None):
                return "anything"

        harness = ti.TTSIntelligibilityHarness(
            BoomTTS(), lang="en-US", reference_stt=EchoSTT(), mode="direct",
        )
        with harness:
            report = harness.score(["hello world", "good morning"])

        # The run completes and every utterance is scored a total miss (WER 1.0)
        # rather than the exception propagating and emitting no marker at all.
        self.assertEqual(len(report.scores), 2)
        self.assertEqual(report.mean_wer, 1.0)
        # The report still serialises, so the test's marker can be emitted.
        import json
        json.loads(json.dumps(report.to_dict()))


if __name__ == "__main__":
    unittest.main()
