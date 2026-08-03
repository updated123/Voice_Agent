# Monitoring & Quality Evaluation

"It sounds fine when I try it" is not a quality bar for a system making a billion calls a day. This document defines what's measured, how, where it's collected (`services/analytics`, [../monitoring/](../monitoring/)), and how it gates changes.

## Core metrics

| Metric | Definition | Why it matters | Target |
|---|---|---|---|
| **ASR WER** | Word error rate vs. human transcription, per audio-quality bucket (clean/noisy/accented) | Upstream of everything — an ASR error becomes an intent-misclassification becomes a wrong bot response | Tracked per bucket, not just overall average |
| **Intent classification accuracy** (`llm-gateway`) | Per-intent precision/recall vs. human-labeled ground truth | Determines whether `compliance`'s FSM takes the right branch | A false-negative on `escalate` is a compliance issue, not just a quality one |
| **Task success rate** | % of connected calls reaching a valid, intended outcome | The actual business-outcome metric everything else serves | Tracked per FSM branch/model version |
| **Containment rate** | % of connected calls resolved without human escalation | Directly drives the dominant cost line item — see [cost-analysis.md](cost-analysis.md) | Maximize, but never at the expense of escalation-trigger recall (below) |
| **No-response rate** | % of connected calls ending in `call-orchestrator`'s `NO_RESPONSE` outcome (borrower went silent mid-call and never replied — see [architecture.md](architecture.md)'s failure-domains table) | Kept as its own bucket specifically so it never gets counted as "resolved" (inflating task success/containment rate) or as "escalated" (diluting escalation-trigger recall) — a dead-air call is neither | Tracked separately; a sustained rise may indicate an AMD false-negative problem (voicemail/hold-music misclassified as a live connect) rather than a dialogue-quality issue |
| **Escalation-trigger recall** | Of calls that *should* have escalated (explicit human request, distress, ambiguous/high-risk content), % that actually did | The guardrail against over-optimizing containment rate | ~100%, hard gate |
| **Turn-taking latency (P50/P95)** and **barge-in latency (P50/P95)** | See [latency-budget.md](latency-budget.md) | Affects perceived naturalness and hang-up rate | P50 <700ms turn-taking, P95 <1200ms; barge-in stop <100ms |
| **Promise-to-pay conversion rate** | % of connected calls resulting in a payment promise | Business KPI | Benchmarked against human-agent baseline |
| **Promise-kept rate** (downstream, days later) | % of promises actually resulting in payment | Detects over-eliciting promises the bot can't secure | Compared against human-agent baseline |
| **Compliance-script delivery rate** | % of calls where mandatory disclosures were delivered verbatim/on-schedule | See [security.md](security.md) | ~100%, hard alerting if it drops at all |
| **Naturalness score** | Human-rated (small sampled subset) mean-opinion-score-style rating of how natural the bot sounded — voice quality, pacing, turn-taking feel, not just correctness | Every metric above measures whether the bot did the *correct* thing; this is the only one that measures whether the call *felt* like talking to something competent rather than a robotic script-reader. It's also the metric that actually validates the latency-optimization work in [latency-budget.md](latency-budget.md) — "faster turn-taking improves perceived naturalness" is the premise behind that whole document, and this is the metric that closes the loop and confirms it, rather than leaving it asserted | Tracked on a rolling sampled basis (not every call — expensive to rate), trended over model/prompt versions |
| **Customer satisfaction (CSAT)** | Post-call rating, where obtainable (a brief opt-in prompt, or inferred from callback/complaint rates where a direct rating isn't practical at this volume) | The actual end-user-facing outcome metric — task success rate and containment rate are proxies for "did this go well," CSAT is the more direct signal, and the two can diverge (a call can be contained and compliant while still leaving the borrower annoyed) | Benchmarked against human-agent baseline for the same account segment, same as promise-to-pay/promise-kept rates |

## Evaluation methodology

1. **Offline regression suite** — a curated, growing set of recorded/synthetic utterances covering every FSM state, plus adversarial cases (ambiguous responses, borrowers talking over the bot, human/lawyer requests phrased many ways, distress signals, noisy audio, hostile responses). Every change to `stt-service`, `llm-gateway`, `tts-service`, or `compliance`'s FSM must pass this suite before eligible for the next stage.
2. **Shadow/canary deployment** — new versions run on a small % of live traffic, compared against production on every metric above. At this scale even a 0.1% canary is ~1M calls/day — enough for statistically meaningful comparisons within hours.
3. **A/B testing framework** — for genuine tradeoffs (model size vs. latency vs. quality; negotiation phrasing vs. promise-kept rate), measuring real business-metric impact, not just proxy metrics.
4. **Human-in-the-loop QA sampling** — random and risk-weighted call samples reviewed by human QA, catching issues automated metrics don't yet have a defined check for.
5. **Escalated-call review loop** — every escalated call is, by definition, a case the bot didn't handle; reviewed to check if escalation was actually necessary and to identify new intents/FSM branches worth adding.

## Guardrails against optimizing the wrong thing

- **Escalation-trigger recall is tracked and gated independently from containment rate** — a model update can't "improve" containment by getting worse at recognizing when it should hand off (see [security.md](security.md)).
- **Promise-kept rate (measured days later) is tracked alongside promise-to-pay rate** — prevents an overly-agreeable dialogue manager from "improving" its headline conversion metric by extracting hollow promises.

## Where this lives operationally

- `services/analytics` — event logging + on-demand rollup metrics (`GET /metrics/summary`).
- [../monitoring/prometheus.yml](../monitoring/prometheus.yml) — scrape config for per-service latency/throughput/GPU-utilization metrics.
- [../monitoring/alerts.yaml](../monitoring/alerts.yaml) — hard-alert thresholds (compliance delivery rate, escalation recall, P95 latency, barge-in latency, carrier concentration, containment-rate regression).
- [../monitoring/dashboards/](../monitoring/dashboards/) — executive/cost, call-quality, latency, and capacity dashboard placeholders.
- [../monitoring/tracing.yaml](../monitoring/tracing.yaml) — distributed tracing (OpenTelemetry). Metrics (above) tell you *whether* something's slow in aggregate; tracing is what lets you answer *why one specific call* took 3 seconds instead of 700ms, by following that call's request across all 12 services and seeing exactly which hop added the latency — not something a dashboard of aggregate percentiles can do.
