# Architecture

## Problem statement (summary)

An outbound voice agent that autonomously calls borrowers behind on loan payments: verifies identity, discloses the overdue amount, negotiates a payment date/plan, handles objections (dispute, hardship, wrong number, callback request), logs the outcome, and escalates to a human whenever the conversation goes outside its competence.

**Scale target: 1,000,000,000 calls/day**, taken literally. In operational terms (full derivation in [scaling.md](scaling.md)): ~23,000-37,000 calls/sec during a realistic 12-hour legal calling window, and **~2.2M concurrent active calls at peak**.

**Honest sanity check:** this is larger than the total daily call volume of most national telecom networks. The hard constraint at this scale isn't the AI stack (ASR/LLM/TTS) — that scales roughly linearly with GPUs, a large but conventional infra problem. The hard constraint is **PSTN termination capacity**: no single carrier sells 2M+ concurrent outbound channels, so multi-carrier trunking is a first-class architectural concern, not an afterthought. This is a telecom-industry/regulatory scaling problem as much as a software one — flagged here rather than glossed over.

## High-level flow

```mermaid
flowchart LR
    subgraph Campaign["Campaign & Dialer Layer (services/scheduler)"]
        LS[Loan Servicing API] --> CB[Campaign Builder]
        CB --> DL[Predictive Dialer]
        DND[Consent / DND / Calling-Hours Gate] --> DL
    end

    DL -->|dial requests| CR[Carrier Routing Layer]
    CR -->|SIP trunks, multi-carrier| PSTN[(PSTN / Mobile Networks)]
    PSTN --> Callee((Borrower's Phone))

    CR --> MS[Media Server Fleet<br/>SIP/RTP termination]

    subgraph EdgePipeline["Per-call Edge Pipeline (CPU tier)"]
        MS --> VAD[vad-service]
        VAD --> DNS[denoiser]
        DNS --> AEC[Acoustic Echo Cancellation]
    end

    AEC -->|clean speech, streamed| ASRPool[stt-service<br/>GPU pool]
    ASRPool -->|transcripts| ORCH[call-orchestrator]
    ORCH --> LLM[llm-gateway<br/>intent classification]
    ORCH --> COMPLIANCE[compliance<br/>FSM + response text]
    COMPLIANCE -->|account lookups, outcome writes| BE[Loan Servicing Backend]
    ORCH --> SESSION[session-manager<br/>externalized call state]
    ORCH --> TTSPool[tts-service<br/>GPU pool]
    TTSPool -->|audio, streamed| MS
    MS --> PSTN

    COMPLIANCE -->|escalation trigger| HA[Human Agent Queue]
    ORCH --> ANALYTICS[analytics]
    ORCH --> BILLING[billing]
    ANALYTICS --> QA[QA / Model Eval Loop]
```

## Component responsibilities (mapped to services/)

| Component | Service folder | Responsibility |
|---|---|---|
| Campaign & dialer | `services/scheduler` | Live consent/DND/calling-hours gate before every dial; paces attempts against expected answer rate (AMD). |
| Carrier routing | *(infra, not a service)* | Multi-carrier SIP trunking, STIR/SHAKEN attestation, number-pool reputation management. |
| Media servers | *(infra: FreeSWITCH/Jambonz fleet)* | SIP/RTP termination; hosts the CPU-tier edge pipeline. |
| VAD | `services/vad-service` | Frame-level speech detection + end-of-speech hangover timing. |
| Denoiser | `services/denoiser` | Real-time speech enhancement ahead of ASR. |
| ASR | `services/stt-service` | Streaming speech-to-text, GPU pool. |
| NLU / intent | `services/llm-gateway` | Classifies borrower utterances into the fixed intent set. |
| Call-flow / compliance | `services/compliance` | The FSM: mandatory disclosures, negotiation flow, escalation triggers — stateless, pure function of (state, intent). |
| TTS | `services/tts-service` | Streaming text-to-speech, GPU pool. |
| Orchestration | `services/call-orchestrator` | Coordinates one call's pipeline turn-by-turn across every other service. |
| Call state | `services/session-manager` | Externalized state store (Redis in production) — lets every other service stay stateless. |
| Outcome logging | `services/analytics` | Event logging + rollup quality metrics (see [monitoring.md](monitoring.md)). |
| Cost metering | `services/billing` | Per-call cost tracking against the fleet-level cost model (see [cost-analysis.md](cost-analysis.md)). |

## Key architectural decisions

1. **VAD/denoise at the edge (CPU), ASR/LLM/TTS centralized (GPU).** Keeps expensive compute reserved for actual speech — silence, hold music, and background noise never reach the GPU pools. See "Audio pipeline detail" below.
2. **FSM-first `compliance` service, `llm-gateway` as a component feeding it — not the other way around.** Guarantees compliance-critical disclosures happen every time, bounds response latency (short, templated generations vs. open-ended chat), and bounds cost (fewer, shorter LLM calls). Full justification in the "Technology choices" section below.
3. **Regional, multi-carrier telephony from day one.** The actual scaling bottleneck at 1B calls/day — bolting it on later doesn't work because number reputation and carrier relationships take months to build.
4. **Streaming everywhere.** Every hop (ASR, LLM, TTS) is streaming, not request/response batch, because turn-taking latency is a quality-critical metric in an adversarial conversational context (see [latency-budget.md](latency-budget.md)).
5. **Stateless, horizontally-scalable services; call state lives in `session-manager` (Redis in production), keyed by call-id.** Any service instance can crash and be replaced without losing the call, and autoscaling is a simple function of adding more identical replicas.

## Technology choices

Every choice is evaluated on **cost at 1B calls/day**, **latency**, and **quality** — full tradeoff table:

| Layer | Chosen | Why | Rejected at this scale |
|---|---|---|---|
| VAD | Silero-VAD (GPU-free, ONNX) | ~1ms/frame on CPU, accurate, zero marginal GPU cost | WebRTC VAD — faster but more false triggers on noisy mobile audio |
| Denoiser | DeepFilterNet (or RNNoise for lowest-CPU tier) | Real-time on CPU, large WER improvement on noisy audio | Cloud denoising APIs — per-minute cost is a non-starter at 1B minutes/day |
| ASR | Self-hosted streaming Conformer / distil-Whisper (CTranslate2 or NVIDIA Riva) | Open-weight, streaming, GPU-batchable, near-Whisper-large accuracy at a fraction of the cost | Cloud ASR APIs — excellent quality, but 20-50x the self-hosted compute cost at this volume |
| NLU + dialogue generation | Small fine-tuned model (1-3B params), served via vLLM/TensorRT-LLM, wrapped by a deterministic FSM | Narrow domain — small model matches large-model quality here at 10-20x lower latency/cost; FSM guarantees required disclosures regardless of model output | Frontier LLM per turn — 50-100x the cost, 300-800ms+ TTFT under load (blows the latency budget), and cannot *guarantee* compliance behavior |
| TTS | Streaming neural TTS (Kokoro-82M-class / Piper) | Low first-byte latency, self-hostable | ElevenLabs/OpenAI TTS APIs — more expressive, but per-minute pricing at this volume is one of the largest cost items |
| Telephony / media server | FreeSWITCH or Jambonz, multi-carrier SIP trunking | Open-source, proven at high concurrency, full control over edge VAD/denoise | Fully-managed platforms (Twilio Voice) — right choice below ~1-5M calls/day, cost-prohibitive well before 1B/day |
| Orchestration / state | Stateless services + Redis, Kubernetes autoscaling | Standard horizontal-scaling pattern; a crashed worker doesn't lose the call | Sticky, stateful workers — simpler, but a crash loses the call and complicates autoscaling |
| Dialer | Custom predictive dialer with AMD + live consent/DND gating | Wasting bot capacity on voicemail/no-answer is one of the largest hidden costs at scale | Simple round-robin dialing — wastes 60-80% of pipeline capacity on non-connects |

### Why FSM-wrapped LLM, not a free-form agent (the most important decision)

A frontier LLM given a good system prompt behaves well *most of the time*. That isn't an acceptable compliance posture at 1B calls/day — even a 0.01% failure rate on a mandatory disclosure is 100,000 non-compliant calls/day. The `compliance` service's FSM converts compliance-critical behavior from "extremely likely, if prompted well" to "structurally guaranteed," while `llm-gateway`'s small model handles exactly the part that's genuinely hard to do with pure rules: understanding open-ended borrower speech and (in production) paraphrasing within an allowed response template.

## Audio pipeline detail (VAD, denoiser, echo cancellation, barge-in)

Every millisecond of audio reaching the GPU pools costs money. Real phone audio is full of silence, hold-adjacent noise, and background sound — none of which should reach an expensive model.

```mermaid
flowchart LR
    RTP[Raw RTP audio] --> AEC[Acoustic Echo Cancellation]
    AEC --> DNS[denoiser]
    DNS --> VAD[vad-service]
    VAD -->|speech frames only| ASR[stt-service]
    VAD -.->|silence: dropped| X((discarded))
```

- **VAD tuning that matters:** hangover/end-of-speech window (~150-250ms — too short interrupts mid-thought, too long feels sluggish), speech-onset threshold (fast enough to catch barge-in without false-triggering on breath/line noise), frame size (~20-30ms).
- **Denoising** runs before ASR (and can help VAD itself distinguish speech from noise in the noisiest cases) — one of the highest-leverage, lowest-cost quality improvements available, since ASR errors compound into intent-misclassification and wrong bot responses.
- **AEC** prevents the bot from "hearing itself" (its own TTS output looping back through the borrower's mic), which is what makes reliable barge-in detection possible.
- **Barge-in mechanics:** VAD runs continuously even during bot playback → speech onset during playback = barge-in → `call-orchestrator` stops reading the `tts-service` stream within ~100ms → new borrower audio routed through the normal pipeline as the next turn. See [latency-budget.md](latency-budget.md).
- **Cost impact of doing this poorly:** an extra 20% of dead-air/noise leaking through to `stt-service` is roughly a 20% inflation of the ASR GPU fleet for zero benefit — thousands of extra GPUs at this scale, for nothing.

## Failure domains & resilience

| Failure | Mitigation |
|---|---|
| Single carrier outage | Multi-carrier routing fails over automatically; no single carrier > ~30% of a region's traffic. |
| GPU pool overload | Backpressure at `scheduler`: throttles new dial attempts if pipeline queue depth exceeds threshold, rather than degrading in-call latency for connected calls. |
| Regional datacenter outage | Multi-region active-active deployment; calls route to the nearest healthy region. |
| `compliance` low-confidence/uncertain state | Hard-coded escalation to human — a wrong guess in a compliance-sensitive conversation is worse than a handoff. |
| Media server crash mid-call | Call drops (acceptable), but state already lives in `session-manager`, so campaign logic doesn't re-attempt a call that actually succeeded. |
