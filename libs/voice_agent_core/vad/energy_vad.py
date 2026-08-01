"""Runnable dev/reference VAD backend: short-term energy + zero-crossing rate.

This requires no model download and no extra dependency beyond numpy, so the
prototype runs anywhere. docs/architecture.md and docs/architecture.md
call out Silero-VAD as the production backend (materially more robust to
background noise) -- swapping it in means implementing VADBackend.is_speech
with the Silero model and nothing else in the pipeline changes.
"""

import numpy as np

from .base import VADBackend


class EnergyVAD(VADBackend):
    def __init__(self, energy_threshold: float = 0.01, zcr_max: float = 0.15):
        self.energy_threshold = energy_threshold
        self.zcr_max = zcr_max

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return False

        rms = float(np.sqrt(np.mean(samples**2)))
        signs = np.sign(samples)
        signs[signs == 0] = 1
        zcr = float(np.mean(signs[1:] != signs[:-1]))

        # Speech has meaningful energy but isn't pure high-frequency noise
        # (which tends to have a very high zero-crossing rate).
        return rms > self.energy_threshold and zcr < self.zcr_max
