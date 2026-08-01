# =============================================================================
# vad-service
# =============================================================================
#
# RESPONSIBILITY
#   Frame-level voice-activity detection + end-of-speech ("hangover")
#   timing for one call. Runs on the media-server / CPU tier, upstream of
#   stt-service -- never on the GPU pools. See docs/architecture.md and
#   docs/scaling.md.
#
# WHY THIS EXISTS AS ITS OWN SERVICE
#   Every millisecond of silence/noise that reaches stt-service is wasted
#   GPU spend at 1B-calls/day scale (see docs/cost-analysis.md). Isolating
#   VAD as its own hop keeps that gating logic swappable (dev energy-based
#   VAD -> production Silero-VAD) without touching anything downstream.
#
# STATE
#   Stateful per call: the hangover window tracks how long silence has run
#   since the last detected speech frame. One VAD instance would be kept
#   per session_id, sticky-routed to the call's media server in production.
#
# API CONTRACT (planned)
#   POST /vad/frame
#     in:  { session_id, frame_b64 (PCM16 mono audio frame), sample_rate,
#            hangover_ms }
#     out: { session_id, event }   # event: "speech" | "silence" | "end_of_speech"
#   DELETE /vad/{session_id}       # release per-call VAD state
#   GET /healthz
#
# DEV BACKEND (see libs/voice_agent_core/vad/)
#   EnergyVAD + HangoverVAD -- energy/zero-crossing-rate based, CPU-only,
#   no model download. Already implemented and unit-tested there.
#
# PRODUCTION BACKEND
#   Silero-VAD (ONNX export), still CPU-only. Swap is isolated to this
#   service's model-call layer -- the API contract above does not change.
# =============================================================================
