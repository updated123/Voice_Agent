# =============================================================================
# analytics (call-outcome logging & rollup metrics)
# =============================================================================
#
# RESPONSIBILITY
#   Logs every call's outcome (final state, escalation, intents seen,
#   turn latency) and computes the rollup metrics that feed the quality
#   evaluation loop -- containment rate, escalation-trigger recall, task
#   success rate, promise-to-pay rate. See docs/monitoring.md for the
#   full metric definitions and targets.
#
# PRODUCTION BACKEND
#   A real event pipeline: call-orchestrator/compliance emit events onto
#   a Kafka topic (see infrastructure/kafka/), consumed into an analytics
#   warehouse (e.g. for the offline regression suite and canary
#   comparisons described in docs/monitoring.md). This service, in a real
#   deployment, would be the Kafka producer-facing API, not the storage
#   layer itself.
#
# API CONTRACT (planned)
#   POST /events
#     in:  { call_id, event_type, final_state?, intent?, escalated?,
#            turn_latency_ms?, metadata? }
#     out: { recorded: true, total_events }
#   GET /events/{call_id}          -> all logged events for one call
#   GET /metrics/summary           -> rollup: escalation_rate,
#                                     containment_rate, promise_to_pay_rate,
#                                     avg_turn_latency_ms, outcome_breakdown
#   GET /healthz
# =============================================================================
