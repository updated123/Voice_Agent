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
#   Aerospike, keyed by call-id, with a TTL and proper concurrency control
#   (optimistic locking / atomic updates) -- see infrastructure/aerospike/.
#   Chosen over Redis Cluster after comparing both against this system's
#   actual peak load (~370,000 session ops/sec): both clear the required
#   throughput, but Aerospike's 17-48% lower p99 latency (independent
#   benchmarks) matters more here, since every stage in
#   docs/latency-budget.md's turn-taking budget is milliseconds-accountable
#   and Redis's single-threaded event loop can tail into multi-second p99
#   under high concurrency. Redis Cluster remains a documented, fully
#   valid alternative (infrastructure/redis/) if ecosystem maturity is
#   weighted higher than the p99 gap. Either way, this service in a real
#   deployment would be a thin API layer over that store rather than
#   holding state in its own process memory (a single process's dict is
#   not durable and not safe across multiple replicas).
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
