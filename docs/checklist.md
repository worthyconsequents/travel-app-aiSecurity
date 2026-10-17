# Build checklist

Current scope: local foundation first, per the user. The attached plan is the target specification; its instruction to continue through all milestones does not override this scope or the requirement for cost approval.

- [x] Inspect and preserve the existing workspace source; create the requested Documents/Chatgpt repo.
- [x] M0 foundation: architecture ADR, lockfiles, Compose, private MCP network, health checks, Makefile, README.
- [x] Disable paid inference in application code and remove API egress; no cloud resources or model calls.
- [x] Rebuild all eight containers and verify health.
- [x] Verify real MCP discovery/invocation across all three services, synthetic inventory, owned reads, approved booking/cancellation, audit decisions and six safe attack fixtures.
- [x] Unit tests, Python lint/format, Next.js production TypeScript build, proxy smoke tests, browser search and customer switching.
- [ ] M1 completion: hotel detail route, date/guest search, checkout UI, automated Playwright suite. Current preview covers inventory and owned booking reads only.
- [ ] M2 completion: broaden schema/timeout/retry/concurrency/transport tests. Basic real HTTP transport is verified.
- [ ] M3 completion: persistent agent UI and conversation flow; Bedrock implementation review and explicit cost approval. Inherited Bedrock code is disabled and untested.
- [ ] M4 completion: approval race tests, real stopped-gateway test, workload credential isolation and stronger network separation. Current gateway-unavailable unit test mocks a transport failure.
- [ ] M5 completion: live security dashboard and replay UI. Protected fixtures pass; unprotected outcomes are inert illustrations, not an executed vulnerable agent.
- [ ] M6: dependency/security scans, broader hardening, complete end-to-end gates.
- [ ] M7: AWS templates and static validation; no deployment authorized.
- [ ] M8: Trend AI Gateway selected and deployed locally (v0.1.159, ready); app transport adapter, virtual key/catalog configuration and vendor-enforcement tests remain pending.
