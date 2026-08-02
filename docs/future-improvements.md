# Future Improvements

Honest accounting of what this design simplifies or leaves out, and what real next steps would be.

## Known simplifications in this repo

- **Every `services/*/main.py` is a comment-only architecture placeholder**, not a running implementation. The one piece of real, tested code is [../libs/voice_agent_core/](../libs/voice_agent_core/) — an in-process reference pipeline (VAD → denoiser → ASR → FSM dialogue manager → TTS) exercised by [../tests/test_pipeline.py](../tests/test_pipeline.py) and [../run_demo.py](../run_demo.py). It proves the pipeline logic and FSM compliance behavior; it does not prove the microservice/infra scaffold runs, since that scaffold was intentionally left as architecture-only.
- **`libs/voice_agent_core`'s ASR "cheats"** by reading attached ground-truth text rather than running acoustic inference — there's no trained acoustic model in this repo. Word-error-rate injection is provided so the dialogue manager's behavior under realistic ASR imperfection can still be exercised.
- **TTS produces placeholder audio**, not real speech — what's tested is the streaming/cancellation contract, not voice quality.
- **English only** (see the project's original scope decision) — multilingual support (Hindi + regional Indian languages, given the likely deployment geography) is a real next step, not a detail: it changes ASR/TTS model choice, adds per-language WER tracking, and likely changes the FSM's response templates (tone/formality conventions differ by language and region).
- **No real telephony stack** — AMD (answering-machine detection), real dial pacing against live carrier capacity, and STIR/SHAKEN attestation are all described in [scaling.md](scaling.md)/[architecture.md](architecture.md) but not implemented; they require a live carrier relationship this repo doesn't have.
- **No real diagram renderer** — [../architecture/](../architecture/) holds Mermaid/drawio *sources*, not rendered PNGs; rendering requires a diagram tool (`mmdc`/draw.io) run outside this environment.

## Resolved: an earlier draft had 16 services, four with weak justification

A first pass at closing gaps against an enterprise-conversational-AI component checklist added `tool-gateway`, `sentiment-detector`, `model-router`, and `inference-router` as four more standalone services, bringing the total to 16. Self-auditing that draft against [architecture.md](architecture.md)'s own criteria for splitting out a service (a genuinely different scaling curve, a compliance/security boundary, or a distinct external vendor integration) found that none of the four actually cleared it — each shared its scaling curve and failure domain with a direct neighbor, so the extra service bought no real isolation, only an extra network hop and an extra thing to operate. Rather than ship 16 services with four self-acknowledged "soft" justifications, all four were folded into the neighbor they shared a scaling curve with (`tool-gateway` and the batching layer into `compliance`/infrastructure respectively; `sentiment-detector` and `model-router` into `llm-gateway`), each preserved as an explicitly-labeled internal module rather than silently deleted. See [architecture.md](architecture.md)'s "Consolidated into an existing service, not left as a separate one" section for the per-service reasoning. The result is 12 services, each defensible under the same criteria used to justify the other 12 from the start.

## Real next steps, roughly in priority order

1. **Load-test the per-GPU throughput assumptions** (`streams_per_gpu` in [../benchmarks/cost_calculator.py](../benchmarks/cost_calculator.py)) against real model benchmarks — every capacity/cost number in [scaling.md](scaling.md) and [cost-analysis.md](cost-analysis.md) is currently a planning assumption, not a measured figure.
2. **Validate the human-agent cost assumption** ($8/hr blended) against real staffing data for the actual planned geography — [cost-analysis.md](cost-analysis.md) flags this as the single most sensitive number in the whole model.
3. **Build the offline regression suite** described in [monitoring.md](monitoring.md) before any real model is put behind `llm-gateway`/`stt-service`/`tts-service` — this is the gate that catches regressions cheaply, and it doesn't exist yet.
4. **Pick and contract with multi-region carrier partners** — the actual long-lead-time item at this scale (see [scaling.md](scaling.md)'s "primary real-world constraint" callout); this takes months and should start before any other build-out.
5. **Legal/compliance review per target jurisdiction** — [security.md](security.md) is an engineering-requirements summary, not legal advice; a real deployment needs jurisdiction-specific sign-off before [services/compliance](../services/compliance/)'s FSM scripts are finalized.
6. **Multilingual expansion** — once English-only is validated end-to-end, extend ASR/TTS/NLU to the actual target languages, with per-language quality tracking from day one rather than bolted on later.
7. **Real AMD + dial-pacing implementation** in `services/scheduler`, once a carrier relationship exists to test against.

## Considered and cut: voice-biometric fraud detection

A `fraud-detection` service (voice-biometric identity verification against an enrolled voiceprint) was added
during a gap audit against a standard enterprise-conversational-AI checklist, then removed after closer
scrutiny. Worth recording why, since the reasoning generalizes beyond this one service.

**The mistake:** voice-biometric fraud detection is a real, necessary pattern for *inbound* calls — a bank's
customer-service line, where an unknown caller can claim any identity and the system must verify them before
granting account access (wire transfers, password resets). That threat model doesn't transfer to this system:

- This is an **outbound** dialer calling a **known number tied to a known account** — not an unknown inbound
  caller claiming an identity.
- "Wrong person answered" is already handled by the `wrong_number` intent/FSM branch.
- "Reasonable assurance before disclosing debt info" is already handled by the knowledge-based
  `identity_verification` challenge (confirm last 4 digits / DOB), which is proportionate to what's actually
  disclosed — an amount and a due date, not full account access.
- Critically, **there's no high-value action for an impersonator to gain by succeeding.** Negotiating a
  payment plan or promising to pay doesn't move money or grant access the way an inbound banking call's
  password reset or wire transfer does — so the attack has little incentive behind it.

**Where it might still be worth revisiting:** very large balances, demographics with elevated elder-fraud
risk, or jurisdictions with stricter identity-assurance requirements before any debt disclosure. If any of
those apply to a real deployment, voice-biometric verification (Azure Speaker Recognition, Pindrop, Nuance
Gatekeeper, Veridas, ID R&D — priced in `benchmarks/cost-latency-calculator.html`) is worth reconsidering
as an optional, risk-tiered addition — not a default requirement for every call.

## Deliberately out of scope for this exercise

- The loan servicing/accounting backend itself (treated as an external dependency the voice agent calls into).
- Carrier-level telecom economics and STIR/SHAKEN attestation politics beyond flagging them as the primary real-world bottleneck.
- A fully worked-out CI/CD pipeline (described at the level of intent in [deployment.md](deployment.md), not implemented).
