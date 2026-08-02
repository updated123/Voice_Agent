# =============================================================================
# compliance (call-flow / compliance-enforcement backbone)
# =============================================================================
#
# RESPONSIBILITY
#   Owns the finite state machine for the call: mandatory disclosures,
#   negotiation flow, and every escalation trigger (dispute, explicit
#   human request, abuse/distress). See docs/security.md and
#   docs/architecture.md.
#
# WHY THIS IS THE MOST IMPORTANT SERVICE IN THE SYSTEM
#   This is what converts compliance-critical behavior from "extremely
#   likely, if the model is prompted well" to "structurally guaranteed."
#   The LLM (llm-gateway) only classifies intent and, in production,
#   phrases responses WITHIN a state's allowed template -- it can never
#   skip a disclosure or fail to escalate a dispute, because those are
#   fixed transitions here, not model output.
#
# STATE
#   Intentionally STATELESS: /transition is a pure function of
#   (current_state, intent) -> (next_state, response_text, ...). The
#   actual per-call current state is owned by session-manager and
#   round-tripped by the caller (call-orchestrator) on every request.
#   This is what lets compliance scale horizontally with zero session
#   affinity -- unlike vad-service/denoiser/stt-service, which hold
#   genuinely stream-local audio state.
#
# API CONTRACT (planned)
#   GET  /opening-turn?session_id=...
#     out: { session_id, state, response_text, should_escalate, call_ended }
#     (the mandatory, fixed opening disclosure -- fires before any
#      borrower speech, so it isn't intent-driven)
#   POST /transition
#     in:  { session_id, current_state, intent, slots }
#     out: { session_id, state, response_text, should_escalate, call_ended }
#   GET /healthz
#
# REFERENCE LOGIC (see libs/voice_agent_core/dialogue/fsm.py and
# libs/voice_agent_core/dialogue/manager.py -- CallFSM, TRANSITIONS,
# RESPONSE_TEMPLATES are already implemented and unit-tested there;
# this service is the HTTP-boundary placeholder around that logic.)
#
# -----------------------------------------------------------------------
# FOLDED IN: tool calling (previously a standalone service, "tool-gateway")
# -----------------------------------------------------------------------
#   RESPONSIBILITY: the single, named-function boundary between the
#   conversation and every external system of record (loan servicing
#   backend, CRM, payment scheduling). Every fact the bot states about an
#   account, and every action it takes on one, goes through a named tool
#   call here -- never through the LLM generating a number or a decision
#   from its own "judgment."
#
#   TOOL REGISTRY (indicative, not exhaustive): getLoanDetails(account_id),
#   getOutstandingBalance(account_id), schedulePayment(account_id, date,
#   amount), updateCRM(account_id, outcome), checkIdentity(account_id,
#   challenge_response), requestHumanTransfer(reason)
#
#   LOGIC / FLOW (example: "how much do I owe?")
#     1. llm-gateway classifies the utterance's intent (e.g. `balance_inquiry`)
#     2. This service's FSM transition for that intent specifies which
#        tool(s) it needs filled in before it can render its response
#        template
#     3. The tool call executes against the loan servicing backend, gets
#        back a real number, returns it as a structured value -- never as
#        free text
#     4. The response template's {amount_due} slot is filled with that
#        value
#
#   WHY IT WAS FOLDED HERE, NOT LEFT AS ITS OWN SERVICE: the original
#   split was justified as "compliance decides WHAT to do, tool-gateway
#   decides HOW that reaches an external system" -- a real distinction,
#   but one that doesn't require a second network hop to preserve. Only
#   `compliance` ever called it (a self-critique of the original
#   16-service design found this to be a "soft" justification -- see
#   docs/future-improvements.md); nothing else in the system needs to
#   invoke a tool independently of an FSM transition deciding to. The
#   WHAT/HOW distinction is preserved as an internal module boundary
#   (a distinct function per tool, a reviewed allow-list, structured
#   values only -- never free text from the LLM) rather than a service
#   boundary. Auth scopes and the allow-list are still owned by this
#   module specifically, not scattered through FSM transition logic, so
#   adding a new tool is still a reviewed, explicit registry change.
#
#   API CONTRACT (internal, not borrower-facing):
#     invoke_tool(tool_name, session_id, account_id, args) -> { result, error? }
#     list_tools() -> the registered, allowed tool set
# =============================================================================
