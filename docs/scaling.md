# Scaling & Capacity Planning

All figures reproducible via [benchmarks/cost_calculator.py](../benchmarks/cost_calculator.py) — treat the numbers below as one scenario with the assumptions stated.

## Step 1: from "calls/day" to "concurrent calls"

Regulations typically restrict outbound collection calls to a daytime window (e.g. 8am-9pm local, FDCPA-style; similar restrictions under Indian TRAI/RBI guidance), and traffic concentrates around certain hours even within that window.

**Assumptions:** `TOTAL_CALLS_PER_DAY = 1,000,000,000`, `OPERATING_HOURS = 12`, `PEAK_MULTIPLIER = 1.6`, `AVG_CALL_DURATION_SEC = 60`.

```
avg_calls_per_sec (24h)        = 1e9 / 86,400            ≈ 11,574 calls/sec
avg_calls_per_sec (12h window) = 1e9 / (12 × 3600)        ≈ 23,148 calls/sec
peak_calls_per_sec             = avg_window × 1.6         ≈ 37,037 calls/sec

concurrent_calls_avg  = avg_calls_per_sec_window × avg_duration_sec  ≈ 1,388,889
concurrent_calls_peak = peak_calls_per_sec × avg_duration_sec        ≈ 2,222,222
```

**Peak concurrency to design for: ~2.2M simultaneous active calls.** This one number drives every downstream sizing calculation — telephony ports, media servers, GPU pools.

## Step 2: telephony/PSTN capacity — the real bottleneck

2.2M concurrent outbound channels is larger than the total concurrent-call capacity most single carriers offer. Realistic sizing requires **on the order of 50-100+ separate carrier relationships/trunk groups**, spread across multiple regions, each independently STIR/SHAKEN-attested, plus **millions of distinct outbound numbers**, actively rotated and reputation-monitored to avoid blanket "Spam Likely" flagging (which would silently collapse the answer rate regardless of how good the AI is).

This is flagged as the primary real-world constraint — solvable in principle, but a telecom-industry/regulatory scaling problem, not a software one. See [architecture.md](architecture.md).

## Step 3: media server (`vad-service`/`denoiser` CPU tier) sizing

A well-tuned FreeSWITCH/Jambonz instance handles ~1,000-2,000 concurrent RTP audio streams per box.

```
media_servers_needed = concurrent_calls_peak / streams_per_box ≈ 2,222,222 / 1,500 ≈ 1,482
```

Round up with N+1 redundancy per region → **~1,500-1,800 media server instances**.

## Step 4: AI compute pool sizing (`stt-service` / `llm-gateway` / `tts-service`)

GPU pools only need to be sized for concurrently *speaking* calls, not all connected calls — VAD gates audio at the edge, so silence/hold/dead-air never reaches these pools.

| Pool | Streams/GPU (assumed) | GPUs needed at 2.22M peak |
|---|---|---|
| `stt-service` | 100 | 22,222 |
| `llm-gateway` | 400 | 5,556 |
| `tts-service` | 200 | 11,111 |
| **Total AI compute GPUs** | | **≈ 38,900** |

These per-GPU throughput numbers are **planning assumptions, not benchmarked figures** — real numbers depend on model choice, quantization, sequence length, and GPU SKU, and should be replaced with load-test results before committing to hardware.

**`llm-gateway`'s 400 streams/GPU predates folding sentiment classification and model-tier routing into it** (see `docs/architecture.md`'s "Consolidated into an existing service" section) — this table was never updated to reflect that `llm-gateway` now runs strictly more inference per request (intent + sentiment + a routing pre-classifier) than a single intent-only classification call. This wasn't a new gap introduced by the consolidation, though: sentiment classification's compute cost was never counted anywhere in this table even when it was a separate `sentiment-detector` service — its own row back then said "Gap-closing addition" with no GPU figure, meaning it was already missing from the 38,900 total. Folding it in just makes the omission visible instead of hidden across two rows. Treat 5,556 as an underestimate for `llm-gateway`'s real GPU need until a load test replaces it — this is exactly the kind of number "should be replaced with load-test results" above is warning about.

## Step 5: sensitivity — what moves this number the most

| Lever | Effect |
|---|---|
| **Answer rate / AMD accuracy** | If only ~25-30% of dials connect (typical for collections) and non-connects are filtered before touching the AI pipeline, the AI pools can be sized for ~30% of raw dial concurrency — roughly a **3x reduction** in GPU count. |
| **Avg call duration** | Concurrency scales linearly with duration. 60s → 45s blended AHT is a direct ~25% cut across telephony and compute sizing. |
| **Streams/GPU (batching efficiency)** | The single biggest compute-cost lever — doubling batched throughput per GPU halves the AI compute fleet size directly. |
| **Operating window width** | Spreading calls over 16h instead of 12h cuts peak concurrency by ~25%, at the cost of needing regulatory approval for a wider window. |

Applying the answer-rate correction (AMD filters to 30% of dials reaching the full pipeline): AI compute pool drops to roughly **~11,700 GPUs** (11,667 from `benchmarks/cost_calculator.py`'s actual run — see [cost-analysis.md](cost-analysis.md)) — the more realistic planning figure. See [cost-analysis.md](cost-analysis.md) for both scenarios' full cost breakdown.

## Step 6: edge/ingress tier (`nginx`) sizing

Unlike every pool above, `infrastructure/nginx/nginx.conf` lists what the edge tier would *do* (TLS termination, regional routing, rate limiting) with no sizing math — a real omission, since it's the first hop of every single request in the system.

A well-tuned nginx instance terminating TLS and reverse-proxying can sustain on the order of 10,000-50,000 concurrent keep-alive connections per box, depending on cipher suite, hardware, and worker-process tuning (highly workload-dependent, more so than the media-server/GPU figures above — treat this range as a rougher planning assumption than those, not a benchmarked number).

```
edge_nodes_needed = concurrent_calls_peak / connections_per_box
                   ≈ 2,222,222 / 20,000 (mid-range assumption)
                   ≈ 112
```

Round up with N+1 redundancy per region → **~150-200 edge nodes**, small relative to the media-server (~1,500) and GPU (~38,900) tiers, but not zero — and worth naming explicitly rather than leaving as an unsized placeholder, since an under-provisioned edge tier would bottleneck every request behind it regardless of how well everything downstream is sized.

## Service-level scaling notes

- `call-orchestrator`: one lightweight, stateless replica per concurrently active call (~2.2M at peak) — the highest-replica-count service in the system by design, since it holds no state itself.
- `session-manager`: backed by Aerospike in production (Redis Cluster documented as the alternative), sharded by call-id — a single instance cannot hold ~2.2M live call records with acceptable latency.
- `scheduler`: must itself be horizontally sharded (e.g. by campaign/region) to evaluate ~37,000 dial-decisions/sec at peak.
- `analytics`/`billing`: decoupled from the synchronous per-turn path via a Kafka event backbone (see [../infrastructure/kafka/](../infrastructure/kafka/)) so neither adds latency to a live call.
