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

"""End-to-end TTS intelligibility scoring for ovoscope.

Synthesises speech with a TTS plugin under test, transcribes the rendered
audio back with a reference STT, and scores the round-trip with word- and
character-error-rate (WER/CER). This catches regressions that file-existence
unit tests miss — garbled audio, wrong sample rate, broken transforms, silent
output — and gives every TTS plugin a comparable intelligibility number.

Two synthesis modes:

* ``"playback"`` (default) drives the full ovos-audio stack
  (``speak`` -> PlaybackService -> tts.execute -> get_tts -> tts_transform ->
  play_audio) via :class:`ovoscope.audio.PlaybackServiceHarness`, with the real
  plugin injected. The rendered WAV is captured from the patched ``play_audio``.
* ``"direct"`` calls ``tts.get_tts(utterance, wav_path, ...)`` directly with no
  bus — a fallback for engines that hang under the playback thread or when
  ``ovos_audio`` is unavailable.

Public API:
    score_tts_intelligibility -- convenience function returning an IntelligibilityReport
    TTSIntelligibilityHarness  -- context manager form of the above
    IntelligibilityReport      -- aggregate report with mean WER/CER + serialisation
    UtteranceScore             -- per-utterance result
"""

import dataclasses
import os
import re
import shutil
import string
import tempfile
import threading
from typing import Any, List, Optional

import jiwer

from ovos_plugin_manager.utils.audio import AudioFile

# Module-level singleton for the reference STT — model load is expensive.
_REFERENCE_STT: Optional[Any] = None
_REFERENCE_STT_LOCK = threading.Lock()

# Module-level singleton for the utterance normaliser (cheap, but shared).
_NORMALIZER: Optional[Any] = None


def get_reference_stt() -> Any:
    """Return a lazily-instantiated faster-whisper ``tiny`` reference STT.

    The model is loaded once per process and reused. ``beam_size=1`` and
    ``compute_type="int8"`` keep it deterministic and light enough for CI.

    Returns:
        A ready-to-use ``FasterWhisperSTT`` instance.
    """
    global _REFERENCE_STT
    if _REFERENCE_STT is None:
        with _REFERENCE_STT_LOCK:
            if _REFERENCE_STT is None:
                from ovos_stt_plugin_fasterwhisper import FasterWhisperSTT
                _REFERENCE_STT = FasterWhisperSTT({
                    "model": "tiny",
                    "compute_type": "int8",
                    "beam_size": 1,
                })
    return _REFERENCE_STT


def _normalize(text: str, lang: str) -> str:
    """Normalise a transcript for fair WER/CER scoring.

    Uses ``ovos_utterance_normalizer`` (lowercase, number expansion,
    contraction expansion, punctuation strip) so cosmetic differences between
    reference and hypothesis don't inflate the error rate. The normaliser
    yields several variants per input; the last one is the fully-normalised
    form, which is what we score against.

    Args:
        text: The raw text to normalise.
        lang: BCP-47 language tag (e.g. ``"en-US"``).

    Returns:
        A single normalised string (whitespace-collapsed, lowercased).
    """
    global _NORMALIZER
    if _NORMALIZER is None:
        from ovos_utterance_normalizer import UtteranceNormalizerPlugin
        _NORMALIZER = UtteranceNormalizerPlugin()
    if not text:
        return ""
    variants, _ = _NORMALIZER.transform([text], {"lang": lang})
    # transform() emits [contraction-expanded, original, number-normalized]
    # per utterance, deduplicated and order-preserving. The first variant
    # (contractions expanded, punctuation stripped, words kept as words) is the
    # stable choice — the number-collapsed variant ("two" -> "2") would create
    # spurious mismatches against a word-emitting STT. Lowercasing/whitespace
    # collapse are applied here so both reference and hypothesis align.
    normalized = variants[0] if variants else text
    # The normaliser only strips leading/trailing punctuation of the whole
    # string; interior punctuation (e.g. a tokenised comma) survives and would
    # inflate WER. Strip all punctuation characters here, then collapse space.
    normalized = re.sub(rf"[{re.escape(string.punctuation)}]", " ", normalized)
    return " ".join(normalized.lower().split())


def _score_pair(reference: str, hypothesis: str) -> "tuple[float, float]":
    """Compute (WER, CER) for a reference/hypothesis pair.

    jiwer raises on an empty reference, so empty references are handled
    explicitly: a non-empty hypothesis against an empty reference scores 1.0
    (fully wrong), two empties score 0.0 (trivially correct).

    Args:
        reference: Normalised ground-truth string.
        hypothesis: Normalised transcript from the reference STT.

    Returns:
        Tuple of ``(wer, cer)`` as floats.
    """
    if not reference:
        return (0.0, 0.0) if not hypothesis else (1.0, 1.0)
    wer = float(jiwer.wer(reference, hypothesis))
    cer = float(jiwer.cer(reference, hypothesis))
    return wer, cer


@dataclasses.dataclass
class UtteranceScore:
    """Per-utterance intelligibility result.

    Attributes:
        utterance: The text that was synthesised (the ground truth).
        transcript: What the reference STT heard back.
        wer: Word error rate of transcript vs utterance (0.0 = perfect).
        cer: Character error rate of transcript vs utterance.
        wav_path: Path to the captured rendered WAV (may be None on failure).
        lang: BCP-47 language tag used for synthesis and scoring.
        voice: Voice identifier used, if any.
    """

    utterance: str
    transcript: str
    wer: float
    cer: float
    wav_path: Optional[str] = None
    lang: str = "en-US"
    voice: Optional[str] = None

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of this score."""
        return {
            "utterance": self.utterance,
            "transcript": self.transcript,
            "wer": round(self.wer, 4),
            "cer": round(self.cer, 4),
            "wav_path": self.wav_path,
            "lang": self.lang,
            "voice": self.voice,
        }


@dataclasses.dataclass
class IntelligibilityReport:
    """Aggregate intelligibility report over a set of utterances.

    Attributes:
        scores: Per-utterance :class:`UtteranceScore` results.
        lang: BCP-47 language tag the run used.
        voice: Voice identifier the run used, if any.
        mode: Synthesis mode used (``"playback"`` or ``"direct"``).
    """

    scores: List[UtteranceScore] = dataclasses.field(default_factory=list)
    lang: str = "en-US"
    voice: Optional[str] = None
    mode: str = "playback"

    @property
    def mean_wer(self) -> float:
        """Mean word error rate across all scored utterances (0.0 if empty)."""
        if not self.scores:
            return 0.0
        return sum(s.wer for s in self.scores) / len(self.scores)

    @property
    def mean_cer(self) -> float:
        """Mean character error rate across all scored utterances (0.0 if empty)."""
        if not self.scores:
            return 0.0
        return sum(s.cer for s in self.scores) / len(self.scores)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of the full report."""
        return {
            "lang": self.lang,
            "voice": self.voice,
            "mode": self.mode,
            "mean_wer": round(self.mean_wer, 4),
            "mean_cer": round(self.mean_cer, 4),
            "n_utterances": len(self.scores),
            "scores": [s.to_dict() for s in self.scores],
        }

    def to_markdown_row(self) -> str:
        """Return a single markdown table row: ``| voice | lang | mean_wer | mean_cer | n |``."""
        voice = self.voice or "default"
        return (
            f"| {voice} | {self.lang} | "
            f"{self.mean_wer:.3f} | {self.mean_cer:.3f} | {len(self.scores)} |"
        )


class TTSIntelligibilityHarness:
    """Context manager that scores TTS intelligibility end-to-end.

    Usage::

        with TTSIntelligibilityHarness(tts, lang="en-US") as h:
            report = h.score(["hello world", "what time is it"])
        print(report.mean_wer)

    In ``mode="playback"`` the harness owns a :class:`PlaybackServiceHarness`
    for its lifetime; in ``mode="direct"`` no bus is started. A temp directory
    holds copies of the rendered WAVs (the TTS cache may delete originals); it
    is cleaned up on exit.

    Args:
        tts: The TTS plugin under test.
        lang: BCP-47 language tag for synthesis and scoring.
        voice: Optional voice identifier passed to ``get_tts``.
        reference_stt: STT used to transcribe. Defaults to the lazy
            faster-whisper ``tiny`` singleton.
        mode: ``"playback"`` (full ovos-audio stack) or ``"direct"``
            (``tts.get_tts`` only).
        speak_timeout: Per-utterance timeout for playback mode.
    """

    def __init__(self, tts: Any, *, lang: str = "en-US",
                 voice: Optional[str] = None,
                 reference_stt: Optional[Any] = None,
                 mode: str = "playback",
                 speak_timeout: float = 30.0) -> None:
        if mode not in ("playback", "direct"):
            raise ValueError(f"mode must be 'playback' or 'direct', got {mode!r}")
        self.tts = tts
        self.lang = lang
        self.voice = voice
        self._reference_stt = reference_stt
        self.mode = mode
        self.speak_timeout = speak_timeout
        self._tmpdir: Optional[str] = None
        self._playback = None  # PlaybackServiceHarness in playback mode

    @property
    def reference_stt(self) -> Any:
        """The reference STT, lazily resolved to the faster-whisper singleton."""
        if self._reference_stt is None:
            self._reference_stt = get_reference_stt()
        return self._reference_stt

    def __enter__(self) -> "TTSIntelligibilityHarness":
        self._tmpdir = tempfile.mkdtemp(prefix="ovoscope-tts-")
        if self.mode == "playback":
            from ovoscope.audio import PlaybackServiceHarness
            self._playback = PlaybackServiceHarness(tts=self.tts)
            self._playback.__enter__()
        return self

    def __exit__(self, *args) -> None:
        if self._playback is not None:
            try:
                self._playback.__exit__(*args)
            except Exception:
                pass
            self._playback = None
        if self._tmpdir and os.path.isdir(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    def _render_playback(self, utterance: str) -> Optional[str]:
        """Synthesise via the full ovos-audio stack; return a copied WAV path."""
        before = len(self._playback.captured_wavs)
        self._playback.speak(utterance, timeout=self.speak_timeout)
        captured = self._playback.captured_wavs[before:]
        if not captured:
            return None
        return self._copy_out(captured[-1])

    def _render_direct(self, utterance: str) -> Optional[str]:
        """Synthesise via ``tts.get_tts`` directly; return the WAV path."""
        wav_path = os.path.join(
            self._tmpdir, f"direct_{abs(hash(utterance)) & 0xffffffff}.wav"
        )
        self.tts.get_tts(utterance, wav_path, lang=self.lang, voice=self.voice)
        return wav_path if os.path.isfile(wav_path) else None

    def _copy_out(self, wav_path: str) -> Optional[str]:
        """Copy a rendered WAV into the harness temp dir before the cache prunes it."""
        if not wav_path or not os.path.isfile(wav_path):
            return wav_path if wav_path and os.path.isfile(wav_path) else None
        dst = os.path.join(
            self._tmpdir, f"play_{len(os.listdir(self._tmpdir))}_{os.path.basename(wav_path)}"
        )
        try:
            shutil.copyfile(wav_path, dst)
            return dst
        except OSError:
            return wav_path

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _transcribe(self, wav_path: str) -> str:
        """Round-trip a WAV through the reference STT and return the transcript."""
        with AudioFile(wav_path) as source:
            audio = source.read()
        return self.reference_stt.execute(audio, language=self.lang) or ""

    def score_one(self, utterance: str) -> UtteranceScore:
        """Synthesise, transcribe, and score a single utterance.

        Args:
            utterance: The text to synthesise and score.

        Returns:
            An :class:`UtteranceScore`. On synthesis/transcription failure the
            transcript is empty and WER/CER reflect a total miss.
        """
        if self.mode == "playback":
            wav_path = self._render_playback(utterance)
        else:
            wav_path = self._render_direct(utterance)

        transcript = ""
        if wav_path and os.path.isfile(wav_path):
            try:
                transcript = self._transcribe(wav_path)
            except Exception:
                transcript = ""

        ref = _normalize(utterance, self.lang)
        hyp = _normalize(transcript, self.lang)
        wer, cer = _score_pair(ref, hyp)
        return UtteranceScore(
            utterance=utterance,
            transcript=transcript,
            wer=wer,
            cer=cer,
            wav_path=wav_path,
            lang=self.lang,
            voice=self.voice,
        )

    def score(self, utterances: List[str]) -> IntelligibilityReport:
        """Score a list of utterances and return the aggregate report.

        Args:
            utterances: Phrases to synthesise and score.

        Returns:
            An :class:`IntelligibilityReport`.
        """
        report = IntelligibilityReport(lang=self.lang, voice=self.voice, mode=self.mode)
        for utt in utterances:
            report.scores.append(self.score_one(utt))
        return report


def score_tts_intelligibility(tts: Any, utterances: List[str], *,
                              lang: str = "en-US",
                              voice: Optional[str] = None,
                              reference_stt: Optional[Any] = None,
                              mode: str = "playback",
                              speak_timeout: float = 30.0) -> IntelligibilityReport:
    """Synthesise, transcribe, and score a set of utterances in one call.

    Args:
        tts: The TTS plugin under test.
        utterances: Phrases to synthesise and score.
        lang: BCP-47 language tag for synthesis and scoring.
        voice: Optional voice identifier passed to ``get_tts``.
        reference_stt: STT used to transcribe. Defaults to faster-whisper tiny.
        mode: ``"playback"`` (full ovos-audio stack) or ``"direct"``.
        speak_timeout: Per-utterance timeout for playback mode.

    Returns:
        An :class:`IntelligibilityReport` with per-utterance and mean scores.
    """
    with TTSIntelligibilityHarness(
        tts, lang=lang, voice=voice, reference_stt=reference_stt,
        mode=mode, speak_timeout=speak_timeout,
    ) as harness:
        return harness.score(utterances)
