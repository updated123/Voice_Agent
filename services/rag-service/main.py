# =============================================================================
# rag-service (retrieval-augmented answers for policy/FAQ questions)
# =============================================================================
#
# RESPONSIBILITY
#   Answers off-script borrower questions that are real but outside the
#   compliance FSM's fixed intent set -- "what happens if I miss two
#   payments," "do you report to credit bureaus," "can I pay in
#   installments." Retrieves the relevant policy/FAQ passage and returns it
#   as grounded context for llm-gateway/compliance to phrase a response
#   from -- it does not itself decide what the bot is allowed to say.
#
# WHY THIS EXISTS -- THE GAP IT CLOSES
#   Without this, an off-script question either matches no known intent
#   (UNKNOWN -> re-prompt, loops the borrower) or gets escalated to a
#   human unnecessarily -- both hurt containment rate for questions that
#   have a real, correct, retrievable answer (docs/cost-analysis.md:
#   containment rate is the single biggest cost lever in the system).
#
# LOGIC / FLOW
#   1. Borrower utterance classified by llm-gateway as `faq_or_policy_question`
#      (a new intent, added to the fixed set specifically to route here)
#   2. call-orchestrator calls rag-service with the utterance + account
#      context (loan type, region -- policies vary by jurisdiction)
#   3. rag-service normalizes the query text (lowercase, strip punctuation/
#      whitespace), then runs it through the two-tier cache below
#   4. Retrieved passage(s) + original question are handed to compliance,
#      which is still the only service allowed to decide the final wording
#      and whether the retrieved answer is safe to say verbatim
#   5. If retrieval confidence is low (no passage clears a similarity
#      threshold), rag-service returns "no confident match" -- compliance
#      treats this the same as an unknown intent (re-prompt or escalate),
#      rather than letting a low-confidence retrieval reach the borrower
#
# CACHING -- TWO TIERS, BECAUSE THE TWO THINGS BEING CACHED INVALIDATE FOR
# DIFFERENT REASONS. THIS IS SPECIFIC TO rag-service; docs/architecture.md's
# other caches (llm-gateway's intent cache, tts-service's phrase cache) are
# single-tier because neither has an intermediate stable-but-expensive step
# the way RAG has an embedding sitting between the query and the final
# knowledge-base search.
#
#   Tier 1 -- Search cache (checked first; the fast, common-case path)
#     key:   (normalized_query_text, loan_type, region)
#     value: { passages, confidence }
#     invalidates: whenever the knowledge base changes (a policy update, a
#       new hardship program, a regulatory disclosure revision) -- the same
#       question can legitimately return different passages after an update,
#       even though the question's embedding hasn't changed at all.
#     HIT  -> return passages immediately, skip everything below.
#     MISS -> fall through to Tier 2.
#
#   Tier 2 -- Embedding cache (only reached on a Tier 1 miss)
#     key:   (normalized_query_text, embedding_model_version)
#     value: embedding vector
#     invalidates: only when the embedding model itself is upgraded -- the
#       embedding of a given piece of text is otherwise stable indefinitely,
#       which is exactly why it's cached separately from Tier 1 rather than
#       being invalidated every time the knowledge base changes.
#     HIT  -> reuse the cached vector, skip the GPU embedding call.
#     MISS -> generate the embedding (GPU), store it in this cache.
#     Either way: run the similarity search against the current knowledge
#     base using the embedding, then store that result in the Tier 1 search
#     cache (keyed as above) before returning.
#
#   Backend for both tiers: Aerospike (not Redis) -- same choice and same
#   p99-latency reasoning as services/session-manager, so this doesn't
#   reintroduce a second caching technology into the stack.
#
# WHAT THIS DELIBERATELY DOES NOT DO
#   It does not generate free-text answers itself and does not bypass
#   compliance -- every retrieved passage is still filtered through the
#   same FSM-based guardrail everything else in the system goes through
#   (docs/security.md). RAG closes the "no answer" gap; it doesn't create
#   a second, ungoverned path to the borrower.
#
# KNOWLEDGE BASE CONTENTS (indicative, not exhaustive)
#   Loan agreement terms and conditions, hardship/forbearance program
#   rules, credit-bureau reporting policy, payment-method FAQs,
#   region-specific regulatory disclosures (varies by jurisdiction --
#   see docs/security.md on compliance varying by region).
#
# API CONTRACT (planned)
#   POST /retrieve
#     in:  { session_id, query_text, account_context: { loan_type, region } }
#     out: { session_id, passages: [{ text, source, confidence }],
#            confident_match: bool }
#   GET /healthz
# =============================================================================
