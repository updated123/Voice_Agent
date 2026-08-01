#!/usr/bin/env python3
"""Run a simulated end-to-end call through the full voice_agent_core pipeline
(the same logic the services/ microservices wrap over HTTP) and print the
transcript.

    python3 run_demo.py                  # happy-path call (promise-to-pay)
    python3 run_demo.py --scenario hardship
    python3 run_demo.py --scenario dispute
    python3 run_demo.py --scenario escalate
    python3 run_demo.py --scenario noisy_and_barge_in
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "libs"))

from voice_agent_core.asr.mock_asr import MockASR
from voice_agent_core.orchestrator.call_session import ScriptedBorrowerTurn
from voice_agent_core.orchestrator.pipeline import VoiceAgentPipeline
from voice_agent_core.tts.mock_tts import MockStreamingTTS

SCENARIOS = {
    "happy_path": [
        ScriptedBorrowerTurn(text="yes this is me"),
        ScriptedBorrowerTurn(text="yes okay"),
        ScriptedBorrowerTurn(text="I'll pay it by Friday"),
    ],
    "hardship": [
        ScriptedBorrowerTurn(text="yes this is me"),
        ScriptedBorrowerTurn(text="yes okay"),
        ScriptedBorrowerTurn(text="I lost my job last month and can't afford this right now"),
        ScriptedBorrowerTurn(text="I'll pay it by Friday"),
    ],
    "dispute": [
        ScriptedBorrowerTurn(text="yes this is me"),
        ScriptedBorrowerTurn(text="yes okay"),
        ScriptedBorrowerTurn(text="I already paid this, this must be a mistake"),
    ],
    "escalate": [
        ScriptedBorrowerTurn(text="I want to speak to a lawyer about this"),
    ],
    "wrong_number": [
        ScriptedBorrowerTurn(text="sorry you have the wrong number"),
    ],
    "noisy_and_barge_in": [
        ScriptedBorrowerTurn(text="yes this is me", inject_noise=True),
        ScriptedBorrowerTurn(text="actually never mind, call me back later", barge_in=True),
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="happy_path")
    parser.add_argument("--word-error-rate", type=float, default=0.0,
                        help="Simulate imperfect ASR (0.0-1.0) to see how the dialogue "
                             "manager degrades under noisy transcription.")
    args = parser.parse_args()

    asr = MockASR(word_error_rate=args.word_error_rate)
    tts = MockStreamingTTS()
    pipeline = VoiceAgentPipeline(asr=asr, tts=tts)

    log = asyncio.run(pipeline.run_call(SCENARIOS[args.scenario]))

    print(f"\n=== Scenario: {args.scenario} ===\n")
    for entry in log:
        tag = "[BOT]     " if entry.speaker == "bot" else "[BORROWER]"
        extra = []
        if entry.state:
            extra.append(f"state={entry.state}")
        if entry.intent:
            extra.append(f"intent={entry.intent}")
        if entry.barge_in:
            extra.append("BARGE-IN")
        if entry.escalated:
            extra.append("ESCALATED")
        suffix = f"  ({', '.join(extra)})" if extra else ""
        print(f"{tag} {entry.text}{suffix}")
    print()


if __name__ == "__main__":
    main()
