"""Runnable dev/reference denoiser: FFT spectral gating (spectral subtraction).

docs/architecture.md and docs/architecture.md specify DeepFilterNet (or
RNNoise) as the production denoiser -- both are real-time neural denoisers
that meaningfully beat classical spectral gating on non-stationary noise
(traffic, other voices). Spectral gating is implemented here because it needs
no model download/GPU and is a legitimate, if less powerful, real technique --
useful as a dev-mode default and as a baseline to benchmark the neural
denoiser's improvement against.
"""

import numpy as np


class SpectralGateDenoiser:
    def __init__(self, sample_rate: int = 16000, noise_floor_db: float = -40.0,
                 frame_size: int = 512, hop_size: int = 256):
        self.sample_rate = sample_rate
        self.noise_floor_db = noise_floor_db
        self.frame_size = frame_size
        self.hop_size = hop_size
        self._window = np.hanning(frame_size)
        self._noise_profile = None  # magnitude spectrum estimate, learned adaptively

    def _estimate_noise(self, magnitude: np.ndarray, alpha: float = 0.98) -> None:
        if self._noise_profile is None:
            self._noise_profile = magnitude.copy()
        else:
            # Slow-moving floor estimate: assumes noise is quieter/steadier
            # than speech, so a low percentile tracked over time approximates it.
            self._noise_profile = np.minimum(
                self._noise_profile * alpha + magnitude * (1 - alpha),
                np.maximum(self._noise_profile, magnitude),
            )

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Denoise a mono float32 waveform in [-1, 1]. Returns same shape/dtype."""
        if audio.size < self.frame_size:
            return audio

        out = np.zeros_like(audio)
        window_sum = np.zeros_like(audio)
        threshold_linear = 10 ** (self.noise_floor_db / 20.0)

        for start in range(0, len(audio) - self.frame_size + 1, self.hop_size):
            frame = audio[start:start + self.frame_size] * self._window
            spectrum = np.fft.rfft(frame)
            magnitude = np.abs(spectrum)
            phase = np.angle(spectrum)

            self._estimate_noise(magnitude)
            gate_floor = np.maximum(self._noise_profile, threshold_linear)
            gain = np.clip((magnitude - gate_floor) / (magnitude + 1e-8), 0.0, 1.0)
            gated_magnitude = magnitude * gain

            cleaned = np.fft.irfft(gated_magnitude * np.exp(1j * phase), n=self.frame_size)
            out[start:start + self.frame_size] += cleaned * self._window
            window_sum[start:start + self.frame_size] += self._window ** 2

        nonzero = window_sum > 1e-8
        out[nonzero] /= window_sum[nonzero]
        return np.clip(out, -1.0, 1.0).astype(audio.dtype)

    def reset(self) -> None:
        self._noise_profile = None
