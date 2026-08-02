# =============================================================================
# sentiment-detector (emotion/tone detection -- adapts strategy, not just intent)
# =============================================================================
#
# RESPONSIBILITY
#   Detects the borrower's emotional state from voice tone (not just word
#   choice) -- calm, frustrated, distressed, angry -- and feeds it to
#   compliance as an additional signal alongside llm-gateway's intent
#   classification, so the FSM can pick a more empathetic response
#   strategy without that logic being smuggled into intent classification.
#
# WHY THIS EXISTS -- THE GAP IT CLOSES
#   The system already detects distress, but only via keyword matching in
#   llm-gateway's intent classifier (an `abusive_or_distress` intent
#   triggered by specific phrases -- libs/voice_agent_core/dialogue/intents.py).
#   That catches explicit statements ("I'm going to kill myself") but not
#   *tone* -- a borrower who is clearly agitated but doesn't say a
#   trigger phrase gets the same standard-negotiation script as a calm
#   one. This service closes that gap by analyzing the audio itself, not
#   just the transcript.
#
# LOGIC / FLOW
#   1. Runs on the same denoised audio segment stt-service transcribes
#      (parallel consumer of the same audio, not a blocking dependency)
#   2. Classifies tone into a small fixed set (calm / frustrated /
#      distressed / angry) with a confidence score
#   3. Result is attached to the turn alongside the intent from
#      llm-gateway -- compliance's FSM can key on (state, intent,
#      sentiment) rather than (state, intent) alone for the handful of
#      transitions where tone should change the response, e.g.:
#        - calm + negotiation      -> standard direct payment-plan script
#        - frustrated + negotiation -> acknowledge concern before continuing
#        - angry + any state        -> lower escalation threshold (escalates
#                                       sooner / on weaker signal, doesn't
#                                       require a hardcoded distress phrase)
#
# WHY THIS IS SEPARATE FROM llm-gateway'S INTENT CLASSIFICATION
#   Intent answers "what does the borrower want"; sentiment answers "how
#   are they feeling while they want it." Conflating the two into one
#   classifier would make both harder to improve independently, and
#   would make it harder to audit which one caused a given FSM branch to
#   fire (docs/security.md's audit-trail requirement wants a clean
#   explanation of why the bot did what it did).
#
# STATE
#   Stateless per utterance -- classifies one audio segment at a time.
#
# API CONTRACT (planned)
#   POST /classify-sentiment
#     in:  { session_id, audio_b64, sample_rate }
#     out: { session_id, sentiment, confidence }
#   GET /healthz
#
# PRODUCTION BACKEND
#   A small audio-tone classifier (prosody/pitch/energy features or a
#   lightweight speech-emotion-recognition model), GPU or CPU depending
#   on model size -- not specified/benchmarked in this repo.
# =============================================================================
