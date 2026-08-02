# =============================================================================
# tool-gateway (formalized tool calling -- the bot never invents a fact)
# =============================================================================
#
# RESPONSIBILITY
#   The single, named-function boundary between the conversation and every
#   external system of record (loan servicing backend, CRM, payment
#   scheduling). Every fact the bot states about an account, and every
#   action it takes on one, goes through a named tool call here -- never
#   through the LLM generating a number or a decision from its own
#   "judgment."
#
# WHY THIS EXISTS -- THE GAP IT CLOSES
#   Before this service was named explicitly, `compliance` narratively
#   "called out" to the loan servicing backend for lookups and writes
#   (docs/architecture.md), but that was informal -- no defined tool
#   contract, no enforced allow-list of what the bot is permitted to
#   call. Formalizing it here means adding a new capability (e.g. a
#   "waive late fee" action) is a reviewed, explicit addition to this
#   gateway's tool registry -- not an implicit side effect of a prompt
#   change somewhere else.
#
# LOGIC / FLOW (example: "how much do I owe?")
#   1. llm-gateway classifies the utterance's intent (e.g. `balance_inquiry`)
#   2. compliance's FSM transition for that intent specifies which tool(s)
#      it needs filled in before it can render its response template
#   3. call-orchestrator calls tool-gateway: `getOutstandingBalance(account_id)`
#   4. tool-gateway calls the loan servicing backend, gets back a real
#      number, returns it as a structured value -- never as free text
#   5. compliance substitutes that value into its (already-decided)
#      response template's {amount_due} slot
#
# TOOL REGISTRY (indicative, not exhaustive)
#   getLoanDetails(account_id), getOutstandingBalance(account_id),
#   schedulePayment(account_id, date, amount), updateCRM(account_id, outcome),
#   checkIdentity(account_id, challenge_response), requestHumanTransfer(reason)
#
# WHY THIS IS SEPARATE FROM compliance
#   compliance decides WHAT to do (the FSM transition); tool-gateway
#   decides HOW that decision reaches an external system. Keeping them
#   separate means the tool registry (what systems exist, what functions
#   are callable, their auth scopes) can change without touching the
#   compliance FSM, and vice versa.
#
# STATE
#   Stateless -- each call is a single named function invocation with its
#   own inputs/outputs; no session memory here (that's session-manager's job).
#
# API CONTRACT (planned)
#   POST /tools/{tool_name}/invoke
#     in:  { session_id, account_id, args: { ...tool-specific } }
#     out: { session_id, tool_name, result, error? }
#   GET /tools                 -- list the registered, allowed tool set
#   GET /healthz
# =============================================================================
