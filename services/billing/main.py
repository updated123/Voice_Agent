# =============================================================================
# billing (per-call cost metering)
# =============================================================================
#
# RESPONSIBILITY
#   Computes per-call cost (compute + telephony + human-escalation) using
#   the same unit-cost assumptions as benchmarks/cost_calculator.py --
#   single source of truth for $/GPU-hr, $/telephony-min, $/human-agent-hr.
#   See docs/cost-analysis.md.
#
# WHY THIS MATTERS MORE THAN IT LOOKS
#   docs/cost-analysis.md's key finding is that human-escalation cost
#   dominates total spend by ~10x over compute+telephony combined. This
#   service is what would let that be tracked per call in production,
#   not just at the fleet-aggregate level -- e.g. flagging which FSM
#   branches/model versions correlate with the costliest calls.
#
# PRODUCTION BACKEND
#   Consumes real metering events (GPU-seconds actually billed by the
#   cloud/datacenter, telephony CDRs from the carrier, human-agent
#   timesheets) off a Kafka topic -- see infrastructure/kafka/ -- rather
#   than being called synchronously per call.
#
# API CONTRACT (planned)
#   POST /usage
#     in:  { call_id, asr_gpu_seconds, llm_gpu_seconds, tts_gpu_seconds,
#            telephony_seconds, escalated, human_handle_seconds }
#     out: { call_id, compute_cost_usd, telephony_cost_usd,
#            human_cost_usd, total_cost_usd }
#   GET /healthz
# =============================================================================
