# =============================================================================
# terraform/gpu-pool.tf -- AI compute pool sizing (PLACEHOLDER)
# =============================================================================
#
# Would define the GPU node pools backing stt-service, llm-gateway, and
# tts-service, sized per docs/scaling.md's capacity math:
#
#   pool            | GPUs (conservative, full 2.2M peak concurrency)
#   ----------------|--------------------------------------------------
#   asr-gpu-pool     | ~22,222  (stt-service)
#   llm-gpu-pool     | ~5,556   (llm-gateway)
#   tts-gpu-pool     | ~11,111  (tts-service)
#
#   -> ~38,900 GPUs total; ~11,700 under the answer-rate-adjusted
#      scenario (see benchmarks/cost_calculator.py, Scenario B).
#
# Would also define:
#   - Autoscaling policy tied to concurrent-active-call metrics (from
#     analytics/monitoring), not raw CPU/GPU utilization alone
#   - Spot/reserved capacity mix (docs/cost-analysis.md assumes a blended
#     ~$1.5/GPU-hr reserved/owned rate)
#   - GPU SKU choice per pool (e.g. L4/A10G-class for batched inference)
#
# Not implemented here: no real resource blocks. Real throughput-per-GPU
# assumptions (streams_per_gpu in benchmarks/cost_calculator.py) need
# load-test validation before this would size an actual order.
# =============================================================================
