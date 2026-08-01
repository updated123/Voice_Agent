"""VAD backend interface.

docs/architecture.md describes the production choice (Silero-VAD,
GPU-free, running on the media server). This interface is deliberately
narrow so a production backend is a drop-in swap: implement
`is_speech(frame) -> bool` and the rest of the pipeline (hangover-window
end-of-speech detection, barge-in triggering) is backend-agnostic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VADResult:
    is_speech: bool
    frame_index: int
    confidence: float = 1.0


class VADBackend(ABC):
    """Frame-level speech/non-speech classifier.

    Implementations must be able to classify a single audio frame
    (typically 20-30ms of PCM16 mono audio) in well under the frame
    duration itself, since this runs inline on every frame of every
    active call.
    """

    @abstractmethod
    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        """Return True if `frame` contains speech."""
        raise NotImplementedError


class HangoverVAD:
    """Wraps a frame-level VADBackend with end-of-speech ("hangover") logic.

    This is the piece that actually matters for turn-taking latency
    (docs/latency-budget.md): declaring "the borrower has finished
    talking" too early causes interruptions; too late causes sluggish
    turn-taking. `hangover_ms` is the tunable knob.
    """

    def __init__(self, backend: VADBackend, frame_duration_ms: int = 30, hangover_ms: int = 200):
        self.backend = backend
        self.frame_duration_ms = frame_duration_ms
        self.hangover_frames = max(1, round(hangover_ms / frame_duration_ms))
        self._silence_run = 0
        self._speech_seen = False

    def process_frame(self, frame: bytes, sample_rate: int) -> str:
        """Feed one frame; returns one of: 'silence', 'speech', 'end_of_speech'.

        'end_of_speech' fires exactly once, `hangover_frames` frames after
        the last frame classified as speech.
        """
        speech = self.backend.is_speech(frame, sample_rate)

        if speech:
            self._silence_run = 0
            self._speech_seen = True
            return "speech"

        if self._speech_seen:
            self._silence_run += 1
            if self._silence_run == self.hangover_frames:
                self._speech_seen = False
                return "end_of_speech"
        return "silence"

    def reset(self) -> None:
        self._silence_run = 0
        self._speech_seen = False
