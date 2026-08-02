# Latency Budget

## Why latency is a quality metric here, not just an engineering nicety

Loan collection calls are an adversarial conversational context — the borrower frequently doesn't want to be on this call. Human conversational turn-taking gaps average roughly 200-300ms; anything the bot does much slower reads as "laggy" or "clearly a bot," which measurably increases hang-up rate and reduces containment. Latency is tracked as a primary quality metric alongside WER and task-success-rate (see [monitoring.md](monitoring.md)), not a secondary performance concern.

## Target: end-of-speech to start-of-bot-audio in ~500-700ms (P50) — best-case, not the current industry median

**This target is aspirational, and stating that plainly matters more than the number itself.** Real production cascaded voice-agent pipelines typically run 1.5-3 seconds end-to-end, not 500-700ms — and vendor-marketed latency figures are routinely optimistic versus independently measured production numbers. For example, Deepgram's own site markets Nova-3 at "under 300ms" end-to-end; a 2026 independent benchmark by Coval (testing 5 STT APIs over 2,400 runs) measured a median time-to-first-token of ~992ms for both Nova-3 and Nova-2 in its own test harness — a specific, sourced data point, not a universal claim about all deployments, since Coval's harness includes its own network/pipeline overhead on top of Deepgram's model-inference time. The 500-700ms figure below is what this pipeline is *designed to achieve* if every stage hits its per-hop target simultaneously — it is the number to build toward and measure against, not a number already validated in production, since this repo has no running production traffic to validate it with. Treat the caching work throughout `services/` (intent cache, compliance cache, TTS phrase cache) as exactly what closes the gap between the two — without it, the realistic 1.5-3s figure is the one to plan around.

```
Borrower stops talking
        │
        ▼
[1] vad-service: end-of-speech detection    ~150-250ms   (hangover window: must confirm they've
                                                           really stopped, not just paused)
        │
        ▼
[2] stt-service: final transcript ready      ~50-150ms    (streaming ASR already has partials;
                                                           finalizing the last chunk is fast)
        │
        ▼
[3] llm-gateway (classify) + compliance      ~30-80ms     (small model, short input, batched GPU
    (FSM transition + response text)                      inference; FSM lookup is near-instant)
        │
        ▼
[4] tts-service: time-to-first-audio-byte    ~100-200ms   (streaming TTS starts emitting audio
                                                           before the full sentence is synthesized)
        │
        ▼
[5] Network/jitter buffer to borrower        ~20-50ms     (RTP transport, regional PoP proximity)
        │
        ▼
Borrower hears bot start speaking
        │
   TOTAL P50: ~500-700ms      TOTAL P95 target: <1200ms
```

## Where each stage's latency comes from, and how it's controlled

**[1] vad-service (~150-250ms):** a genuine, unavoidable tradeoff — too short a hangover window and the bot interrupts mid-sentence pauses; too long and every turn feels sluggish. 150-250ms is the established sweet spot.

**[2] stt-service (~50-150ms):** streaming ASR with partial hypotheses lets `llm-gateway` often start classification on high-confidence partials *before* the formal "final" transcript event, effectively hiding this stage's latency behind stage [1]'s hangover window.

**[3] llm-gateway + compliance (~30-80ms):** exactly why [architecture.md](architecture.md) rejects a frontier-LLM-per-turn — a hosted frontier API under load routinely adds 300-800ms+ time-to-first-token, blowing the entire budget. A small (1-3B) model served locally with continuous batching, generating a short response, is what makes sub-100ms latency achievable here. `compliance`'s FSM lookup itself is near-instant (a dict lookup), so this stage's latency is almost entirely `llm-gateway`'s.

**[4] tts-service (~100-200ms):** requires a streaming architecture (audio chunks emitted as synthesized, playback starts on the first chunk) rather than synthesize-then-play. A non-streaming TTS, however good the audio quality, is disqualified on latency grounds alone.

**[5] Network (~20-50ms):** controlled by regional PoP placement (media servers and GPU pools co-located per-region, close to carrier peering points). Cross-region hops would alone consume the entire latency budget and are avoided by design.

## Barge-in (interruption) handling — a separate, tighter latency requirement

When the borrower interrupts the bot mid-utterance, `call-orchestrator` must:
1. Detect speech onset via `vad-service` within the same ~150-250ms window, even over the bot's own outgoing audio (requires AEC to distinguish borrower speech from the bot's own voice leaking back).
2. **Stop reading the `tts-service` stream within ~100ms** of detected barge-in.
3. Resume the normal turn-taking pipeline on the borrower's new utterance.

Barge-in latency (interrupt-to-silence) is tracked as its own P50/P95 metric distinct from turn-taking latency — see [monitoring.md](monitoring.md).

## What we deliberately do NOT optimize away

- The VAD hangover window is never shortened to shave latency — interrupting borrowers mid-thought is worse for containment than the latency cost of waiting.
- We do not use a larger/slower LLM or TTS model "because it's better" — in this domain, latency-driven naturalness outweighs marginal phrasing/voice-expressiveness gains, validated via the A/B methodology in [monitoring.md](monitoring.md), not assumed.
