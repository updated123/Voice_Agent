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
# NO-RESPONSE TIMEOUT -- distinct from vad-service's hangover window
#   The hangover window (vad-service, ~150-250ms) detects "has THIS
#   utterance ended." This is a different problem: "has the borrower
#   failed to start a NEW utterance at all," on a much longer timescale --
#   e.g. they set the phone down, walked away, or the line dropped audio
#   without dropping the call itself. Without a policy for this, a silent
#   call would tie up a call-orchestrator replica and a media-server RTP
#   channel indefinitely -- real cost at 1B-calls/day scale, the same
#   "every wasted second costs money" reasoning that justifies VAD gating
#   in the first place, just at the coordinator/channel level instead of
#   the GPU level.
#
#   Every bot turn that expects a reply starts a timer (any turn except
#   the final closing statement). vad-service reporting "speech" at ANY
#   point cancels whichever stage below the timer is in and resumes
#   normal turn handling -- this is escalating patience, not a hard
#   cutoff regardless of activity:
#
#     Bot finishes speaking
#           |
#           v
#     [WAITING] --- speech detected ---> cancelled, normal turn resumes
#           |
#           | ~5-8s of continued silence
#           v
#     [RE-PROMPT] -- plays "Are you still there?" / repeats the question
#           |
#           |-- speech detected ---> cancelled, normal turn resumes
#           |
#           | ~10-15s more of continued silence
#           v
#     [GRACEFUL_END] -- plays a short closing line, then ends the call
#
#   Total elapsed unresponsive time before ending: ~20-30s, not a full
#   minute -- waiting longer than that before acting is itself the
#   cost/scale mistake, not just a UX one.
#
#   OUTCOME LOGGING: ends in a NO_RESPONSE outcome (see docs/monitoring.md),
#   distinct from every existing FSM terminal state. This matters because
#   containment-rate and escalation-rate (the metrics driving the
#   dominant-cost-line-item finding in docs/cost-analysis.md) would
#   otherwise be silently contaminated -- a dead-air call is neither "the
#   bot resolved it" nor "a human was needed," and letting it fall into
#   either bucket would quietly bias both.
#
#   FEEDS BACK TO scheduler: a NO_RESPONSE outcome is a distinct retry
#   signal from an explicit hang-up or a completed call -- possibly a
#   dropped connection rather than genuine non-responsiveness, worth
#   flagging for a sooner retry rather than treated identically to a
#   borrower who explicitly refused or hung up.
#
#   SAFETY-NET VALUE: also a backstop against scheduler's AMD
#   (answering-machine-detection) false negatives -- if AMD wrongly
#   classifies a voicemail/hold-music pickup as a live human connect,
#   this timeout eventually ends a call that would otherwise run
#   indefinitely against nothing.
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
