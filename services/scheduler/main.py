# =============================================================================
# scheduler (predictive dialer / campaign-pacing service)
# =============================================================================
#
# RESPONSIBILITY
#   Paces outbound dial attempts against the 1B-calls/day target (see
#   docs/scaling.md: ~37,000 dials/sec at peak), runs the live
#   consent/DND/calling-hours compliance gate before every single dial,
#   and (in production) runs AMD (answering-machine detection) so
#   non-connects never reach the AI pipeline -- the single biggest cost
#   lever in docs/cost-analysis.md (answer-rate filtering cuts the AI
#   compute fleet by ~3x).
#
# WHY THE COMPLIANCE GATE IS "LIVE," NOT A BATCH FILTER
#   At this call rate, an opt-out or a calling-hour-window boundary must
#   take effect within the same second it's registered -- a once-a-day
#   batch check would let millions of non-compliant dials slip through
#   during the gap. See docs/security.md.
#
# SCALE NOTE
#   At 1B calls/day this service itself must be horizontally sharded
#   (e.g. by campaign/region) -- a single instance cannot evaluate
#   ~37,000 dial-decisions/sec. See docs/scaling.md and
#   infrastructure/kubernetes/ for the autoscaling approach.
#
# API CONTRACT (planned)
#   POST /dial-decision
#     in:  { borrower_id, borrower_local_hour, opted_out, on_dnc_registry,
#            window_start_hour, window_end_hour }
#     out: { borrower_id, allowed, reason }
#   GET /healthz
#
# OUT OF SCOPE FOR THIS REPO
#   Real AMD and real dial pacing against live carrier trunk capacity --
#   both require a live telephony stack. See docs/future-improvements.md.
# =============================================================================
