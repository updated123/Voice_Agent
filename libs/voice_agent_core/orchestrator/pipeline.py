"""asyncio orchestrator wiring VAD -> denoiser -> ASR -> dialogue manager -> TTS.

This mirrors the production data flow in docs/architecture.md at
prototype scale: one call at a time, in-process, using the mock/dev backends
from each sibling package. Swapping every backend for its production
counterpart (Silero-VAD, DeepFilterNet, a served streaming ASR model, a
served fine-tuned LLM, a served streaming TTS model) does not require
changing this orchestrator, since it only depends on each package's public
interface (VADBackend, ASRBackend, DialogueManager, TTSBackend).
"""

import asyncio

import numpy as np

from ..asr.base import ASRBackend
from ..asr.mock_asr import SyntheticUtterance
from ..denoiser.spectral_gate import SpectralGateDenoiser
from ..dialogue.manager import DialogueManager
from ..tts.base import TTSBackend
from .call_session import ScriptedBorrowerTurn, TranscriptEntry, make_synthetic_audio

# Simulated barge-in cutoff: how many TTS chunks play before an interrupting
# borrower turn is deemed to have stopped the bot (docs/architecture.md
# targets ~100ms interrupt-to-silence; here it's expressed in chunk count
# since this prototype doesn't run on a real audio clock).
BARGE_IN_CUTOFF_CHUNKS = 1


class VoiceAgentPipeline:
    def __init__(
        self,
        asr: ASRBackend,
        tts: TTSBackend,
        dialogue_manager: DialogueManager = None,
        denoiser: SpectralGateDenoiser = None,
        sample_rate: int = 16000,
    ):
        self.asr = asr
        self.tts = tts
        self.dialogue_manager = dialogue_manager or DialogueManager()
        self.denoiser = denoiser or SpectralGateDenoiser(sample_rate=sample_rate)
        self.sample_rate = sample_rate

    async def _play_tts(self, text: str, allow_barge_in: bool) -> tuple[list[np.ndarray], bool]:
        """Consume the TTS stream. Returns (chunks_played, was_interrupted)."""
        chunks = []
        stream = self.tts.synthesize_stream(text, self.sample_rate)
        interrupted = False
        for i, chunk in enumerate(stream):
            chunks.append(chunk)
            await asyncio.sleep(0)  # yield control, mirrors an async I/O boundary in production
            if allow_barge_in and i + 1 >= BARGE_IN_CUTOFF_CHUNKS:
                interrupted = True
                stream.close()
                break
        return chunks, interrupted

    async def _process_borrower_turn(self, turn: ScriptedBorrowerTurn) -> str:
        raw_audio = make_synthetic_audio(turn.text, self.sample_rate, add_noise=turn.inject_noise)
        denoised_audio = self.denoiser.process(raw_audio)
        utterance = SyntheticUtterance(audio=denoised_audio, transcript=turn.text)
        transcript = self.asr.transcribe_utterance(utterance, self.sample_rate)
        await asyncio.sleep(0)
        return transcript.text

    async def run_call(self, script: list[ScriptedBorrowerTurn]) -> list[TranscriptEntry]:
        """Run one simulated call end-to-end. Returns the full transcript log."""
        log: list[TranscriptEntry] = []

        opening = self.dialogue_manager.opening_turn()
        _, interrupted = await self._play_tts(opening.response_text, allow_barge_in=False)
        log.append(TranscriptEntry(
            speaker="bot", text=opening.response_text, state=opening.state.value,
        ))

        for turn in script:
            recognized_text = await self._process_borrower_turn(turn)
            log.append(TranscriptEntry(speaker="borrower", text=recognized_text, barge_in=turn.barge_in))

            dialogue_turn = self.dialogue_manager.handle_turn(recognized_text)
            _, interrupted = await self._play_tts(dialogue_turn.response_text, allow_barge_in=False)
            log.append(TranscriptEntry(
                speaker="bot",
                text=dialogue_turn.response_text,
                state=dialogue_turn.state.value,
                intent=dialogue_turn.intent.value,
                escalated=dialogue_turn.should_escalate,
            ))

            if dialogue_turn.call_ended:
                break

        return log
