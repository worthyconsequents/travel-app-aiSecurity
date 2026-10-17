# Trend AI Gateway test — 2026-10-17

Tested the actual local Trend gateway v0.1.159. No model requests or booking mutations were made. Paid inference remains disabled.

| Check | Result |
|---|---|
| Deployment readiness | PASS: 1/1 ready, no restarts |
| Manager readiness | PASS: HTTP 200, ready=true |
| Scanners | PASS: prompt attack, harmful content and skyeyes loaded |
| Missing application key | PASS: HTTP 401 |
| Deliberately invalid application key | PASS: HTTP 401 |
| Supplied visionOneapikey.txt | BLOCKED: HTTP 401; MCP initialize did not succeed |
| Vendor Helm readiness test | PASS |
| Authenticated discovery and six attack fixtures through Trend | BLOCKED by authentication; not claimed as policy tests |

The key was read only for a local request to the Trend data plane, held in memory, never placed in command arguments or logs, and never sent directly to an external endpoint by this test. HTTP redirects and environment proxies were disabled. The temporary loopback port-forward was terminated after testing. The test report contains no credential value.

The catalog logs show one virtual key and zero LLM providers. That establishes that a virtual key was received in the catalog, but does not establish that the supplied file contains it or that the key has correct scope/validity. The supplied file has JWT structure; format alone is not proof of key type. A 401 can reflect an incorrect credential type/value, revocation/expiry or key scope/availability.

Next: obtain a currently valid AI Gateway application virtual key from the configured Vision One gateway, save only its raw value into `AI_Gateway/visionOneapikey.txt`, and rerun authenticated MCP initialization and tool discovery. Once that succeeds, validate MCP catalog entries, tool policies and audit evidence before running attack fixtures against Trend. Do not replace it with a broad tenant API key or disable virtual-key authentication.

The customer website remains operational through the reference gateway. Its six scenario results are separate from this Trend test. Machine-readable results: `trend-gateway-test-results.json`.
