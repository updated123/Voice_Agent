# =============================================================================
# model-router (send simple turns to a small model, hard turns to a bigger one)
# =============================================================================
#
# RESPONSIBILITY
#   Decides, per turn, which model tier llm-gateway should actually run --
#   a cheap/fast model for the common, easy case (simple FAQ-shaped
#   utterances, high-confidence keyword-adjacent phrases) and a larger,
#   more capable model only for turns that need it (ambiguous phrasing,
#   multi-part objections, negotiation nuance).
#
# WHY THIS EXISTS -- THE GAP IT CLOSES
#   docs/cost-analysis.md and architecture/cost-latency-calculator.html
#   already document multiple LLM tiers with real cost/latency deltas
#   (small self-hosted vs. larger self-hosted vs. frontier API) -- but
#   today that choice is a static, deployment-time decision (you pick
#   one model and every turn uses it). This service is what would make
#   it a per-request decision instead, which is where the real savings
#   are: most turns in a scripted collections flow ARE the easy case.
#
# LOGIC / FLOW
#   1. call-orchestrator sends the transcript to model-router instead of
#      directly to llm-gateway
#   2. model-router applies a cheap pre-classifier (regex/keyword match
#      against the known-easy patterns, or a tiny confidence-scored
#      model) to decide: easy or hard
#   3. Easy turns route to the small/fast llm-gateway tier; hard turns
#      route to the larger tier
#   4. Routing decision is logged (via analytics) so the split can be
#      tuned over time -- if the "hard" tier is getting hit far more or
#      less often than expected, that's a signal the routing threshold
#      needs adjusting
#
# WHY THIS IS SEPARATE FROM llm-gateway
#   llm-gateway's job is classification; model-router's job is a cost/
#   latency decision about HOW to classify. Keeping them separate means
#   the routing policy (thresholds, which tiers exist) can be tuned
#   without touching the classifier itself, and the classifier doesn't
#   need to know its own cost tier.
#
# THE GUARDRAIL THIS NEEDS (so containment/compliance don't regress)
#   Routing to a cheaper model must never be allowed to reduce
#   escalation-trigger recall (docs/monitoring.md's guardrail against
#   optimizing containment at the expense of correctly detecting when a
#   human is needed) -- the pre-classifier's "easy" bucket should be
#   conservative, and anything it's not confident about should default
#   to the larger tier, not the cheaper one.
#
# STATE
#   Stateless -- a per-turn routing decision, no memory between turns.
#
# API CONTRACT (planned)
#   POST /route
#     in:  { session_id, text }
#     out: { session_id, tier: "small" | "large", routing_confidence }
#   GET /healthz
# =============================================================================
