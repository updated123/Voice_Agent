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
#
# -----------------------------------------------------------------------
# SEMANTIC ENDPOINTING -- gates the hangover timer, doesn't replace it
# -----------------------------------------------------------------------
#   THE PROBLEM: pure acoustic silence-duration VAD cannot distinguish a
#   mid-sentence thinking-pause from a genuine end-of-turn -- a 400ms pause
#   in the middle of a sentence is acoustically identical to a 400ms pause
#   at the end of one. "I'll pay... uh... by Friday": if the pause around
#   "uh" exceeds the hangover window (real disfluency pauses run 300ms-1s,
#   not reliably under 250ms), this service fires end_of_speech early,
#   fragmenting one utterance into two independent turns downstream, with
#   nothing in compliance/llm-gateway able to recognize the second as a
#   continuation of the first. Retuning hangover_ms cannot fix this: the
#   same knob that would catch disfluencies faster also makes ordinary
#   pauses trigger false cutoffs -- it's a real ceiling on acoustic-only
#   detection, not a tuning gap.
#
#   THE FIX -- industry-standard, not a bespoke idea (Deepgram Flux,
#   AssemblyAI Universal-Streaming/Universal-3 Pro, and LiveKit's
#   transcript-based end-of-utterance model all do a version of this):
#   when the acoustic hangover timer is about to expire, don't fire
#   end_of_speech unconditionally -- run a lightweight completeness check
#   against stt-service's already-streaming PARTIAL transcript for the
#   current utterance (the same partial stream docs/latency-budget.md
#   stage [2] already produces for early classification; this reuses it,
#   it isn't a new data source). The check looks at grammatical
#   completeness, trailing filler words/conjunctions ("uh", "and", "so"),
#   and available intonation cues (falling pitch -> likely done; rising
#   or flat -> likely continuing). If the partial looks incomplete,
#   extend the hangover window briefly (one more hangover period) instead
#   of firing end_of_speech; if it looks complete, or the extension also
#   times out, finalize as normal.
#
#   WHY THIS STAYS CHEAP: the acoustic gate is still the default,
#   always-on, CPU-only path for every turn -- the semantic check only
#   runs in the specific moment the hangover timer is about to expire,
#   not continuously. It adds cost in the disfluency edge case only, so
#   docs/latency-budget.md stage [1]'s ~150-250ms figure still holds for
#   the common case.
#
#   NEW DEPENDENCY THIS INTRODUCES: this service now needs read access to
#   stt-service's in-flight partial transcript for the SAME utterance --
#   a feedback path in the opposite direction of the normal
#   vad-service -> stt-service data flow. Whether that's wired directly
#   (stt-service pushes partials back to the owning vad-service instance)
#   or brokered through call-orchestrator (which already talks to both)
#   is an implementation choice not decided here; either way it's a new
#   coupling worth calling out explicitly rather than leaving implicit.
# =============================================================================
