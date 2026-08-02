# =============================================================================
# llm-gateway (natural-language understanding: intent + sentiment + tier routing)
# =============================================================================
#
# RESPONSIBILITY
#   Classifies a borrower utterance into the small, fixed intent set the
#   compliance FSM understands (promise-to-pay, dispute, hardship,
#   wrong-number, callback-request, escalate, abusive/distress, refuse,
#   affirm, unknown), PLUS the two responsibilities folded in below
#   (sentiment, model-tier routing). Runs on the GPU pool. See
#   docs/architecture.md.
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
#     in:  { session_id, text, audio_b64? }
#     out: { session_id, intent, sentiment, model_version, model_tier }
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
#
# -----------------------------------------------------------------------
# FOLDED IN: sentiment detection (previously a standalone service)
# -----------------------------------------------------------------------
#   RESPONSIBILITY: detects the borrower's emotional state from voice tone
#   (calm / frustrated / distressed / angry), not just word choice, and
#   attaches it to the turn alongside intent -- so compliance's FSM can key
#   on (state, intent, sentiment) for the handful of transitions where tone
#   should change the response (e.g. frustrated + negotiation ->
#   acknowledge concern before continuing; angry + any state -> lower
#   escalation threshold, rather than requiring a hardcoded distress
#   phrase). Runs on the same denoised audio segment stt-service
#   transcribes.
#
#   WHY IT WAS FOLDED HERE, NOT LEFT AS ITS OWN SERVICE: it doesn't scale,
#   deploy, or fail independently of intent classification -- both consume
#   the same utterance, on the same GPU pool, on the same request path, and
#   produce sibling outputs compliance reads together. Splitting them into
#   two network hops bought no real isolation (a self-critique of the
#   original 16-service design found this to be a "soft" justification --
#   see docs/future-improvements.md), only an extra hop's worth of latency
#   and an extra deploy unit to operate. Auditability (docs/security.md's
#   requirement to explain why the bot did what it did) is preserved by
#   keeping intent and sentiment as separate, distinctly-logged fields in
#   the same response, not by keeping them in separate services.
#
#   PRODUCTION BACKEND: a small audio-tone classifier (prosody/pitch/energy
#   features, or a lightweight speech-emotion-recognition model) running
#   alongside the intent model in the same serving process.
#
# -----------------------------------------------------------------------
# FOLDED IN: model-tier routing (previously "model-router")
# -----------------------------------------------------------------------
#   RESPONSIBILITY: decides, per turn, which model tier actually runs --
#   a cheap/fast tier for the common easy case (simple FAQ-shaped
#   utterances, high-confidence keyword-adjacent phrases), a larger tier
#   only for turns that need it (ambiguous phrasing, multi-part
#   objections, negotiation nuance). See docs/cost-analysis.md and
#   architecture/cost-latency-calculator.html for the per-tier cost/latency
#   deltas this is meant to exploit.
#
#   LOGIC: a cheap pre-classifier (regex/keyword match, or a tiny
#   confidence-scored model) decides easy-or-hard before the main
#   classification call; easy turns run the small tier, hard turns run the
#   larger one. The decision is logged (via analytics) so the split can be
#   tuned over time.
#
#   GUARDRAIL: routing to a cheaper tier must never reduce
#   escalation-trigger recall (docs/monitoring.md) -- anything the
#   pre-classifier isn't confident about defaults to the larger tier, not
#   the cheaper one.
#
#   WHY IT WAS FOLDED HERE, NOT LEFT AS ITS OWN SERVICE: routing "which
#   model should classify this" is an implementation detail of the
#   classification call itself, not a decision any other service needs to
#   observe or act on independently -- it never had a real reason to be a
#   separate network hop with its own deploy lifecycle. It's an internal
#   function of this service's model-call layer, the same way choosing
#   which specific model file to load already is.
# =============================================================================
