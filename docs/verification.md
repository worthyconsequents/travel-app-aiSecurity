# Verification — local base build, 2026-10-17

## Prior-chat evidence

The retrieved chat “Build Secure Travel Demo” reported module compilation and basic policy smoke checks only, explicitly leaving full Docker, Bedrock and AWS integration tests outstanding. The inherited workspace log claimed an M0 startup pass; it is not used as evidence for this build. Rebuilding uncovered invalid MCP parameter names and stale NGINX upstream addresses; both were repaired and retested.

## Current verified results

- `docker compose up --build -d --wait`: all eight services healthy after repairing MCP registration. Next.js production compilation and TypeScript checks passed during build.
- `make test`: 21 Python unit tests passed; the actual gateway→MCP Streamable HTTP→PostgreSQL integration runner passed, plus frontend HTTP availability.
- Integration runner: discovers 10 tools from all three MCP servers; searches 12 hotels/3 destinations; verifies hotel detail, customer profile, owner-only bookings, cross-customer denial, explicit approval before creation/cancellation, single-use approval rejection, idempotent replay, mock chat, and all six attack fixtures with corresponding audit evidence and no denied booking mutation.
- `make lint`: Ruff checks and formatting passed.
- `make smoke`: published NGINX routes and upstream service identity, same-origin session cookie flow and owned bookings. Extended after browser testing caught the stale-upstream bug that status-only checks missed.
- `make scenarios`: all six expected decisions passed; no booking mutations. Unprotected results are explicitly inert illustrations. Prompt injection fixture forces the malicious tool request; it does not demonstrate a real model being compromised.
- Browser verification through the published proxy: Alice hotel search shows 12 stays and her bookings; Kyoto filter plus Bob selection shows four Kyoto stays and Bob's own booking. Screenshot captured of the original local landing page.

## Files added or changed in this pass

Frontend landing page and styles; startup/chat cost guard (`services/settings.py`, API and agent); Compose network isolation; MCP capability parameter naming and reserved-argument checks; NGINX dynamic upstream resolution and Host preservation; 20 additional unit cases; missing HTTP integration runner; stronger proxy smoke script; Makefile; README, ADR, checklist and this report. Existing application source and lockfiles were reused.

## Acceptance status

M0 foundation is verified. Initial M1 read UI and backend portions of M2–M5 are verified by the checks above, but the complete milestone gates are not claimed. This is not a full end-to-end certification of the attached build plan.

Known limits: no automated Playwright suite, browser checkout, persistent chat UI, security dashboard UI, AWS templates, dependency scan, actual commercial adapter, or paid-model validation. The gateway-outage unit test mocks a connection failure; physically stopping the gateway and approval concurrency remain future tests. One dependency deprecation warning comes from FastAPI/Starlette TestClient's httpx integration; tests pass.

Next: hotel detail and explicit checkout UI with browser automation, then chat/dashboard and remaining hardening. Bedrock and AWS require explicit user cost approval before use.
