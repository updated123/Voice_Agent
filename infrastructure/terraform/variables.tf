# =============================================================================
# terraform/variables.tf -- input variables (PLACEHOLDER)
# =============================================================================
#
# Would define, at minimum:
#   - target_calls_per_day        (default: 1_000_000_000, see docs/scaling.md)
#   - operating_hours             (default: 12 -- legal calling window)
#   - peak_multiplier             (default: 1.6)
#   - avg_call_duration_sec       (default: 60)
#   - answer_rate                 (conservative: 1.0, realistic: 0.3)
#   - region_list                 (multi-region active-active deployment)
#   - gpu_sku_per_pool            (per docs/architecture.md tech choices)
#   - reserved_vs_spot_ratio
#
# These mirror the Assumptions dataclass in benchmarks/cost_calculator.py
# so infra sizing and the cost model stay derived from the same numbers
# rather than drifting independently.
# =============================================================================
