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
# API CONTRACT (planned) -- gRPC, bidirectional streaming, not REST-per-frame
#   Same reasoning as vad-service: this is a continuous per-call audio
#   stream, not a one-shot request, so it rides gRPC over one long-lived
#   HTTP/2 connection instead of paying REST's per-frame connection/header
#   cost tens of times a second. See docs/architecture.md, "Key
#   architectural decisions" #8.
#
#   service DenoiserService {
#     rpc StreamAudio(stream AudioChunk) returns (stream AudioChunk);
#   }
#   AudioChunk: { session_id, audio (bytes, float32 PCM mono), sample_rate }
#   Stream close releases per-call denoiser (noise-floor estimate) state --
#   no separate DELETE call needed.
#   GET /healthz stays plain HTTP -- one-shot liveness check, not part of
#   the audio stream.
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
