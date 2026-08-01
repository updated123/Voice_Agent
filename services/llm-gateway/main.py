# =============================================================================
# llm-gateway (natural-language understanding)
# =============================================================================
#
# RESPONSIBILITY
#   Classifies a borrower utterance into the small, fixed intent set the
#   compliance FSM understands (promise-to-pay, dispute, hardship,
#   wrong-number, callback-request, escalate, abusive/distress, refuse,
#   affirm, unknown). Runs on the GPU pool. See docs/architecture.md.
#
# WHY THIS EXISTS AS ITS OWN SERVICE, SEPARATE FROM `compliance`
#   Owns exactly one job: NLU. It deliberately does NOT own call-flow or
#   compliance logic (mandatory disclosures, escalation transitions,
#   response templates) -- that's the `compliance` service's job, so a
#   change to the NLU model can never accidentally alter what the bot is
#   legally required to say. See docs/security.md.
#
# WHY A SMALL SELF-HOSTED MODEL, NOT A FRONTIER API
#   See docs/cost-analysis.md -- a frontier LLM per turn is both too slow
#   (blows the latency budget, docs/latency-budget.md) and too expensive
#   at 1B calls/day. A small (1-3B) fine-tuned model, continuous-batched,
#   matches quality on this narrow domain at a fraction of the cost/latency.
#
# STATE
#   Stateless: classifies one utterance per request, no session memory.
#
# API CONTRACT (planned)
#   POST /classify
#     in:  { session_id, text }
#     out: { session_id, intent, model_version }
#   GET /healthz
#
# DEV BACKEND (see libs/voice_agent_core/dialogue/intents.py)
#   KeywordIntentClassifier -- regex/keyword matching, no model. Already
#   implemented and unit-tested there.
#
# PRODUCTION BACKEND
#   Fine-tuned 1-3B LLM (e.g. Llama-3.2-3B / Phi-3-mini class), served via
#   vLLM/TensorRT-LLM with continuous batching. Swap is isolated to this
#   service's model-call layer.
# =============================================================================
