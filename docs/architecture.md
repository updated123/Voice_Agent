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
| NLU / intent / sentiment / model-tier routing | `services/llm-gateway` | Classifies borrower utterances into the fixed intent set; also owns tone/emotion (sentiment) classification and the per-turn small-vs-large model-tier routing decision, folded in below. |
| Call-flow / compliance / tool calling | `services/compliance` | The FSM: mandatory disclosures, negotiation flow, escalation triggers — stateless, pure function of (state, intent). Also owns the named-function boundary to external systems (loan servicing backend, CRM), folded in below. |
| TTS | `services/tts-service` | Streaming text-to-speech, GPU pool. |
| Orchestration | `services/call-orchestrator` | Coordinates one call's pipeline turn-by-turn across every other service. |
| Call state | `services/session-manager` | Externalized state store (Aerospike in production, Redis Cluster documented as the alternative) — lets every other service stay stateless. |
| Outcome logging | `services/analytics` | Event logging + rollup quality metrics (see [monitoring.md](monitoring.md)). |
| Cost metering | `services/billing` | Per-call cost tracking against the fleet-level cost model (see [cost-analysis.md](cost-analysis.md)). |
| Policy/FAQ retrieval | `services/rag-service` | Answers off-script questions outside the fixed intent set by retrieving from a vetted knowledge base — grounds `compliance`'s response, never bypasses it. |

`services/compliance` and `services/llm-gateway` each own more than one responsibility below their top-level entry — see "Consolidated into an existing service, not left as a separate one" underneath this table.

## Components added to close an identified gap

`rag-service` was not in the original design — it was identified by auditing this architecture against a standard enterprise-conversational-AI component checklist and finding a real gap, not just a naming mismatch: off-script questions previously had no path except re-prompt-until-give-up or unnecessary escalation. It's a comment-only specification (`services/rag-service/main.py`), consistent with every other service in this repo — not implemented.

A candidate, **voice-biometric fraud detection**, was considered and deliberately cut rather than added — it imports an inbound-call threat model (verify an unknown caller before granting account access) that doesn't map onto this outbound-only system, where the callee's identity is already known and there's no high-value action for an impersonator to gain. See [future-improvements.md](future-improvements.md) for the full reasoning.

## Consolidated into an existing service, not left as a separate one

An earlier draft of this design added four more gap-closing services — `tool-gateway`, `sentiment-detector`, `model-router`, `inference-router` — bringing the total to 16. Auditing that draft against this doc's own criteria for splitting a service out (a genuinely different scaling curve, a compliance/security boundary, or a distinct external vendor integration — see "Key architectural decisions" #2 and the failure-domains table below) found that none of the four cleared it: each shared its scaling curve, deploy lifecycle, and failure domain with a direct neighbor, so the extra network hop bought no real isolation, only latency and one more thing to operate. Each was folded into that neighbor instead, as an explicitly-labeled internal module (not silently merged — see the "FOLDED IN" section in the target file for the full original reasoning):

- **Tool calling** (was `tool-gateway`) → folded into `services/compliance`. Only `compliance` ever called it; the WHAT/HOW distinction it existed to preserve (compliance decides what to do, tool calling decides how that reaches an external system) is kept as an internal module boundary — a reviewed tool registry and allow-list — rather than a service boundary.
- **Sentiment detection** (was `sentiment-detector`) → folded into `services/llm-gateway`. Both consume the same utterance on the same GPU pool on the same request path and produce sibling outputs (`intent`, `sentiment`) that `compliance` reads together — splitting them never had a real independent-scaling justification.
- **Model-tier routing** (was `model-router`) → folded into `services/llm-gateway`. Deciding which model tier classifies a turn is an implementation detail of the classification call itself, not a decision any other service needs to observe or act on independently.
- **GPU batching/routing** (was `inference-router`) → not folded into a service at all, because it was never really an application-level microservice — it's the batching/load-balancing/canary-routing layer that serving stacks like NVIDIA Triton or vLLM/TensorRT-LLM already provide. It's documented as shared infrastructure in the "Technology choices" table above, not as a `services/` entry.

This leaves 12 services (see the table above plus `services/compliance` and `services/llm-gateway`'s expanded scope), each with a scaling/security/vendor-integration justification that holds up under its own stated criteria — rather than 16 with four self-acknowledged soft justifications. See [future-improvements.md](future-improvements.md) for why this wasn't done in the first pass.

## Key architectural decisions

1. **VAD/denoise at the edge (CPU), ASR/LLM/TTS centralized (GPU).** Keeps expensive compute reserved for actual speech — silence, hold music, and background noise never reach the GPU pools. See "Audio pipeline detail" below.
2. **FSM-first `compliance` service, `llm-gateway` as a component feeding it — not the other way around.** Guarantees compliance-critical disclosures happen every time, bounds response latency (short, templated generations vs. open-ended chat), and bounds cost (fewer, shorter LLM calls). Full justification in the "Technology choices" section below.
3. **Regional, multi-carrier telephony from day one.** The actual scaling bottleneck at 1B calls/day — bolting it on later doesn't work because number reputation and carrier relationships take months to build.
4. **Streaming everywhere.** Every hop (ASR, LLM, TTS) is streaming, not request/response batch, because turn-taking latency is a quality-critical metric in an adversarial conversational context (see [latency-budget.md](latency-budget.md)).
5. **Stateless, horizontally-scalable services; call state lives in `session-manager` (Aerospike in production, keyed by call-id).** Any service instance can crash and be replaced without losing the call, and autoscaling is a simple function of adding more identical replicas. Aerospike was picked over Redis Cluster after comparing both against this system's actual peak load — see `services/session-manager/main.py` for the p99-latency reasoning.
6. **Cache anything that varies by a small, bounded dimension — never anything that varies per account.** `configs/model-versions.yaml`, `configs/feature-flags.yaml`, and `configs/calling-hours.yaml` change on a deployment cadence (minutes to hours), not per-call — every service reading them should load once and refresh on a slow interval, not fetch fresh over the network on every single request. The same principle is why `rag-service`'s knowledge base is cached by `(query, loan_type, region)` rather than by account, and why `scheduler`'s consent/DNC status and carrier number-pool reputation are cached with a TTL instead of queried fresh per dial (see each service's own spec for the specifics) — the common thread is: identify what's actually shared across millions of calls vs. what's genuinely unique to one, and only pay the network/compute cost for the latter.

   **Config caching specifically needs two details right, or it barely helps.** `call-orchestrator` alone runs ~2.2M replicas at peak — a naive cache that has *every pod* independently poll the config store every 30 seconds still generates ~75,000 requests/sec on that store, only a ~2.5x reduction from the ~185,000/sec uncached baseline, because the sheer replica count dominates. The real fix is **both**: (a) a refresh interval matched to how often config actually changes (minutes, not seconds — there's no reason to poll every 30s for something that changes a few times a day), and (b) a **node-local shared cache** (one cache per physical node, read by every pod scheduled on it) instead of one cache per pod. Combined, those two bring it down to roughly 100-1,000x fewer requests on the config store, not 2.5x — the difference between "cached" and "cached correctly" is most of the win here.

   **Number-pool reputation caching doesn't have this trap**, because the cache key is the phone number, not the replica — a simple TTL cache (no node-local complexity needed) already gets a real 4-44x reduction in reputation-check load depending on pool size, and — more importantly than the raw number — it decouples that load from call volume entirely, which matters because call volume is the one thing guaranteed to keep growing at this scale.
7. **Warm GPU pools, not cold starts.** The model weights behind `stt-service`/`llm-gateway`/`tts-service` are the same for every call — loading them is the one-time, reusable cost. Keeping the GPU pools warm (minimum replica counts that never scale to zero, per `infrastructure/kubernetes/hpa.yaml`) means every call reuses an already-loaded model instead of paying a cold-start cost, which would otherwise show up directly in the per-turn latency budget (`docs/latency-budget.md`).
8. **gRPC bidirectional streaming for the internal continuous-audio hops (`vad-service` → `denoiser` → `stt-service`), not REST-per-frame.** This audio path carries a live stream of 10-30ms PCM frames for the duration of every call, not discrete request/response calls — the wrong transport model for that shape of traffic is a real, quantifiable latency cost, not a style preference. A REST call per frame pays a new HTTP/1.1 connection (or at best HTTP/1.1 keep-alive) setup + full header + JSON-(de)serialization cost on every single frame, tens of times a second, per concurrent call; independent benchmarks put that per-call overhead high enough to matter against a ~150-250ms VAD budget (see `docs/latency-budget.md`), while gRPC's single long-lived HTTP/2 stream per call carries every frame as a small protobuf message over an already-open, multiplexed connection — commonly cited at under 50ms overhead for this kind of call pattern. SIP/RTP remains correct for the actual PSTN leg (that's carrier-standard, not something this system controls); gRPC applies specifically to the internal hops between `vad-service`, `denoiser`, and `stt-service`, all three of which are inherently continuous-stream rather than one-shot.

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
| Orchestration / state | Stateless services + Aerospike, Kubernetes autoscaling | Both Aerospike and Redis Cluster clear the required ~370K ops/sec; Aerospike's 17-48% lower p99 latency wins given the tight per-turn latency budget | Redis Cluster — comparable throughput and a more mature ecosystem, documented as the fallback if that's weighted higher; sticky, stateful workers — simpler than either, but a crash loses the call |
| Dialer | Custom predictive dialer with AMD + live consent/DND gating | Wasting bot capacity on voicemail/no-answer is one of the largest hidden costs at scale | Simple round-robin dialing — wastes 60-80% of pipeline capacity on non-connects |
| Internal transport (`vad-service`↔`denoiser`↔`stt-service`) | gRPC, bidirectional streaming | Continuous per-call audio stream over one long-lived HTTP/2 connection; protobuf framing, no per-frame connection/header cost | REST/HTTP per audio frame — correct for one-shot calls (`billing`, `analytics`), wrong for a stream of frames tens of times/sec per call; adds latency the ~150-250ms VAD budget can't absorb at scale |
| GPU-request batching/routing (in front of `stt-service`/`llm-gateway`/`tts-service`) | NVIDIA Triton, or the batching/serving layer built into vLLM/TensorRT-LLM directly | Solving batching, replica load-balancing, and canary-version traffic-splitting once, as shared serving infrastructure, benefits all three GPU-tier services simultaneously — and it's the single biggest AI-compute cost lever (docs/cost-analysis.md) | A bespoke `inference-router` **service** — an earlier draft of this design named this as its own microservice; it isn't one. It has no independent scaling curve, no compliance/security boundary, and no distinct vendor integration of its own (this doc's own criteria for splitting out a service, see "Component responsibilities" below) — it's the serving layer every mainstream inference stack already provides, not a thing to build and operate as an extra deploy unit |

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
- **Pure acoustic hangover-window VAD has a real, unfixable-by-tuning failure mode: a mid-sentence thinking-pause is acoustically identical to a genuine end-of-turn.** "I'll pay... uh... by Friday" — if the pause around "uh" happens to exceed the hangover window (real disfluency pauses run 300ms-1s, not always under 250ms), pure silence-duration VAD fires `end_of_speech` early, splitting one utterance into two fragments that `llm-gateway`/`compliance` then process independently, with no mechanism to recognize the second as a continuation of the first. This isn't solvable by retuning the window — shortening it to catch true disfluencies faster makes ordinary pauses trigger false cutoffs instead; the two failure modes trade off against each other on the *same* knob.
  **The fix used across the industry (Deepgram Flux, AssemblyAI Universal-Streaming/Universal-3 Pro, LiveKit's transcript-based end-of-utterance model) is semantic endpointing**: judge turn completeness from the utterance's *content* (partial-transcript grammatical structure, filler words, trailing conjunctions, intonation — falling pitch signals done, rising/flat signals continuing), not silence duration alone. Applied here: when `vad-service`'s acoustic hangover timer is about to fire, a lightweight completeness check reads `stt-service`'s already-streaming partial transcript for the current utterance (the same partial stream stage [2] of [latency-budget.md](latency-budget.md) already produces for early classification) and either confirms the cutoff or extends the hangover window briefly if the partial looks incomplete. The acoustic gate stays the default, always-on, cheap path — the semantic check only adds cost in the disfluency edge case, not on every turn. See `services/vad-service/main.py` for the mechanism.
- **Denoising** runs before ASR (and can help VAD itself distinguish speech from noise in the noisiest cases) — one of the highest-leverage, lowest-cost quality improvements available, since ASR errors compound into intent-misclassification and wrong bot responses.
- **AEC** prevents the bot from "hearing itself" (its own TTS output looping back through the borrower's mic), which is what makes reliable barge-in detection possible.
- **Barge-in mechanics:** VAD runs continuously even during bot playback → speech onset during playback = barge-in → `call-orchestrator` stops reading the `tts-service` stream within ~100ms → new borrower audio routed through the normal pipeline as the next turn. See [latency-budget.md](latency-budget.md).
- **Cost impact of doing this poorly:** an extra 20% of dead-air/noise leaking through to `stt-service` is roughly a 20% inflation of the ASR GPU fleet for zero benefit — thousands of extra GPUs at this scale, for nothing.

## Failure domains & resilience

| Failure | Mitigation |
|---|---|
| Single carrier outage | Multi-carrier routing fails over automatically; no single carrier > ~30% of a region's traffic. |
| GPU pool overload | Backpressure at `scheduler`: throttles new dial attempts if pipeline queue depth exceeds threshold, rather than degrading in-call latency for connected calls. |
| Regional datacenter outage | Multi-region active-active deployment; **new** calls route to the nearest healthy region immediately. **In-flight calls in the failed region are dropped, not transparently migrated** — `session-manager`'s Aerospike replication (`infrastructure/aerospike/aerospike.conf`) is replication-factor ≥2 *within* a region, not cross-region (no XDR or equivalent configured), so a call's session state doesn't exist anywhere outside the region that was serving it. This is consistent with that same file's own stated design principle — "a lost call is acceptable, a slow one is not" — but it means "active-active" here means new-call continuity, not mid-call continuity, and that distinction wasn't stated plainly until now. Making cross-region session replication a prerequisite for true mid-call continuity is a real next step if that's ever required — see [future-improvements.md](future-improvements.md). |
| `compliance` low-confidence/uncertain state | Hard-coded escalation to human — a wrong guess in a compliance-sensitive conversation is worse than a handoff. |
| Media server crash mid-call | Call drops (acceptable), but state already lives in `session-manager`, so campaign logic doesn't re-attempt a call that actually succeeded. |
| Borrower goes silent mid-call (phone set down, walked away, dropped audio without dropping the call) | **`call-orchestrator`'s no-response timeout**, not just an indefinite wait. A tiered timer (re-prompt at ~5-8s of silence, graceful end at ~10-15s more) resumes normal turn handling the instant `vad-service` reports speech again, or ends the call gracefully otherwise. Without this, a silent call ties up a coordinator replica and a media-server channel indefinitely — real cost at 1B-calls/day scale, not just a UX gap. Logged as a distinct `NO_RESPONSE` outcome (see [monitoring.md](monitoring.md)) so it doesn't contaminate containment/escalation rate. See `services/call-orchestrator/main.py` for the full state machine. |
| A GPU-tier dependency (`stt-service`/`llm-gateway`/`tts-service`) degrades or goes down | **Circuit breaker, not just retry.** Per-request retry-once-then-fallback (already the pattern throughout `architecture/single-call-flow.html`'s technical flow) handles a single slow request, but doesn't stop *every concurrent call* from independently retrying against a dependency that's clearly failing. A circuit breaker tracks consecutive failures per dependency; past a threshold, it "opens" — new requests fail fast (straight to the same fallback each retry would have reached anyway: re-prompt, or escalate) for a cooldown window, instead of every one of millions of concurrent calls piling retries onto an already-struggling pool. This is what turns "one GPU pool is degraded" into a contained, bounded-impact event instead of a pile-up that makes the outage worse. |
