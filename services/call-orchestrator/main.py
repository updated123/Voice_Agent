# =============================================================================
# call-orchestrator (per-call pipeline coordinator)
# =============================================================================
#
# RESPONSIBILITY
#   The service that ties every other service together for one call's
#   duration: media server hands it audio -> vad-service ->
#   denoiser -> stt-service -> llm-gateway (classify intent) ->
#   compliance (FSM transition + response text) -> tts-service ->
#   back to the media server. Reads/writes call state via
#   session-manager on every turn (this service holds no state itself).
#   See docs/architecture.md for the full sequence.
#
# SCALE NOTE
#   At the 1B-calls/day peak (~2.2M concurrent calls, docs/scaling.md),
#   this is the service with the most replicas -- one lightweight
#   coordinator process per concurrently active call, horizontally
#   autoscaled, stateless (all state lives in session-manager) so any
#   instance can pick up any call's next turn.
#
# BARGE-IN HANDLING
#   Continuously watches vad-service's events even while tts-service is
#   streaming a response; on a barge-in event it stops reading the
#   tts-service stream and routes the new borrower audio through the
#   normal pipeline as the next turn. Target: interrupt-to-silence
#   ~100ms -- see docs/latency-budget.md.
#
# API CONTRACT (planned)
#   POST /calls                    { call_id, borrower_id } -> starts a
#                                   call: creates a session-manager
#                                   record, plays the opening disclosure
#   POST /calls/{call_id}/turns    { borrower_audio_b64 } -> runs one
#                                   full pipeline turn, returns the bot's
#                                   next response + call status
#   POST /calls/{call_id}/end      -> tears down the call, final
#                                   analytics + billing events emitted
#   GET /healthz
#
# REFERENCE LOGIC (see libs/voice_agent_core/orchestrator/pipeline.py --
# the same VAD->denoise->ASR->dialogue->TTS sequence, already implemented
# and unit-tested there as a single in-process pipeline; this service is
# the same sequence expressed as HTTP calls across service boundaries.)
# =============================================================================
