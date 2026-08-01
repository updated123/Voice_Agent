# Deployment

This describes how the `services/` fleet and `infrastructure/` would be provisioned and rolled out. Nothing in this repo actually runs any of this — see the placeholder comments in [../infrastructure/](../infrastructure/) and each `services/*/main.py` — but the plan below is what those placeholders are structured around.

## Environments

- **staging** — small fixed-size fleet (a few replicas per service), synthetic/replayed call traffic only, used for the offline regression suite and load-testing throughput assumptions (see [scaling.md](scaling.md)'s "planning assumptions, not benchmarked figures" caveat).
- **canary** — a thin slice of production traffic (as little as 0.1%, which at 1B calls/day is still ~1M calls — enough for statistically meaningful comparison within hours, see [monitoring.md](monitoring.md)).
- **production** — the full multi-region, multi-carrier fleet sized per [scaling.md](scaling.md).

## Provisioning order

1. **`infrastructure/terraform`** — networking (VPCs, regional peering near carrier PoPs), IAM roles per service, GPU/CPU node pools (`gpu-pool.tf`), remote state backend.
2. **`infrastructure/kubernetes`** — namespace + resource quotas, then Deployments/Services for every `services/*` component, then `hpa.yaml` autoscaling policies wired to the concurrent-active-call metrics `services/analytics` publishes (not raw CPU%, per [architecture.md](architecture.md)'s backpressure principle).
3. **`infrastructure/redis`** — Redis Cluster for `services/session-manager`, provisioned before any stateful service comes up.
4. **`infrastructure/kafka`** — event backbone for `services/analytics` and `services/billing`, provisioned before `services/call-orchestrator` starts producing events.
5. **`infrastructure/nginx`** — edge routing/TLS termination, brought up last, once every backend service is health-check-passing.

## Rollout strategy for model/logic changes

Different components have different blast radii, so they roll out differently:

| Component | Rollout method | Why |
|---|---|---|
| `services/compliance` (FSM/scripts) | Staged, legal-reviewed, feature-flagged (`configs/feature-flags.yaml`) | Compliance-critical — a bad script change is a regulatory incident, not just a quality regression. |
| `services/llm-gateway` (model version) | Shadow mode first, then canary (`configs/model-versions.yaml` pins the live version) | Model-quality regressions should be caught before they touch a single real call. |
| `services/stt-service` / `services/tts-service` | Canary, watched against WER / latency dashboards | Lower blast radius than compliance/NLU changes, but still gated on [monitoring.md](monitoring.md)'s regression suite. |
| `services/vad-service` / `services/denoiser` | Canary, watched against downstream WER (a VAD/denoise regression shows up as worse ASR accuracy, not directly) | |
| `services/scheduler` (calling-hours/consent logic) | Never canaried on compliance-critical logic — deployed fleet-wide together with legal sign-off | A partial rollout of a DND/calling-hours fix means part of the fleet is non-compliant during the rollout window. |

## Rollback

Every service version is tagged (`configs/model-versions.yaml` for models; standard image tags for service code); a regression caught by canary monitoring or a hard alert (see [../monitoring/alerts.yaml](../monitoring/alerts.yaml)) triggers an immediate revert to the last known-good tagged version, not a forward-fix under pressure — consistent with this being a compliance-sensitive, high-volume system where "fix forward" carries real regulatory risk.

## CI/CD (not implemented in this repo)

Would run, per service, on every change: unit tests (mirroring `tests/test_pipeline.py`'s coverage of the core `libs/voice_agent_core` logic each service wraps), the offline regression suite from [monitoring.md](monitoring.md), then a build/push to the image registry, then a staged rollout per the table above. No CI pipeline definitions exist in this repo — this section describes the intended shape only.
