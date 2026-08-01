"""Mock streaming TTS backend for the runnable demo/tests -- no model, no GPU.

Generates placeholder audio (silence, correctly timed and chunked per word)
rather than real speech. What matters for this prototype is the *streaming
interface shape* and, critically, that playback can be stopped mid-stream
for barge-in (docs/architecture.md) -- both are exercised faithfully
here even though the audio itself is a stand-in.

Swap in a real streaming model (docs/architecture.md) behind the same
TTSBackend interface for production.
"""

from collections.abc import Iterator

import numpy as np

from .base import TTSBackend


class MockStreamingTTS(TTSBackend):
    def __init__(self, chunk_ms: int = 120, ms_per_word: int = 220):
        self.chunk_ms = chunk_ms
        self.ms_per_word = ms_per_word

    def synthesize_stream(self, text: str, sample_rate: int = 16000) -> Iterator[np.ndarray]:
        words = text.split() or [""]
        total_ms = max(len(words) * self.ms_per_word, self.chunk_ms)
        emitted_ms = 0
        while emitted_ms < total_ms:
            this_chunk_ms = min(self.chunk_ms, total_ms - emitted_ms)
            n_samples = int(sample_rate * this_chunk_ms / 1000)
            # Low-amplitude placeholder "voice" signal (not silence, so it's
            # distinguishable from a dropped/empty stream in tests/logs).
            t = np.linspace(0, this_chunk_ms / 1000, n_samples, endpoint=False)
            chunk = (0.05 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
            yield chunk
            emitted_ms += this_chunk_ms
