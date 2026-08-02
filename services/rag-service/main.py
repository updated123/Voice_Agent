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
#   3. rag-service embeds the query, retrieves the top-K matching passages
#      from a vetted, legally-reviewed knowledge base (loan agreement terms,
#      hardship program rules, regulatory disclosures, common FAQ answers)
#   4. Retrieved passage(s) + original question are handed to compliance,
#      which is still the only service allowed to decide the final wording
#      and whether the retrieved answer is safe to say verbatim
#   5. If retrieval confidence is low (no passage clears a similarity
#      threshold), rag-service returns "no confident match" -- compliance
#      treats this the same as an unknown intent (re-prompt or escalate),
#      rather than letting a low-confidence retrieval reach the borrower
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
