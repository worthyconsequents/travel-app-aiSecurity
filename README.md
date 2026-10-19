# the boring-travel company · AI security demo

A local travel website with destination photography, a scripted travel assistant, protected MCP tools, and a separate password-locked operations dashboard. All travelers, hotels, bookings, payments and attack fixtures are synthetic. The build makes no paid model calls and does not deploy AWS resources automatically.

## Run locally

Requires Docker Desktop with Compose, Make, and Python 3 for host-side verification scripts.

1. Copy `.env.example` to `.env` and set `MONITOR_PASSWORD` to a unique 24–256 character password. Keep `.env` private (`chmod 600 .env`).
2. Run `make up` for the current implementation.
3. Optionally run `make agentcore-up` for the separate offline AgentCore implementation.

| | Current implementation | Offline AgentCore alternative |
| --- | --- | --- |
| Travel website | http://localhost:8080 | http://localhost:8081 |
| Private monitoring | http://localhost:8080/monitor | http://localhost:8081/monitor |

Choose Alice or Bob to browse 12 stays across Lisbon, Kyoto and Vancouver. Open **A little travel help** to search stays, request hotel details or view that traveler’s trips. Traveler changes clear the conversation. The assistant is deterministic and each message is standalone; it is not a live LLM. Booking mutations, payments and approval grants are not available through this chat.

The monitoring page uses `MONITOR_PASSWORD`, independently of traveler/admin demo identities. It shows saved attack outcomes, actual application events, audit records and request traces. Historical audits without step telemetry are labeled accordingly. Passwords, raw chat messages and credentials are excluded from logs. See [monitoring setup and evidence scope](docs/monitoring.md).

## Verify

```sh
make lint smoke chat-test monitor-test scenarios
make agentcore-chat-test agentcore-monitor-test
```

`make test` and `make agentcore-test` also run the broader synthetic booking lifecycle tests, which create and cancel test reservations. The focused chat and monitoring checks preserve existing bookings. The latest verification passed 104 unit tests per implementation, protected monitoring checks, saved outcomes for all six attack fixtures, chat regressions and the offline gateway checks. See [monitoring verification](docs/monitoring-verification.json) and [attack vector map](docs/attack-vectors.md).

`make down` and `make agentcore-down` stop their respective stacks while preserving data. `make seed` is idempotent. `make demo-reset` deletes the current stack’s synthetic database contents and reseeds them.

## Enforcement and evidence

The current path is browser → NGINX → Next.js / FastAPI → local reference policy → three MCP services → Postgres. The alternative keeps the company UI but routes inference/tool requests through local AgentCore contract simulators with interceptor tests. Each stack has its own database, networks and session cookies. Only NGINX exposes a loopback port.

Ownership, workload permissions, scoped capabilities and explicit mutation approvals are enforced server-side. The six attack fixtures exercise indirect injection, cross-customer reads, privileged-tool misuse, approval requirements, bulk-data transfer and identity spoofing. The injection fixture forces a malicious tool request; it does not show a real model being persuaded. Unprotected consequences are hypothetical.

This is a local demo. Identity selection and shared database/service credentials are not production authentication. The completed isolated AWS staging test verified gateway routing and live Trend inspection, but Trend allowed the tested injection. All test-created AWS resources were subsequently removed and their absence verified. Full application AWS/model integration and effective Trend blocking remain unverified; see [live AWS test results](docs/aws-test-deployment.md). Local policy denials and offline interceptor results must not be described as live Trend detections. See [assistant behavior](docs/travel-assistant.md), [architecture](docs/adr-001.md), and [AgentCore handoff](docs/agentcore-alternative.md).

## Generic AWS deployment preparation

AWS clients, Lambda interceptor packaging, CloudFormation foundation and gateway request templates are included. A separate [isolated AWS gateway test deployment](docs/aws-test-deployment.md) adds explicit account checks, private artifacts, a dedicated secret, live inspection, a synthetic read-only tool and bounded verification commands; it does not host the full application. The test environment has been torn down; its deployment and guarded cleanup commands remain available. The final offline suite passed 130 unit tests. `make agentcore-plan` validates request shapes offline; `make agentcore-package` builds a local Lambda ZIP.

`make monitor-secret-plan` previews Secrets Manager setup without contacting AWS. To create the monitoring secret, a deployer authenticates separately using their normal AWS workflow and explicitly runs `scripts/deploy_monitor_secret.py --apply` with the project’s Python dependencies installed. The script uses the SDK credential chain; it embeds no account, login flow or access key. It reads the password from private `.env`, creates a new secret, records its ARN, and emits runtime configuration plus a narrowly scoped read policy. See the [AWS secret deployment instructions](docs/monitoring.md#generic-aws-secret-deployment).

Explicit AWS and paid-inference opt-ins remain required. Local containers do not mount AWS credentials and their private service network has no internet egress. Publishing this repository does not deploy services or enable model billing.

## Optional Trend gateway references

The public Trend chart and local configuration templates are under `infra/trend-gateway/`; the app continues to use the reference policy until a commercial gateway is configured and verified. Supplied guides, tenant registration overrides, API keys, local cluster credentials and generated runtime files are excluded from Git. See [gateway integration notes](infra/trend-gateway/README.md).

Photography sources and license links are in [the image credits](docs/photography.md) and `frontend/public/photos/credits.json`.
