"""Streaming ASR interface.

docs/architecture.md specifies a self-hosted streaming Conformer /
distil-Whisper (served via CTranslate2 or NVIDIA Riva) as the production
backend, GPU-batched across many concurrent calls. This interface exposes
both partial and final transcripts because the dialogue manager can start
acting on high-confidence partials before the final event fires -- see
docs/latency-budget.md, stage [2].
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class Transcript:
    text: str
    is_final: bool
    confidence: float = 1.0


class ASRBackend(ABC):
    @abstractmethod
    def transcribe_utterance(self, audio: np.ndarray, sample_rate: int) -> Transcript:
        """Transcribe one complete borrower utterance (already VAD-segmented).

        Real streaming backends would instead expose partial-result callbacks
        as audio arrives; this simplified interface transcribes a whole
        utterance at once, which is sufficient to demonstrate the pipeline
        wiring and dialogue-manager behavior in this prototype.
        """
        raise NotImplementedError
