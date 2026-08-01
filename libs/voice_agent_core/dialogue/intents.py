"""Intent classification.

docs/architecture.md specifies a small fine-tuned LLM (1-3B params) for this
job in production -- narrow domain, small intent set, low latency/cost when
self-hosted with continuous batching. `KeywordIntentClassifier` here is a
deliberately simple, dependency-free stand-in that implements the same
interface (`classify(text) -> Intent`), so the dialogue manager and FSM are
already written against the real interface boundary; swapping in an actual
model means implementing this one method against a served LLM, not rewiring
the rest of the pipeline.
"""

import re
from enum import Enum


class Intent(str, Enum):
    PROMISE_TO_PAY = "promise_to_pay"
    DISPUTE = "dispute"
    HARDSHIP = "hardship"
    WRONG_NUMBER = "wrong_number"
    CALLBACK_REQUEST = "callback_request"
    ESCALATE_HUMAN = "escalate_human"
    ABUSIVE_OR_DISTRESS = "abusive_or_distress"
    REFUSE = "refuse"
    AFFIRM = "affirm"
    UNKNOWN = "unknown"


# Ordered by priority: compliance/safety-critical intents (escalation,
# distress) are checked before conversational ones, so an ambiguous utterance
# that contains both a payment reference AND an explicit "let me talk to a
# person" still escalates -- see docs/security.md.
_PATTERNS: list[tuple[Intent, "re.Pattern[str]"]] = [
    (Intent.ABUSIVE_OR_DISTRESS, re.compile(
        r"\b(kill myself|suicide|hurt myself|end it all)\b", re.I)),
    (Intent.ESCALATE_HUMAN, re.compile(
        r"\b(human|real person|representative|manager|lawyer|attorney|sue|legal action)\b", re.I)),
    (Intent.DISPUTE, re.compile(
        r"\b(not mine|already paid|dispute|never took|wrong amount|identity theft|fraud)\b", re.I)),
    (Intent.WRONG_NUMBER, re.compile(
        r"\b(wrong number|don'?t know (this|that) person|no one by that name)\b", re.I)),
    (Intent.HARDSHIP, re.compile(
        r"\b(lost my job|laid off|hospital|medical|can'?t afford|no money|hardship|"
        r"passed away|bereavement)\b", re.I)),
    (Intent.CALLBACK_REQUEST, re.compile(
        r"\b(call (me )?back|not (a )?good time|busy right now|call later)\b", re.I)),
    (Intent.PROMISE_TO_PAY, re.compile(
        r"\b(i'?ll pay|i can pay|pay (it |that )?(by|on|next)|make a payment|schedule a payment)\b", re.I)),
    (Intent.AFFIRM, re.compile(r"^\s*(yes|yeah|yep|sure|okay|ok)\b", re.I)),
    (Intent.REFUSE, re.compile(r"^\s*(no|nope|not interested|stop calling)\b", re.I)),
]


class KeywordIntentClassifier:
    def classify(self, text: str) -> Intent:
        if not text or not text.strip():
            return Intent.UNKNOWN
        for intent, pattern in _PATTERNS:
            if pattern.search(text):
                return intent
        return Intent.UNKNOWN
