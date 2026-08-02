# =============================================================================
# inference-router (the layer between a GPU-tier service and its GPU cluster)
# =============================================================================
#
# RESPONSIBILITY
#   Sits in front of the GPU pool backing stt-service, llm-gateway, and
#   tts-service: batches concurrent requests for throughput, load-balances
#   across GPU replicas, and tracks which model version is live on which
#   replica during a rollout -- so each GPU-tier service's own code
#   doesn't need to know about batching or replica topology.
#
# WHY THIS EXISTS -- THE GAP IT CLOSES
#   docs/architecture.md and docs/scaling.md already specify continuous
#   batching (vLLM/TensorRT-LLM) as part of the production backend for
#   every GPU-tier service, and configs/model-versions.yaml already pins
#   which model version is live -- but nothing names the component that
#   actually performs the batching/routing/version-pinning as its own
#   layer. Today it reads as something that happens "inside" each
#   GPU-tier service; naming it separately is what lets it be shared
#   infrastructure instead of reimplemented three times (once each for
#   stt-service, llm-gateway, tts-service).
#
# LOGIC / FLOW
#   1. A GPU-tier service (e.g. llm-gateway) receives a request and hands
#      it to inference-router instead of calling a model directly
#   2. inference-router groups concurrent requests into a batch (subject
#      to a max-wait-time so batching doesn't itself add latency --
#      trades off against docs/latency-budget.md's per-stage targets)
#   3. Batch is dispatched to whichever GPU replica is least loaded
#   4. Which model version is live comes from configs/model-versions.yaml
#      -- during a canary rollout (docs/deployment.md), inference-router
#      is what actually splits traffic between the old and new version
#   5. Results are returned to the calling GPU-tier service, unbatched,
#      matched back to their original requests
#
# WHY THIS IS SEPARATE FROM EACH GPU-TIER SERVICE
#   Batching/load-balancing/version-routing is the same problem for
#   stt-service, llm-gateway, and tts-service -- solving it once here
#   instead of three times means a batching-efficiency improvement (the
#   single biggest AI-compute cost lever per docs/cost-analysis.md)
#   benefits all three simultaneously.
#
# STATE
#   Tracks in-flight batches and replica health/load -- ephemeral,
#   rebuildable state, not part of call state (session-manager owns that).
#
# API CONTRACT (planned)
#   Not borrower-facing -- an internal dispatch layer other GPU-tier
#   services call into, not something call-orchestrator calls directly.
#   POST /dispatch
#     in:  { service: "stt" | "llm" | "tts", payload, model_version? }
#     out: { result, replica_id, model_version_used }
#   GET /healthz
#
# PRODUCTION BACKEND
#   NVIDIA Triton Inference Server, or the batching/serving layer built
#   into vLLM/TensorRT-LLM directly -- not a bespoke component.
# =============================================================================
