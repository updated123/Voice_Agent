"""Data types for a simulated call.

A real call gets its borrower audio from the PSTN/mobile network in
real time; this prototype instead runs against a scripted list of
`ScriptedBorrowerTurn`s so the pipeline can be exercised and tested
deterministically without a live phone line or a real ASR/TTS model.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class ScriptedBorrowerTurn:
    text: str
    barge_in: bool = False        # if True, this "utterance" interrupts the bot mid-TTS-playback
    inject_noise: bool = False    # if True, run through the denoiser with synthetic added noise


@dataclass
class TranscriptEntry:
    speaker: str                  # "bot" or "borrower"
    text: str
    state: str = ""
    intent: str = ""
    barge_in: bool = False
    escalated: bool = False
    interrupted: bool = False     # bot entries only: was this response cut short by a genuine barge-in?


# Short acknowledgment phrases spoken while the bot is still talking ("mm-hmm",
# "yeah", "okay") are not an attempt to take the floor -- treating every
# detected utterance during TTS playback as a real interruption makes the bot
# read as jumpy/broken. This is a real, honest simplification for this
# prototype: a live system would need genuine overlapping-audio detection to
# make this call in real time, not a keyword match against already-transcribed
# text after the fact (there's no transcript yet at the moment a live system
# has to decide whether to keep talking). See docs/architecture.md's
# "Audio pipeline detail" section for the semantic-endpointing discussion this
# is the barge-in-side counterpart of.
BACKCHANNEL_PHRASES = frozenset({
    "mm-hmm", "mhm", "uh-huh", "mm", "yeah", "yep", "okay", "ok",
    "right", "i see", "got it", "sure", "uh huh",
})


def is_backchannel(text: str) -> bool:
    """True if `text` is a short acknowledgment rather than an attempt to
    interrupt -- a barge-in-flagged turn matching this should NOT cut the
    bot's TTS stream."""
    return text.strip().lower().rstrip(".!?") in BACKCHANNEL_PHRASES


def make_synthetic_audio(text: str, sample_rate: int = 16000, add_noise: bool = False) -> np.ndarray:
    """Generate a placeholder waveform standing in for real borrower audio.

    Duration scales with text length so downstream duration-dependent logic
    (VAD hangover timing, TTS chunking) has something non-trivial to act on.
    Optionally mixes in white noise to exercise the denoiser.
    """
    n_words = max(len(text.split()), 1)
    duration_s = 0.35 * n_words
    n_samples = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    voice = 0.3 * np.sin(2 * np.pi * 150 * t) * np.sin(2 * np.pi * 2.5 * t) ** 2

    if add_noise:
        rng = np.random.default_rng(42)
        voice = voice + rng.normal(0, 0.08, size=voice.shape)

    return voice.astype(np.float32)
