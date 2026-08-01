# =============================================================================
# compliance (call-flow / compliance-enforcement backbone)
# =============================================================================
#
# RESPONSIBILITY
#   Owns the finite state machine for the call: mandatory disclosures,
#   negotiation flow, and every escalation trigger (dispute, explicit
#   human request, abuse/distress). See docs/security.md and
#   docs/architecture.md.
#
# WHY THIS IS THE MOST IMPORTANT SERVICE IN THE SYSTEM
#   This is what converts compliance-critical behavior from "extremely
#   likely, if the model is prompted well" to "structurally guaranteed."
#   The LLM (llm-gateway) only classifies intent and, in production,
#   phrases responses WITHIN a state's allowed template -- it can never
#   skip a disclosure or fail to escalate a dispute, because those are
#   fixed transitions here, not model output.
#
# STATE
#   Intentionally STATELESS: /transition is a pure function of
#   (current_state, intent) -> (next_state, response_text, ...). The
#   actual per-call current state is owned by session-manager and
#   round-tripped by the caller (call-orchestrator) on every request.
#   This is what lets compliance scale horizontally with zero session
#   affinity -- unlike vad-service/denoiser/stt-service, which hold
#   genuinely stream-local audio state.
#
# API CONTRACT (planned)
#   GET  /opening-turn?session_id=...
#     out: { session_id, state, response_text, should_escalate, call_ended }
#     (the mandatory, fixed opening disclosure -- fires before any
#      borrower speech, so it isn't intent-driven)
#   POST /transition
#     in:  { session_id, current_state, intent, slots }
#     out: { session_id, state, response_text, should_escalate, call_ended }
#   GET /healthz
#
# REFERENCE LOGIC (see libs/voice_agent_core/dialogue/fsm.py and
# libs/voice_agent_core/dialogue/manager.py -- CallFSM, TRANSITIONS,
# RESPONSE_TEMPLATES are already implemented and unit-tested there;
# this service is the HTTP-boundary placeholder around that logic.)
# =============================================================================
