# =============================================================================
# stt-service (speech-to-text / ASR)
# =============================================================================
#
# RESPONSIBILITY
#   Transcribes one VAD-segmented borrower utterance. Runs on the GPU
#   pool. See docs/architecture.md and docs/scaling.md for the GPU-count
#   math (~22K GPUs at conservative 1B/day peak concurrency).
#
# WHY THIS EXISTS AS ITS OWN SERVICE
#   ASR is the single largest GPU-compute line item (docs/cost-analysis.md)
#   and scales independently of VAD/denoise (CPU) and TTS (GPU, but
#   different throughput profile) -- it needs its own autoscaling group.
#
# STATE
#   Stateless per request: transcribes one already-segmented utterance at
#   a time. A real streaming backend would instead expose partial-result
#   callbacks as audio arrives (see docs/latency-budget.md, stage [2]).
#
# API CONTRACT (planned)
#   POST /transcribe
#     in:  { session_id, audio_b64 (float32 PCM), sample_rate }
#     out: { session_id, text, is_final, confidence }
#   GET /healthz
#
# DEV BACKEND (see libs/voice_agent_core/asr/)
#   MockASR -- no acoustic model; reads ground-truth text attached to a
#   SyntheticUtterance and optionally injects word-error-rate to simulate
#   a realistic, imperfect ASR channel. Already implemented and
#   unit-tested there.
#
# PRODUCTION BACKEND
#   Self-hosted streaming Conformer / distil-Whisper, served via
#   CTranslate2 or NVIDIA Riva, continuous-batched across concurrent
#   calls. Swap is isolated to this service's model-call layer.
# =============================================================================
