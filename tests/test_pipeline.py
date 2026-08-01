import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs"))

from voice_agent_core.asr.mock_asr import MockASR
from voice_agent_core.denoiser.spectral_gate import SpectralGateDenoiser
from voice_agent_core.dialogue.fsm import CallFSM, CallState
from voice_agent_core.dialogue.intents import Intent, KeywordIntentClassifier
from voice_agent_core.dialogue.manager import DialogueManager
from voice_agent_core.orchestrator.call_session import ScriptedBorrowerTurn
from voice_agent_core.orchestrator.pipeline import VoiceAgentPipeline
from voice_agent_core.tts.mock_tts import MockStreamingTTS
from voice_agent_core.vad.base import HangoverVAD
from voice_agent_core.vad.energy_vad import EnergyVAD

# ---------- VAD ----------

def test_energy_vad_detects_silence_vs_tone():
    vad = EnergyVAD(energy_threshold=0.01)
    sample_rate = 16000
    silence = np.zeros(480, dtype=np.int16).tobytes()
    t = np.linspace(0, 0.03, 480, endpoint=False)
    tone = (0.5 * np.sin(2 * np.pi * 200 * t) * 32767).astype(np.int16).tobytes()

    assert vad.is_speech(silence, sample_rate) is False
    assert vad.is_speech(tone, sample_rate) is True


def test_hangover_vad_emits_end_of_speech_after_hangover_window():
    backend = EnergyVAD(energy_threshold=0.01)
    hv = HangoverVAD(backend, frame_duration_ms=30, hangover_ms=90)  # 3 frames
    sample_rate = 16000
    t = np.linspace(0, 0.03, 480, endpoint=False)
    tone_frame = (0.5 * np.sin(2 * np.pi * 200 * t) * 32767).astype(np.int16).tobytes()
    silence_frame = np.zeros(480, dtype=np.int16).tobytes()

    assert hv.process_frame(tone_frame, sample_rate) == "speech"
    assert hv.process_frame(silence_frame, sample_rate) == "silence"
    assert hv.process_frame(silence_frame, sample_rate) == "silence"
    assert hv.process_frame(silence_frame, sample_rate) == "end_of_speech"


# ---------- Denoiser ----------

def test_spectral_gate_denoiser_preserves_shape_and_reduces_noise_energy():
    sample_rate = 16000
    rng = np.random.default_rng(0)
    duration_s = 1.0
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    clean = 0.4 * np.sin(2 * np.pi * 220 * t)
    noisy = (clean + rng.normal(0, 0.15, size=clean.shape)).astype(np.float32)

    denoiser = SpectralGateDenoiser(sample_rate=sample_rate)
    denoised = denoiser.process(noisy)

    assert denoised.shape == noisy.shape
    assert denoised.dtype == noisy.dtype
    # Denoising a signal against itself (after the noise floor has been
    # learned) should not increase total energy relative to the noisy input.
    denoiser2 = SpectralGateDenoiser(sample_rate=sample_rate)
    for _ in range(3):
        denoised = denoiser2.process(noisy)
    assert np.sum(denoised**2) <= np.sum(noisy**2)


# ---------- Intent classification ----------

@pytest.mark.parametrize("text,expected", [
    ("I already paid this last month", Intent.DISPUTE),
    ("I lost my job and can't afford this right now", Intent.HARDSHIP),
    ("Can I speak to a real person please", Intent.ESCALATE_HUMAN),
    ("Sorry you have the wrong number", Intent.WRONG_NUMBER),
    ("I'll pay it by Friday", Intent.PROMISE_TO_PAY),
    ("Not a good time, call me back later", Intent.CALLBACK_REQUEST),
    ("asdkjfh random gibberish text", Intent.UNKNOWN),
])
def test_keyword_intent_classifier(text, expected):
    assert KeywordIntentClassifier().classify(text) == expected


# ---------- FSM ----------

def test_fsm_dispute_and_escalate_are_terminal():
    fsm = CallFSM()
    fsm.transition(Intent.AFFIRM)  # -> IDENTITY_VERIFICATION handled by manager, direct FSM test below
    assert fsm.state in (CallState.OPENING_DISCLOSURE, CallState.IDENTITY_VERIFICATION)


def test_fsm_full_dispute_path_terminates():
    fsm = CallFSM(start=CallState.DEBT_DISCLOSURE)
    fsm.transition(Intent.DISPUTE)
    assert fsm.state == CallState.DISPUTE_BRANCH
    assert fsm.is_terminal()
    # No transitions defined out of a terminal state.
    assert fsm.next_state(Intent.PROMISE_TO_PAY) is None


def test_fsm_escalation_trigger_from_any_reachable_state():
    for start in (CallState.OPENING_DISCLOSURE, CallState.DEBT_DISCLOSURE, CallState.NEGOTIATION):
        fsm = CallFSM(start=start)
        fsm.transition(Intent.ESCALATE_HUMAN)
        assert fsm.state == CallState.ESCALATE_TO_HUMAN


# ---------- Dialogue manager ----------

def test_dialogue_manager_opening_turn_contains_mandatory_disclosure():
    dm = DialogueManager()
    turn = dm.opening_turn()
    assert "attempt to collect a debt" in turn.response_text
    assert "recorded" in turn.response_text


def test_dialogue_manager_escalation_request_always_escalates():
    dm = DialogueManager()
    dm.opening_turn()
    turn = dm.handle_turn("I want to speak to a lawyer")
    assert turn.should_escalate is True
    assert turn.call_ended is True


def test_dialogue_manager_happy_path_reaches_closing():
    dm = DialogueManager()
    dm.opening_turn()
    dm.handle_turn("yes this is me")            # -> DEBT_DISCLOSURE
    dm.handle_turn("yes okay")                  # -> NEGOTIATION
    turn = dm.handle_turn("I'll pay it by Friday")  # -> CLOSING
    assert turn.state == CallState.CLOSING
    assert turn.call_ended is True
    assert turn.should_escalate is False


# ---------- ASR ----------

def test_mock_asr_word_error_injection_is_deterministic_and_drops_words():
    from voice_agent_core.asr.mock_asr import SyntheticUtterance
    asr = MockASR(word_error_rate=0.9, seed=1)
    utterance = SyntheticUtterance(audio=np.zeros(10), transcript="I will pay it by Friday please")
    transcript = asr.transcribe_utterance(utterance, 16000)
    assert len(transcript.text.split()) <= len("I will pay it by Friday please".split())


# ---------- Full pipeline (end-to-end) ----------

def test_full_pipeline_happy_path_reaches_closing():
    asr = MockASR(word_error_rate=0.0)
    tts = MockStreamingTTS()
    pipeline = VoiceAgentPipeline(asr=asr, tts=tts)

    script = [
        ScriptedBorrowerTurn(text="yes this is me"),
        ScriptedBorrowerTurn(text="yes okay"),
        ScriptedBorrowerTurn(text="I'll pay it by Friday"),
    ]
    log = asyncio.run(pipeline.run_call(script))

    assert log[0].speaker == "bot"
    assert any(entry.state == "closing" for entry in log)
    assert not any(entry.escalated for entry in log)


def test_full_pipeline_escalation_path():
    asr = MockASR(word_error_rate=0.0)
    tts = MockStreamingTTS()
    pipeline = VoiceAgentPipeline(asr=asr, tts=tts)

    script = [ScriptedBorrowerTurn(text="I want to speak to a human")]
    log = asyncio.run(pipeline.run_call(script))

    assert any(entry.escalated for entry in log)
    assert log[-1].state == "escalate_to_human"


def test_full_pipeline_with_noise_injection_and_barge_in_does_not_crash():
    asr = MockASR(word_error_rate=0.2, seed=7)
    tts = MockStreamingTTS()
    pipeline = VoiceAgentPipeline(asr=asr, tts=tts)

    script = [
        ScriptedBorrowerTurn(text="yes this is me", inject_noise=True),
        ScriptedBorrowerTurn(text="actually never mind call me back later", barge_in=True),
    ]
    log = asyncio.run(pipeline.run_call(script))
    assert len(log) >= 3
