# AWS Trend capability comparison — 2026-10-22 Pacific

> Historical diagnostic before the opaque-reference fix. The fix is now deployed
> and core acceptance passed 12/12; see [current status](aws-deployment-issues.md).
> The comparison and proposed next steps below retain their capture-time scope.

Eight fixed read-only calls ran in a single bounded AWS Kubernetes Job, with
business-policy checks before dispatch, virtual-key authentication, Trend
inspection, and backend signature verification kept enabled. No real models or
paid inference were used. Synthetic booking state was unchanged.

The two tool inputs were `get_my_bookings(booking_id="booking-alice")` and
`search_hotels(destination="Kyoto")`. Both produced the same outcomes:

| Capability variant | Trend request inspection | Backend result |
| --- | --- | --- |
| Omitted | No request content-policy block observed | Correctly rejected missing capability |
| Short invalid literal | No request content-policy block observed | Correctly rejected invalid capability |
| Valid signed capability | Request content-policy block | No successful tool execution |
| Same encoded body, one signature character changed | Request content-policy block | No successful tool execution |

The valid tokens were locally verified before dispatch. For the final pair the
encoded body was identical; only the HMAC signature's last character changed.
The test never printed capability values or returned booking/customer data.

This strongly associates the full capability value with the false positive.
Merely including the argument name is insufficient to reproduce it: the short
invalid literal was inspected and reached backend rejection. Content inspection
did not distinguish the valid and tampered full tokens in this comparison.
The exact influence of length, encoding, decoded fields or particular substrings
has not been isolated. Do not claim a vendor classifier algorithm or signature
validation defect from these results.

The operator independently supplied a related Vision One benign-booking Guardrail
event. It reported sexual and sexual-minors categories marked low and the
prompt-attack classifier marked high under `dtran-boring-travel-policy`.
The prompt-attack score was 0 with contentViolation true; score semantics remain
unverified. Those reported categories are false positives for the known synthetic
business operation, not evidence of such content in a travel booking.

[Sanitized per-case evidence](trend-capability-comparison-results.json) includes
UTC timestamps and audit/correlation IDs for independent event comparison. Cases
ran at 2026-10-23 05:44:25–05:44:56 UTC (October 22 10:44:25–10:44:56 PM Pacific).
The fixed diagnostic source is `scripts/trend_capability_probe.py`; it requires
explicit AWS Trend mock mode and the deployment's private service route. The test
was injected into an authorized one-shot Job using the existing worker image and
credential mounts; it was not added to public request paths or used as a fallback.

Next: review how to separate opaque authorization metadata from inspected business
arguments, or confirm a vendor-supported field-exclusion mechanism. Neither
option has been implemented or verified. Continue inspecting business arguments,
keep capability verification at the backend, and test both legitimate calls and
injection controls together before changing the application transport. Do not
solve this by disabling guardrails, accepting unsigned calls, or broadly allowing
this identity to bypass inspection.
