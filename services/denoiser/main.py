# =============================================================================
# denoiser
# =============================================================================
#
# RESPONSIBILITY
#   Real-time speech enhancement (noise removal) for one call's inbound
#   audio, before it reaches stt-service. Runs on the media-server / CPU
#   tier. See docs/architecture.md.
#
# WHY THIS EXISTS AS ITS OWN SERVICE
#   Denoising ahead of ASR is one of the highest-leverage, lowest-cost
#   quality levers available (dramatically improves WER on noisy
#   mobile/PSTN audio) -- isolating it lets the denoise model be swapped
#   or A/B tested independently of VAD and STT. See docs/monitoring.md.
#
# STATE
#   Stateful per call: the noise-floor estimate adapts over the duration
#   of the utterance/session. One instance per session_id.
#
# API CONTRACT (planned)
#   POST /denoise
#     in:  { session_id, audio_b64 (float32 PCM mono), sample_rate }
#     out: { session_id, denoised_audio_b64, sample_rate }
#   DELETE /denoise/{session_id}   # release per-call denoiser state
#   GET /healthz
#
# DEV BACKEND (see libs/voice_agent_core/denoiser/)
#   SpectralGateDenoiser -- FFT spectral gating, numpy/scipy only, no
#   model download. Already implemented and unit-tested there.
#
# PRODUCTION BACKEND
#   DeepFilterNet (or RNNoise for the lowest-CPU-cost tier) -- real-time
#   neural denoising, meaningfully better on non-stationary noise. Swap is
#   isolated to this service's model-call layer.
# =============================================================================
