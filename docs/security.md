# Security & Compliance

Debt collection is one of the most heavily regulated conversational domains, and this system also handles financial PII at a scale where a data-handling mistake is amplified a billion-fold. This document covers both the **regulatory/compliance** requirements and the **information-security** requirements, and where each is enforced.

> **This document is an engineering-requirements summary, not legal advice.** Any real deployment must have jurisdiction-specific legal/compliance review (e.g., FDCPA/Regulation F and state-level rules in the US; RBI Fair Practices Code, DoT/TRAI regulations and DND registry rules in India; equivalent regimes elsewhere) before launch.

## Regulatory compliance — enforced in `services/compliance`, not by prompting

| Requirement | Enforced where | How |
|---|---|---|
| **Calling-hour restrictions** | `services/scheduler` | Live gate checked against the borrower's local timezone immediately before every dial — not a once-a-day filter, since a call queued near the window boundary must not fire after it closes. |
| **Do-Not-Call / opt-out** | `services/scheduler` + `services/session-manager` | Opt-out takes effect **immediately** — if a borrower opts out mid-call, `compliance` writes the flag synchronously to the same store `scheduler` checks pre-dial. |
| **Mandatory disclosures** | `services/compliance` (fixed FSM states) | Fixed, legally-reviewed scripts — `llm-gateway` does not paraphrase or omit these; it only handles the surrounding natural conversation. |
| **No deceptive/threatening language** | `services/compliance` (constrains allowed response set) + [monitoring.md](monitoring.md) | LLM generation constrained to phrasing *within* a pre-approved template per state; adversarial testing specifically probes for boundary-pushing language before any model/prompt update ships. |
| **Right to request a human / dispute the debt** | `services/compliance` | Any explicit request is a hard-coded escalation trigger, routed to the human queue regardless of confidence. |
| **AI-interaction disclosure** | `services/compliance`, first FSM state | Delivered as a fixed opening disclosure before any substantive conversation. |
| **Vulnerable-borrower / hardship handling** | `services/compliance` | Explicit `hardship` intent routes to a distinct, more conservative FSM branch rather than continuing standard negotiation pressure. |
| **Escalation for abusive/distressed callers** | `services/compliance` | Detected distress/abuse from the borrower is a hard escalation trigger, never handled autonomously. |

### Why this can't be "mostly handled by good prompting"

A frontier LLM given a good system prompt behaves well *most of the time*. That's not an acceptable compliance posture at 1B calls/day — even a 0.01% failure rate on a mandatory disclosure is 100,000 non-compliant calls/day. The FSM converts compliance-critical behavior from "extremely likely" to "structurally guaranteed."

## Information security

| Concern | Approach |
|---|---|
| **Data minimization** | Identity verification uses partial/non-sensitive challenge questions, never full SSN/account-number readback. `services/analytics` and `services/session-manager` retain transcripts/recordings per a data-minimization policy, not indefinitely. |
| **Encryption in transit** | All inter-service calls (call-orchestrator ↔ vad-service/stt-service/llm-gateway/compliance/tts-service/session-manager) over TLS; all PSTN-facing media encrypted where the carrier path supports it (SRTP). |
| **Encryption at rest** | Session records (`session-manager`/Redis), call transcripts and recordings (`analytics`), and account data (loan servicing backend) encrypted at rest; access scoped by least-privilege IAM roles per service — see [../infrastructure/terraform/](../infrastructure/terraform/). |
| **Secrets management** | Service-to-service auth tokens, carrier trunk credentials, and loan-servicing API keys held in a secrets manager, not in `configs/` (which holds only non-sensitive operational parameters) or in service code. |
| **Access control** | Each `services/*` component gets a narrowly-scoped IAM role — e.g. `services/billing` can write usage records but has no access to borrower PII beyond a call-id; `services/compliance` can read/write FSM state but has no access to the loan-servicing backend directly (only via a defined API). |
| **Audit trail** | Every call logs exact disclosure scripts delivered (with timestamp), full transcript, detected intents, escalation trigger/reason, and consent/DND status at time of dial — sufficient to reconstruct and defend the compliance posture of any individual call if challenged. Aggregate compliance metrics (e.g., % of calls correctly delivering the opening disclosure) are hard-alerted, not soft KPIs — see [../monitoring/alerts.yaml](../monitoring/alerts.yaml). |
| **Network segmentation** | GPU-tier services (`stt-service`, `llm-gateway`, `tts-service`) and CPU-tier services (`vad-service`, `denoiser`, `scheduler`) sit in separate node pools/subnets; only `call-orchestrator` needs to reach both tiers. |
| **Dependency/model supply chain** | Self-hosted open-weight models (see [architecture.md](architecture.md)) are pinned by version (`configs/model-versions.yaml`) and scanned/reviewed before deployment, rather than depending on a third-party API's undisclosed model updates. |

## Audit trail (detail)

Every call logs: exact disclosure scripts delivered (with timestamp), full transcript, detected intents, any escalation trigger and reason, and consent/DND status at time of dial — sufficient to reconstruct and defend the compliance posture of any individual call if challenged, and to feed aggregate compliance monitoring.
