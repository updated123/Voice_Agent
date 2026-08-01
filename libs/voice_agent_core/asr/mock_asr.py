"""Mock ASR backend for the runnable demo/tests -- no model, no GPU, no download.

Real speech-to-text requires a trained acoustic model; this repo doesn't ship
one. Instead of silently faking "perfect" transcription, this backend reads
ground-truth text attached to a SyntheticUtterance (see
orchestrator/call_session.py) and optionally injects word-level errors to
simulate a realistic, imperfect ASR channel -- so the dialogue manager and
tests genuinely have to handle noisy/ambiguous transcripts, which is the
realistic operating condition documented in docs/monitoring.md.

Swap in `voice_agent.asr.faster_whisper_asr.FasterWhisperASR` (not included in
this prototype -- see docs/architecture.md) for real transcription; nothing
else in the pipeline needs to change since it only depends on ASRBackend.
"""

import random
from dataclasses import dataclass

import numpy as np

from .base import ASRBackend, Transcript


@dataclass
class SyntheticUtterance:
    """Audio + attached ground-truth text, used only by the mock ASR backend."""
    audio: np.ndarray
    transcript: str


class MockASR(ASRBackend):
    def __init__(self, word_error_rate: float = 0.0, seed: int = 0):
        self.word_error_rate = word_error_rate
        self._rng = random.Random(seed)

    def transcribe_utterance(self, audio, sample_rate: int) -> Transcript:
        if isinstance(audio, SyntheticUtterance):
            text = audio.transcript
        else:
            text = ""

        if self.word_error_rate > 0 and text:
            words = text.split()
            words = [w for w in words if self._rng.random() > self.word_error_rate]
            text = " ".join(words) if words else "<unintelligible>"

        confidence = 1.0 - self.word_error_rate
        return Transcript(text=text, is_final=True, confidence=confidence)
