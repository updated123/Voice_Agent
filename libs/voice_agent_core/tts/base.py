"""Streaming TTS interface.

docs/latency-budget.md is explicit that time-to-first-audio-byte (not
total synthesis time) is the metric that matters: a non-streaming TTS,
however good the voice quality, is disqualified on latency grounds alone.
`synthesize_stream` therefore yields audio chunks incrementally rather than
returning a single finished waveform, mirroring how a real streaming TTS
model (docs/architecture.md: a Kokoro-82M-class or Piper model in
production) would be called.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator

import numpy as np


class TTSBackend(ABC):
    @abstractmethod
    def synthesize_stream(self, text: str, sample_rate: int = 16000) -> Iterator[np.ndarray]:
        """Yield successive audio chunks (float32 PCM, mono) for `text`."""
        raise NotImplementedError
