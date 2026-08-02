#!/usr/bin/env python3
"""
Cost & capacity calculator for the loan-collection voice agent.

Edit the ASSUMPTIONS block and rerun: `python3 cost_calculator.py`
Every number in docs/scaling.md and docs/cost-analysis.md is
reproducible from this script (with the same assumptions stated there).

This is a planning model, not a bill-of-materials — replace the per-GPU
throughput and per-minute telephony assumptions with real benchmark/contract
numbers before using this for procurement decisions.
"""

import json
from dataclasses import asdict, dataclass


@dataclass
class Assumptions:
    # ---- Volume & timing ----
    total_calls_per_day: int = 1_000_000_000
    operating_hours: float = 12.0          # legally-permitted daily calling window
    peak_multiplier: float = 1.6           # peak-hour rate vs. window average
    avg_call_duration_sec: float = 60.0    # blended across all dial attempts
    answer_rate: float = 1.0               # fraction of DIALS that connect & need full AI pipeline
                                            # (set to 1.0 for "conservative" scenario sizing every dial,
                                            #  set to ~0.3 for the "answer-rate-adjusted" realistic scenario)

    # ---- Infra throughput assumptions (tune to real load-test numbers) ----
    media_streams_per_box: int = 1_500
    asr_streams_per_gpu: int = 100
    llm_streams_per_gpu: int = 400
    tts_streams_per_gpu: int = 200

    # ---- Unit costs ----
    gpu_cost_per_hr_usd: float = 1.5        # blended reserved/owned amortized $/GPU-hour across the fleet
    media_server_cost_per_hr_usd: float = 0.15  # CPU box, $/hr amortized
    telephony_cost_per_min_usd: float = 0.0018  # blended wholesale PSTN termination, $/minute
    human_agent_cost_per_hr_usd: float = 8.0    # blended fully-loaded cost, escalation-queue agents
    escalation_rate: float = 0.12               # fraction of connected calls escalated to a human
    human_call_handle_min: float = 4.0           # avg minutes a human spends on an escalated call


def compute(a: Assumptions) -> dict:
    seconds_per_day = 86_400
    window_seconds = a.operating_hours * 3600

    avg_cps_24h = a.total_calls_per_day / seconds_per_day
    avg_cps_window = a.total_calls_per_day / window_seconds
    peak_cps = avg_cps_window * a.peak_multiplier

    concurrent_calls_avg = avg_cps_window * a.avg_call_duration_sec
    concurrent_calls_peak = peak_cps * a.avg_call_duration_sec

    # Telephony/media must handle every DIAL attempt (even unanswered ones ring the network briefly),
    # so those are sized off full peak concurrency.
    media_servers = concurrent_calls_peak / a.media_streams_per_box

    # AI compute (ASR/LLM/TTS) only needs to handle calls that actually CONNECT and run the full pipeline.
    ai_peak_concurrency = concurrent_calls_peak * a.answer_rate

    asr_gpus = ai_peak_concurrency / a.asr_streams_per_gpu
    llm_gpus = ai_peak_concurrency / a.llm_streams_per_gpu
    tts_gpus = ai_peak_concurrency / a.tts_streams_per_gpu
    total_ai_gpus = asr_gpus + llm_gpus + tts_gpus

    # ---- Costs (24h fleet running, simplification: fleet sized for peak runs all day) ----
    compute_cost_per_day = total_ai_gpus * a.gpu_cost_per_hr_usd * 24
    media_cost_per_day = media_servers * a.media_server_cost_per_hr_usd * 24

    minutes_per_day = a.total_calls_per_day * (a.avg_call_duration_sec / 60)
    telephony_cost_per_day = minutes_per_day * a.telephony_cost_per_min_usd

    connected_calls_per_day = a.total_calls_per_day * a.answer_rate
    escalated_calls_per_day = connected_calls_per_day * a.escalation_rate
    human_minutes_per_day = escalated_calls_per_day * a.human_call_handle_min
    human_cost_per_day = (human_minutes_per_day / 60) * a.human_agent_cost_per_hr_usd

    total_cost_per_day = compute_cost_per_day + media_cost_per_day + telephony_cost_per_day + human_cost_per_day

    return {
        "assumptions": asdict(a),
        "traffic": {
            "avg_calls_per_sec_24h": round(avg_cps_24h),
            "avg_calls_per_sec_window": round(avg_cps_window),
            "peak_calls_per_sec": round(peak_cps),
            "concurrent_calls_avg": round(concurrent_calls_avg),
            "concurrent_calls_peak": round(concurrent_calls_peak),
            "ai_peak_concurrency_after_answer_rate": round(ai_peak_concurrency),
        },
        "infra": {
            "media_servers": round(media_servers),
            "asr_gpus": round(asr_gpus),
            "llm_gpus": round(llm_gpus),
            "tts_gpus": round(tts_gpus),
            "total_ai_gpus": round(total_ai_gpus),
        },
        "cost_per_day_usd": {
            "ai_compute": round(compute_cost_per_day),
            "media_servers": round(media_cost_per_day),
            "telephony": round(telephony_cost_per_day),
            "human_escalation": round(human_cost_per_day),
            "total": round(total_cost_per_day),
        },
        "unit_economics": {
            "cost_per_call_usd": round(total_cost_per_day / a.total_calls_per_day, 6),
            "cost_per_connected_call_usd": round(total_cost_per_day / connected_calls_per_day, 6)
                if connected_calls_per_day else None,
            "cost_per_month_usd": round(total_cost_per_day * 30),
        },
    }


def print_report(title: str, a: Assumptions) -> None:
    result = compute(a)
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    conservative = Assumptions(answer_rate=1.0)
    print_report("SCENARIO A: Conservative (AI pipeline sized for every dial attempt)", conservative)

    realistic = Assumptions(answer_rate=0.30)
    print_report("SCENARIO B: Answer-rate-adjusted (AMD filters ~70% of dials before AI pipeline)", realistic)
