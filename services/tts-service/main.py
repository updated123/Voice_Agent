# =============================================================================
# tts-service (text-to-speech)
# =============================================================================
#
# RESPONSIBILITY
#   Streams synthesized bot speech back to the media server. Runs on the
#   GPU pool. See docs/architecture.md and docs/latency-budget.md.
#
# WHY THIS EXISTS AS ITS OWN SERVICE
#   Time-to-first-audio-byte (not total synthesis time) is the metric
#   that matters here -- a non-streaming TTS is disqualified on latency
#   grounds alone (docs/latency-budget.md). Isolating TTS lets its
#   streaming/cancellation (barge-in) contract be owned independently of
#   everything upstream.
#
# STATE
#   Stateless per request: synthesizes one response utterance as a
#   stream of audio chunks. Barge-in is realized by the caller
#   (call-orchestrator) simply stopping consumption of the stream.
#
# API CONTRACT (planned)
#   POST /synthesize                 # non-streaming convenience/testing only
#     in:  { session_id, text, sample_rate }
#     out: { session_id, audio_b64, n_chunks, sample_rate }
#   POST /synthesize/stream          # real streaming endpoint
#     in:  { session_id, text, sample_rate, allow_barge_in }
#     out: newline-delimited JSON, one audio chunk per line, emitted as
#          generated -- caller may stop reading at any point (barge-in cutoff)
#   GET /healthz
#
# CACHING -- SEGMENT-LEVEL, NOT WHOLE-STRING
#   Response text is deterministic (same text + same model/voice always
#   produces the same audio), which is exactly what makes exact-match
#   caching viable here -- unlike stt-service, whose input (raw audio) is
#   never actually identical twice (see that service's spec).
#
#   A whole-string cache is a weak version of this: most compliance
#   response templates are ~90-95% fixed text with one or two variable
#   slots ("...Am I speaking with {borrower_name}?") -- keying the cache
#   on the full rendered string means that one differing slot value
#   misses the *entire* cache entry, every single call, even though
#   almost all of the audio is identical every time.
#
#   Flow:
#     1. Split the response template into fixed segments + variable slots
#        BEFORE rendering (i.e., operate on the template, not the final
#        string with slots already substituted in).
#     2. For each fixed segment: check cache, keyed on the exact segment
#        text + model/voice version.
#          HIT  -> reuse cached audio for that segment.
#          MISS -> synthesize (GPU), store in cache, then use it.
#     3. For each variable slot (borrower name, amount, date): always
#        synthesize fresh -- not cached, since it's different per call
#        by definition and caching it would never hit.
#     4. Concatenate fixed + variable audio chunks in order, stream the
#        combined result to the borrower.
#   Backend: Aerospike, same choice as every other cache in this system,
#   keyed by (segment_text, tts_model_version) so a model/voice upgrade
#   naturally invalidates old entries without a separate cache-busting step.
#
# DEV BACKEND (see libs/voice_agent_core/tts/)
#   MockStreamingTTS -- placeholder audio (not real speech), but genuine
#   streaming/cancellation semantics. Already implemented and
#   unit-tested there.
#
# PRODUCTION BACKEND
#   Streaming neural TTS (Kokoro-82M-class or Piper), served on GPU. Swap
#   is isolated to this service's model-call layer.
# =============================================================================
