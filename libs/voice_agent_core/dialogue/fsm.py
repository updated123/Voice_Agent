"""Finite state machine for the call flow.

This is the compliance backbone described in docs/architecture.md
and docs/security.md: mandatory disclosures and escalation
triggers are structural (fixed states/transitions), not left to whatever an
LLM decides to say. The dialogue manager (manager.py) drives this FSM using
intents classified from borrower speech.
"""

from enum import Enum
from typing import Optional

from .intents import Intent


class CallState(str, Enum):
    OPENING_DISCLOSURE = "opening_disclosure"       # mandatory: who's calling, AI-disclosure, recording notice
    IDENTITY_VERIFICATION = "identity_verification"  # partial, non-sensitive challenge
    DEBT_DISCLOSURE = "debt_disclosure"              # mandatory: "attempt to collect a debt", amount, due date
    NEGOTIATION = "negotiation"                      # main branch: agree on payment date/plan
    HARDSHIP_BRANCH = "hardship_branch"              # conservative branch, offers hardship program / human
    DISPUTE_BRANCH = "dispute_branch"                # routes to human/dispute process
    WRONG_NUMBER_CLOSE = "wrong_number_close"         # polite close, flags number for removal
    CALLBACK_SCHEDULED = "callback_scheduled"
    ESCALATE_TO_HUMAN = "escalate_to_human"           # hard exit to human queue -- see docs/security.md
    CLOSING = "closing"
    ENDED = "ended"


# (current_state, intent) -> next_state
# Any intent not covered by a state's row falls through to a state-specific
# default handled in DialogueManager (e.g. NEGOTIATION treats UNKNOWN as
# "re-prompt", not as a silent no-op).
TRANSITIONS: dict[CallState, dict[Intent, CallState]] = {
    CallState.OPENING_DISCLOSURE: {
        Intent.AFFIRM: CallState.IDENTITY_VERIFICATION,
        Intent.WRONG_NUMBER: CallState.WRONG_NUMBER_CLOSE,
        Intent.CALLBACK_REQUEST: CallState.CALLBACK_SCHEDULED,
        Intent.ESCALATE_HUMAN: CallState.ESCALATE_TO_HUMAN,
        Intent.ABUSIVE_OR_DISTRESS: CallState.ESCALATE_TO_HUMAN,
    },
    CallState.IDENTITY_VERIFICATION: {
        Intent.AFFIRM: CallState.DEBT_DISCLOSURE,
        Intent.WRONG_NUMBER: CallState.WRONG_NUMBER_CLOSE,
        Intent.CALLBACK_REQUEST: CallState.CALLBACK_SCHEDULED,
        Intent.ESCALATE_HUMAN: CallState.ESCALATE_TO_HUMAN,
        Intent.ABUSIVE_OR_DISTRESS: CallState.ESCALATE_TO_HUMAN,
    },
    CallState.DEBT_DISCLOSURE: {
        Intent.DISPUTE: CallState.DISPUTE_BRANCH,
        Intent.HARDSHIP: CallState.HARDSHIP_BRANCH,
        Intent.CALLBACK_REQUEST: CallState.CALLBACK_SCHEDULED,
        Intent.ESCALATE_HUMAN: CallState.ESCALATE_TO_HUMAN,
        Intent.ABUSIVE_OR_DISTRESS: CallState.ESCALATE_TO_HUMAN,
        Intent.AFFIRM: CallState.NEGOTIATION,
        Intent.PROMISE_TO_PAY: CallState.CLOSING,
    },
    CallState.NEGOTIATION: {
        Intent.PROMISE_TO_PAY: CallState.CLOSING,
        Intent.HARDSHIP: CallState.HARDSHIP_BRANCH,
        Intent.DISPUTE: CallState.DISPUTE_BRANCH,
        Intent.CALLBACK_REQUEST: CallState.CALLBACK_SCHEDULED,
        Intent.ESCALATE_HUMAN: CallState.ESCALATE_TO_HUMAN,
        Intent.ABUSIVE_OR_DISTRESS: CallState.ESCALATE_TO_HUMAN,
        Intent.REFUSE: CallState.CALLBACK_SCHEDULED,
    },
    CallState.HARDSHIP_BRANCH: {
        Intent.ESCALATE_HUMAN: CallState.ESCALATE_TO_HUMAN,
        Intent.ABUSIVE_OR_DISTRESS: CallState.ESCALATE_TO_HUMAN,
        Intent.PROMISE_TO_PAY: CallState.CLOSING,
        Intent.CALLBACK_REQUEST: CallState.CALLBACK_SCHEDULED,
    },
    CallState.DISPUTE_BRANCH: {},   # every path out of a dispute goes to a human -- see docs/security.md
    CallState.CALLBACK_SCHEDULED: {},
    CallState.WRONG_NUMBER_CLOSE: {},
    CallState.ESCALATE_TO_HUMAN: {},
    CallState.CLOSING: {},
    CallState.ENDED: {},
}

# States that always terminate the bot's turn of the call (no further FSM transitions).
TERMINAL_STATES = frozenset({
    CallState.WRONG_NUMBER_CLOSE,
    CallState.ESCALATE_TO_HUMAN,
    CallState.DISPUTE_BRANCH,
    CallState.CALLBACK_SCHEDULED,
    CallState.CLOSING,
    CallState.ENDED,
})

# States carrying a legally-mandatory disclosure (docs/security.md) -- these
# are never barge-in-able. This is a deliberate "prevent, don't recover"
# choice: allowing interruption and then trying to resume/replay a partially
# delivered disclosure is real added complexity for an uncertain compliance
# benefit, since what regulators want is confirmation the disclosure was
# delivered in full, not "we tried, got cut off, and did our best after."
# Making these states categorically uninterruptible resolves the ambiguity
# by construction -- if it can never be interrupted, it's always fully
# delivered, full stop. Same "structurally guaranteed, not just likely"
# philosophy as the rest of this FSM.
MANDATORY_DISCLOSURE_STATES = frozenset({
    CallState.OPENING_DISCLOSURE,
    CallState.DEBT_DISCLOSURE,
})


class CallFSM:
    def __init__(self, start: CallState = CallState.OPENING_DISCLOSURE):
        self.state = start

    def next_state(self, intent: Intent) -> Optional[CallState]:
        """Return the next state for `intent` from the current state, or None
        if this state/intent combination has no defined transition (the
        dialogue manager then applies a state-specific default, e.g. re-prompt)."""
        if self.state in TERMINAL_STATES:
            return None
        return TRANSITIONS.get(self.state, {}).get(intent)

    def transition(self, intent: Intent) -> CallState:
        target = self.next_state(intent)
        if target is not None:
            self.state = target
        return self.state

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
