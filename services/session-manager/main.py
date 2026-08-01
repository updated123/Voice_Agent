# =============================================================================
# session-manager (externalized call-state store)
# =============================================================================
#
# RESPONSIBILITY
#   Holds the authoritative record of every in-progress call: current FSM
#   state, account slots, transcript log, escalation flag. See
#   docs/architecture.md -- "stateless workers + call state lives in a
#   fast external store" is the principle that lets every other service
#   (call-orchestrator, compliance, llm-gateway) crash and be replaced
#   mid-call without losing the call.
#
# PRODUCTION BACKEND
#   Redis, keyed by call-id, with a TTL and proper concurrency control
#   (optimistic locking / atomic updates) -- see infrastructure/redis/.
#   This service, in a real deployment, would be a thin API layer over
#   Redis rather than holding state in its own process memory (a single
#   process's dict is not durable and not safe across multiple replicas).
#
# API CONTRACT (planned)
#   POST   /sessions                 { session_id, slots } -> session record
#   GET    /sessions/{session_id}    -> session record
#   PATCH  /sessions/{session_id}    { state?, transcript_entry?, escalated?,
#                                       call_ended? } -> updated session record
#   DELETE /sessions/{session_id}    -> close/release
#   GET /healthz
#
#   Session record shape:
#     { session_id, state, slots, transcript[], escalated, call_ended,
#       created_at, updated_at }
# =============================================================================
