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
# DEV BACKEND (see libs/voice_agent_core/tts/)
#   MockStreamingTTS -- placeholder audio (not real speech), but genuine
#   streaming/cancellation semantics. Already implemented and
#   unit-tested there.
#
# PRODUCTION BACKEND
#   Streaming neural TTS (Kokoro-82M-class or Piper), served on GPU. Swap
#   is isolated to this service's model-call layer.
# =============================================================================
