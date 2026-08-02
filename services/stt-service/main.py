# =============================================================================
# stt-service (speech-to-text / ASR)
# =============================================================================
#
# RESPONSIBILITY
#   Transcribes one VAD-segmented borrower utterance. Runs on the GPU
#   pool. See docs/architecture.md and docs/scaling.md for the GPU-count
#   math (~22K GPUs at conservative 1B/day peak concurrency).
#
# WHY THIS EXISTS AS ITS OWN SERVICE
#   ASR is the single largest GPU-compute line item (docs/cost-analysis.md)
#   and scales independently of VAD/denoise (CPU) and TTS (GPU, but
#   different throughput profile) -- it needs its own autoscaling group.
#
# STATE
#   Stateless per request: transcribes one already-segmented utterance at
#   a time. A real streaming backend would instead expose partial-result
#   callbacks as audio arrives (see docs/latency-budget.md, stage [2]).
#
# API CONTRACT (planned)
#   POST /transcribe
#     in:  { session_id, audio_b64 (float32 PCM), sample_rate }
#     out: { session_id, text, is_final, confidence }
#   GET /healthz
#
# CACHING -- NOT APPLICABLE HERE, AND WHY
#   tts-service caches synthesized audio because its input (text) is
#   deterministic -- the same text always produces the same output, so an
#   exact-match cache actually hits. stt-service's input is raw audio,
#   which is never identical twice, even for the same speaker saying the
#   same word again (timing, pitch, background noise all vary). An
#   audio->text cache here would have an effective hit rate of zero --
#   this isn't a smaller version of the same optimization, it's a
#   different problem that the same mechanism can't solve.
#
# TIERED MODEL ROUTING -- THE ACTUAL EQUIVALENT OPTIMIZATION
#   Same underlying goal as tts-service's cache (avoid paying full cost
#   for cases that don't need it), different mechanism suited to audio
#   input:
#     1. For short utterances (below a duration threshold -- "yes," "no,"
#        "okay"), run a small/cheap ASR pass first.
#     2. If its confidence clears a threshold, use that result directly --
#        skip the full model entirely for this turn.
#     3. If confidence is low (or the utterance exceeds the duration
#        threshold), escalate to the full streaming Conformer/distil-Whisper
#        model.
#   This mirrors model-router's tiered-model principle (services/model-router),
#   applied one stage earlier in the pipeline -- cheap-first, expensive-only-
#   when-needed, rather than cache-hit-vs-miss.
#
#   VAD-gating (already in the pipeline, services/vad-service) is the other
#   half of "avoid wasted STT compute" -- it skips calling stt-service at
#   all on silence, which is the closest real analog to a cache miss being
#   avoided, just triggered by "nothing to transcribe" rather than "seen
#   this exact input before."
#
# DEV BACKEND (see libs/voice_agent_core/asr/)
#   MockASR -- no acoustic model; reads ground-truth text attached to a
#   SyntheticUtterance and optionally injects word-error-rate to simulate
#   a realistic, imperfect ASR channel. Already implemented and
#   unit-tested there.
#
# PRODUCTION BACKEND
#   Self-hosted streaming Conformer / distil-Whisper, served via
#   CTranslate2 or NVIDIA Riva, continuous-batched across concurrent
#   calls. Swap is isolated to this service's model-call layer.
# =============================================================================
