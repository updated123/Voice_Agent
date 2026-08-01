# =============================================================================
# terraform/main.tf -- top-level infrastructure entry point (PLACEHOLDER)
# =============================================================================
#
# Would define, at the scale in docs/scaling.md (peak ~2.2M concurrent
# calls, ~39K AI-compute GPUs, ~1,500 media servers):
#
#   - Multi-region provider blocks (active-active regions, see
#     docs/architecture.md's failure-domain table)
#   - The GPU compute pools for ASR / LLM / TTS (see gpu-pool.tf)
#   - The CPU media-server fleet (VAD/denoiser/AEC tier)
#   - Networking: VPCs, regional peering close to carrier PoPs
#     (docs/architecture.md's Carrier Routing Layer), load balancers
#     fronting each services/ microservice
#   - IAM roles/policies per service, least-privilege
#   - Remote state backend (S3/GCS + locking) for a team-scale, multi-region
#     deployment
#
# Not implemented here: no real provider/resource blocks. This file is a
# structural placeholder -- see docs/deployment.md for the narrative
# deployment plan this would encode.
# =============================================================================
