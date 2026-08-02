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
# API CONTRACT (planned) -- gRPC, bidirectional streaming, not REST-per-frame
#   This hop carries a continuous stream of audio frames for the life of a
#   call, tens of times a second -- a REST call per frame would pay a new
#   connection/header/JSON-serialization cost on every single frame, which
#   is real, measurable latency against the ~150-250ms VAD budget
#   (docs/latency-budget.md), not a style preference. gRPC keeps one
#   long-lived HTTP/2 stream open per call and frames ride it as small
#   protobuf messages. See docs/architecture.md, "Key architectural
#   decisions" #8, and the Technology choices table.
#
#   service VadService {
#     rpc StreamFrames(stream VadFrame) returns (stream VadEvent);
#   }
#   VadFrame:  { session_id, frame (bytes, PCM16 mono), sample_rate, hangover_ms }
#   VadEvent:  { session_id, event }   # event: "speech" | "silence" | "end_of_speech"
#   Stream close (client half-close or call teardown) releases per-call VAD state --
#   no separate DELETE call needed, unlike a REST resource.
#   GET /healthz stays plain HTTP -- it's a one-shot liveness check, not part
#   of the audio stream, so REST is the right tool for it.
#
# DEV BACKEND (see libs/voice_agent_core/vad/)
#   EnergyVAD + HangoverVAD -- energy/zero-crossing-rate based, CPU-only,
#   no model download. Already implemented and unit-tested there.
#
# PRODUCTION BACKEND
#   Silero-VAD (ONNX export), still CPU-only. Swap is isolated to this
#   service's model-call layer -- the API contract above does not change.
# =============================================================================
