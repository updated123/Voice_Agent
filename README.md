# Voice Agent for Loan Collection Calls — System Design

**Goal:** design a voice agent system that can place **1,000,000,000 (1B) outbound loan-collection calls/day**, optimizing jointly for **cost, latency, and quality**, with a concrete system architecture, tech infra, and a working reference implementation of the core audio/dialogue pipeline (VAD, denoiser, ASR, dialogue manager, TTS).

This repo has two layers:
- **`docs/` + `architecture/` + `services/` + `infrastructure/` + `configs/` + `benchmarks/` + `monitoring/`** — the full microservices architecture: one folder per service, infra-as-code, diagrams, cost/capacity model. Every `services/*/main.py` and every file under `infrastructure/`/`configs/`/`monitoring/` is a **comment-only architecture placeholder** — it documents that component's responsibility and API contract, not a running implementation.
- **`libs/voice_agent_core/` + `tests/` + `run_demo.py`** — the one part of this repo that's real, working, tested code: an in-process reference implementation of the VAD → denoiser → ASR → dialogue-FSM → TTS pipeline, proving the pipeline logic and compliance behavior described in the docs actually holds together.

## Folder structure

```
VOICE/
├── README.md                          <- you are here
│
├── docs/
│   ├── architecture.md                End-to-end architecture, diagrams, tech-stack choices, audio pipeline, failure domains
│   ├── cost-analysis.md               Full cost breakdown, unit economics, cost levers
│   ├── scaling.md                     Erlang math, concurrency, GPU/media-server sizing
│   ├── latency-budget.md              Turn-taking latency budget (ms-level breakdown), barge-in
│   ├── monitoring.md                  Metrics, guardrails, A/B testing, human-in-the-loop QA
│   ├── deployment.md                  Environments, rollout strategy, rollback, CI/CD intent
│   ├── security.md                    Regulatory compliance + information security
│   └── future-improvements.md         Known simplifications and real next steps
│
├── architecture/
│   ├── high-level.drawio              Full system topology (open in app.diagrams.net)
│   ├── sequence-diagram.mmd           One call turn, traced across every service boundary
│   ├── deployment-diagram.mmd         Per-region infra topology
│   ├── call-flow.mmd                  The compliance FSM as a state diagram
│   └── README.md                      How to render these to PNG
│
├── services/                          16 microservices — each main.py is a comment-only spec
│   ├── call-orchestrator/             Coordinates one call's pipeline turn-by-turn
│   ├── session-manager/               Externalized call-state store (Aerospike in production)
│   ├── llm-gateway/                   NLU / intent classification (small fine-tuned LLM in production)
│   ├── tts-service/                   Streaming text-to-speech (GPU pool)
│   ├── stt-service/                   Streaming speech-to-text (GPU pool)
│   ├── vad-service/                   Voice activity + end-of-speech detection (CPU tier)
│   ├── denoiser/                      Real-time speech enhancement (CPU tier)
│   ├── analytics/                     Call-outcome logging + rollup quality metrics
│   ├── billing/                       Per-call cost metering
│   ├── scheduler/                     Predictive dialer + live consent/DND/calling-hours gate
│   ├── compliance/                    The FSM: mandatory disclosures, escalation triggers
│   ├── rag-service/                   Gap-closing: retrieval for off-script policy/FAQ questions
│   ├── tool-gateway/                  Gap-closing: named-function boundary to external systems
│   ├── sentiment-detector/            Gap-closing: tone/emotion detection alongside intent
│   ├── model-router/                  Gap-closing: routes turns to a small vs. large LLM tier
│   └── inference-router/              Gap-closing: shared GPU batching/load-balancing layer
│
├── infrastructure/                    Comment-only IaC placeholders
│   ├── terraform/                     Networking, IAM, GPU/CPU node pools
│   ├── kubernetes/                    Namespaces, Deployments, HPA autoscaling policies
│   ├── aerospike/                     session-manager's production backend (chosen over Redis for p99 latency)
│   ├── redis/                         session-manager's documented alternative backend
│   ├── kafka/                         Event backbone for analytics/billing
│   └── nginx/                         Edge routing / TLS termination
│
├── configs/                           Comment-only config placeholders
│   ├── calling-hours.yaml
│   ├── model-versions.yaml
│   ├── campaign-defaults.yaml
│   └── feature-flags.yaml
│
├── benchmarks/
│   ├── cost_calculator.py             REAL, working: parametrized cost/capacity calculator
│   ├── cost-latency-calculator.html   REAL, working: interactive cost/latency calculator — open
│   │                                   directly in a browser, no server or install needed. Swap
│   │                                   VAD/denoiser/STT/LLM/TTS/telephony/compute-tier choices and
│   │                                   traffic sliders (calls/day, answer rate, escalation rate) to
│   │                                   see cost/call, cost/day, and turn-taking latency recompute live.
│   └── real-pricing-reference.html    REAL, working: every cost/latency figure sourced from a live
│                                       vendor pricing page or benchmark, with a citation link per row —
│                                       covers STT/TTS/LLM/GPU/telephony/VAD/denoiser/AEC/diarization/
│                                       wake-word/voice-biometrics (11 categories, nothing assumed).
│
├── monitoring/                        Comment-only observability placeholders
│   ├── prometheus.yml
│   ├── alerts.yaml
│   └── dashboards/
│
├── libs/voice_agent_core/             REAL, working, tested reference pipeline
│   ├── vad/                           EnergyVAD + HangoverVAD (dev backend for vad-service)
│   ├── denoiser/                      SpectralGateDenoiser (dev backend for denoiser)
│   ├── asr/                           MockASR (dev backend for stt-service)
│   ├── dialogue/                      FSM + intent classifier (dev backend for compliance + llm-gateway)
│   ├── tts/                           MockStreamingTTS (dev backend for tts-service)
│   └── orchestrator/                  asyncio pipeline (dev backend for call-orchestrator)
│
├── tests/test_pipeline.py             20 passing tests over libs/voice_agent_core
└── run_demo.py                        Run a simulated call end-to-end and print the transcript
```

## Read order

1. [docs/architecture.md](docs/architecture.md) — start here: problem framing, system diagram, service responsibilities, tech-stack choices, audio pipeline, failure domains.
2. [docs/scaling.md](docs/scaling.md) — how many servers/GPUs/carrier trunks 1B calls/day actually requires.
3. [docs/cost-analysis.md](docs/cost-analysis.md) — $/call, $/day, $/month, and the levers that move it (the biggest one isn't GPUs).
4. [docs/latency-budget.md](docs/latency-budget.md) — why the pipeline targets ~500-700ms turn latency, not 2s.
5. [docs/monitoring.md](docs/monitoring.md) — how quality is measured and gated.
6. [docs/security.md](docs/security.md) — regulatory compliance + information security, enforced structurally.
7. [docs/deployment.md](docs/deployment.md) — environments, rollout strategy, rollback.
8. [docs/future-improvements.md](docs/future-improvements.md) — honest accounting of what's simplified and what's next.
9. [architecture/](architecture/) — diagram sources.
10. [services/](services/) — one folder per microservice; each `main.py` documents that service's contract.
11. Run the real code: `pip3 install -r requirements.txt`, `python3 -m pytest tests/`, `python3 run_demo.py --scenario happy_path`.

## TL;DR numbers (see docs/scaling.md and docs/cost-analysis.md for derivation)

| Metric | Value |
|---|---|
| Peak concurrent calls | ~2.2M |
| AI compute GPUs (stt-service + llm-gateway + tts-service) | ~38,900 (conservative) / ~11,700 (answer-rate-adjusted) |
| Media/SIP servers | ~1,500 |
| Total infra cost/day | ~$21.4M (answer-rate-adjusted) / ~$67.2M (conservative) |
| Cost per call | ~$0.02–0.07 |
| **Dominant cost driver** | **Human escalation labor — ~10x compute+telephony combined** |
| P50 turn latency (bot response after user stops talking) | ~500-700ms |

**Honest caveat, stated up front:** 1B calls/day is larger than the entire outbound call volume of most national telecom networks. The PSTN/carrier termination capacity (not compute) is the real bottleneck — no single carrier can originate 2.2M concurrent calls, so this requires **multi-carrier, multi-region trunking** treated as a first-class scaling dimension, not an afterthought. Details in [docs/architecture.md](docs/architecture.md) and [docs/scaling.md](docs/scaling.md).

## Design principles driving every decision

- **Self-host the AI stack; don't pay per-token/per-minute API pricing at this scale.** At 1B calls/day, commercial ASR/LLM/TTS APIs would cost 10-50x more than self-hosted open-weight models on owned/reserved GPUs.
- **Small, fine-tuned models beat big general ones for this task.** A small (1-3B) fine-tuned LLM (`llm-gateway`) plus a deterministic FSM (`compliance`) gets most of the quality of frontier models at a fraction of the latency and compute cost — and the FSM guarantees required disclosures happen regardless of model output.
- **Latency is a quality feature, not a nice-to-have.** Sub-second turn-taking with correct barge-in handling is a hard requirement, not an optimization target — see [docs/latency-budget.md](docs/latency-budget.md).
- **VAD and denoising happen at the edge (CPU tier), before anything touches a GPU.** Keeps expensive compute reserved for actual speech, not silence/noise/hold-music.
- **Compliance is architecture, not a policy doc.** Calling-hour windows, consent/DNC checks, and mandatory human escalation paths are enforced structurally in `services/compliance` and `services/scheduler`, not left to training data or prompts.
- **Every service is stateless except `session-manager`.** Call state lives in one externalized store, keyed by call-id — any other service can crash and be replaced mid-call without losing the call.
- **The one finding that changed the plan:** human-escalation labor, not GPU compute, dominates total cost by roughly 10x (see [docs/cost-analysis.md](docs/cost-analysis.md)) — so containment rate is the biggest lever in the whole system, bigger than any infra optimization.
