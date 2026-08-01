"""Reference prototype of the loan-collection voice agent pipeline.

See docs/ at the repo root for the full system design this implements a
scaled-down, runnable slice of: VAD -> denoiser -> ASR -> dialogue manager
(FSM + intent classifier) -> TTS, wired together by an asyncio orchestrator
with barge-in support.
"""
