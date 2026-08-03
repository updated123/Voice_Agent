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
#
# -----------------------------------------------------------------------
# EXECUTION ORDER OF THE THREE FOLDED-IN SUB-TASKS -- DECIDED, NOT LEFT AMBIGUOUS
# -----------------------------------------------------------------------
#   Folding three responsibilities into one service (this file) doesn't
#   automatically decide whether they run sequentially or concurrently --
#   that was left unstated after the fold and is decided explicitly here:
#
#     routing (tiny/cheap) --> intent (small or large tier, per routing)
#                          \
#                           +--> sentiment (independent audio-tone model)
#                          /       [runs CONCURRENTLY with routing+intent]
#
#   - `routing` MUST precede `intent`: it decides which model tier intent
#     classification runs on, so it's a real sequential dependency, not an
#     arbitrary ordering choice.
#   - `sentiment` has NO dependency on intent or its model tier -- it's a
#     separate classifier over the same audio segment. It runs concurrently
#     with the routing+intent chain, not after it.
#
#   LATENCY CONSEQUENCE (docs/latency-budget.md stage [3], ~30-80ms):
#   this keeps that budget close to accurate rather than roughly tripling
#   it. Critical path per turn is max(routing_time + intent_time,
#   sentiment_time), not the sum of all three -- routing is a cheap
#   pre-classifier (near-negligible), so the path is dominated by
#   whichever of {intent, sentiment} is slower. The budget may need a
#   small upward revision (routing's own overhead), not a multiplicative
#   one.
#
#   GPU/THROUGHPUT CONSEQUENCE (docs/scaling.md's 5,556-GPU figure):
#   concurrency does NOT mean free -- running intent and sentiment at the
#   same time still requires GPU capacity for both simultaneously, it just
#   avoids adding their latencies together. The 5,556 figure was sized for
#   one classification pass; it's still an underestimate with this
#   execution order, but a smaller one than a naive "3x" reading of
#   "three sub-tasks" would suggest, because: (a) `routing` is a cheap
#   pre-classifier (regex or a tiny model), near-negligible GPU cost, and
#   (b) `sentiment`'s production backend is explicitly a small/lightweight
#   model (prosody/pitch/energy features), not a second full 1-3B LLM
#   forward pass. Treat the real figure as somewhat higher than 5,556 --
#   plausibly 20-50% more GPU capacity to run sentiment alongside intent
#   at the same concurrency, not 2-3x -- and, as scaling.md already says,
#   replace this whole estimate with a load-test result before committing
#   to hardware.
# =============================================================================
