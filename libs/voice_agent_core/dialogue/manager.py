"""Dialogue manager: wires the intent classifier to the FSM and produces the
bot's response text for each turn.

The response templates below are the "fixed script" pieces described in
docs/security.md (mandatory disclosures, escalation hand-offs).
In production, a small fine-tuned LLM paraphrases *within* a state's allowed
response, and/or fills in account-specific slots (amount, due date, name) --
represented here by simple `.format()` slots rather than an actual model
call, since the point of this prototype is the pipeline/FSM wiring, not
language generation quality.
"""

from dataclasses import dataclass, field

from .fsm import CallFSM, CallState
from .intents import Intent, KeywordIntentClassifier

RESPONSE_TEMPLATES: dict[CallState, str] = {
    CallState.OPENING_DISCLOSURE: (
        "Hello, this is an automated assistant calling on behalf of {lender_name} "
        "regarding your account. This call is being recorded and this is an attempt "
        "to collect a debt. Am I speaking with {borrower_name}?"
    ),
    CallState.IDENTITY_VERIFICATION: (
        "For your security, can you confirm the last four digits of the phone number "
        "on file, or your date of birth?"
    ),
    CallState.DEBT_DISCLOSURE: (
        "Thank you. Our records show a balance of {amount_due} on your account, "
        "which was due on {due_date}. I'd like to help you resolve this today."
    ),
    CallState.NEGOTIATION: (
        "Would you be able to make a payment today, or would a specific date this "
        "week work better for you?"
    ),
    CallState.HARDSHIP_BRANCH: (
        "I'm sorry to hear that. We do have hardship assistance programs available. "
        "I can connect you with a specialist who can go through your options, or if "
        "you're able to commit to a smaller payment amount, I can set that up now."
    ),
    CallState.DISPUTE_BRANCH: (
        "I understand you believe this isn't correct. I'm connecting you with a "
        "specialist who can review the account details and your dispute."
    ),
    CallState.WRONG_NUMBER_CLOSE: (
        "My apologies for the inconvenience -- I'll remove this number from our "
        "records for this account. Have a good day."
    ),
    CallState.CALLBACK_SCHEDULED: (
        "No problem, I'll schedule a callback for a better time. Thank you for your time today."
    ),
    CallState.ESCALATE_TO_HUMAN: (
        "Of course -- let me connect you with someone who can help right away."
    ),
    CallState.CLOSING: (
        "Great, thank you -- I've scheduled that payment. You'll receive a confirmation "
        "by SMS. Have a good day."
    ),
}

# States where an UNKNOWN/unclassified intent should re-prompt rather than
# silently stall the call.
REPROMPT_TEXT = "Sorry, could you say that again?"


@dataclass
class DialogueTurn:
    response_text: str
    state: CallState
    intent: Intent
    should_escalate: bool
    call_ended: bool
    slots: dict = field(default_factory=dict)


class DialogueManager:
    def __init__(self, classifier: KeywordIntentClassifier = None, slots: dict = None):
        self.fsm = CallFSM()
        self.classifier = classifier or KeywordIntentClassifier()
        self.slots = slots or {
            "lender_name": "Northbridge Lending",
            "borrower_name": "the account holder",
            "amount_due": "$482.00",
            "due_date": "the 15th",
        }
        self._opened = False

    def opening_turn(self) -> DialogueTurn:
        """The very first bot utterance -- fires before any borrower speech,
        so it isn't intent-driven."""
        self._opened = True
        text = RESPONSE_TEMPLATES[CallState.OPENING_DISCLOSURE].format(**self.slots)
        return DialogueTurn(
            response_text=text,
            state=self.fsm.state,
            intent=Intent.UNKNOWN,
            should_escalate=False,
            call_ended=False,
        )

    def handle_turn(self, borrower_text: str) -> DialogueTurn:
        if not self._opened:
            raise RuntimeError("call opening_turn() before handle_turn()")

        intent = self.classifier.classify(borrower_text)
        next_state = self.fsm.next_state(intent)

        if next_state is None:
            # No defined transition for this (state, intent) pair -- re-prompt
            # rather than silently doing nothing or guessing.
            return DialogueTurn(
                response_text=REPROMPT_TEXT,
                state=self.fsm.state,
                intent=intent,
                should_escalate=False,
                call_ended=False,
            )

        self.fsm.state = next_state
        response_text = RESPONSE_TEMPLATES[next_state].format(**self.slots)

        should_escalate = next_state == CallState.ESCALATE_TO_HUMAN or next_state == CallState.DISPUTE_BRANCH
        call_ended = self.fsm.is_terminal()

        return DialogueTurn(
            response_text=response_text,
            state=next_state,
            intent=intent,
            should_escalate=should_escalate,
            call_ended=call_ended,
        )
