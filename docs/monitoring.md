# Private monitoring and attack traces

## Local access

- Current implementation: http://localhost:8080/monitor
- Offline AgentCore alternative: http://localhost:8081/monitor

The generated `MONITOR_PASSWORD` is in the repository’s ignored `.env` file, with file mode 0600. It is not printed, committed, embedded in frontend code, or copied into container images. Both local implementations use that password, with separate operator cookies. The customer website has no monitoring link or security controls.

The public page is a sign-in shell. Feed, trace, saved results and test execution APIs all require an independent operator session. Selecting the synthetic admin identity does not bypass this password: legacy global audit and scenario endpoints now require the operator session too. Traveler accounts retain access to their own existing audit records.

Sessions expire after one hour. Cookies are HttpOnly and SameSite=Strict. After loading changed environment configuration, password changes invalidate existing sessions on the next check. Recreate the API container after editing local `.env`; AWS secret changes are picked up within the five-minute cache lifetime. Sign-in is limited to five attempts per API worker/client address in five minutes. Set `MONITOR_COOKIE_SECURE=true` behind HTTPS in a deployed environment. Local HTTP uses false. Responses are marked no-store; session checks and feeds must not be cached by a deployment proxy.

## What is recorded

The live feed polls every five seconds while the page is visible. It shows the latest 100 tool audit records, recent application events, and the latest 20 saved attack runs. Counts are all-time totals in that deployment’s database. Filters apply to the fetched records. Selecting a row opens its correlation ID’s recorded events.

New chat flows record receipt, completion or failure. Gateway flows record tool receipt, policy decisions, dispatch start, tool response or processing failure. The alternative also records inference request/response boundaries through its offline contract simulator. These are application boundary events, not packet captures, complete container logs, or individual backend instruction traces. Older audit rows are explicitly labeled historical when step events do not exist.

Raw chat text, passwords, cookies, vendor credentials and freeform tool result bodies are not logged. The audit retains its existing allowlisted resource IDs. Controlled test runs additionally save their fixed synthetic attack arguments and the h04 injection excerpt, rendered as text, not HTML or instructions.

The new **Run tests** control uses a suite picker and a separate durable worker.
See [launcher setup and case inventory](test-launcher.md). It records queued/running
progress, individual outcomes and traces, and survives browser/API restarts. The
worker overlay is required; otherwise the button explains that execution is disabled.
The legacy synchronous six-fixture endpoints remain available only in the original
local mode without that overlay. They cannot bypass the durable launcher when enabled.

Persistence uses additive application event/history tables plus
`operator_test_jobs`, `operator_test_locks` and `operator_test_workers`. Existing
bookings are not reset. New queued/running jobs have a 180-second deadline; expired
runs become errors on polling/claim and preserve partial results. Historical legacy
runs have no such lease and may still show interrupted running states. Log/result
retention remains manual. Vendor Events are separate from application traces.

All local environments were shut down after validation on 2026-10-22. Follow the
launcher guide to start a deliberate new local session. The AWS portion is deferred
and the new launcher refuses cloud/paid execution until that integration is completed.

## Generic AWS secret deployment

No AWS account, login flow, access key, or account ID is embedded. Authenticate separately using your normal AWS process (for example, an existing SSO session or workload role). The script uses the standard SDK credential chain and your configured region; `--region` can override it. The local build never calls AWS.

Preview without AWS calls:

```sh
python3 scripts/deploy_monitor_secret.py --env-file .env --region us-west-2
```

After authenticating separately, deliberately create a new secret:

```sh
uv run python scripts/deploy_monitor_secret.py --env-file .env --region us-west-2 --secret-name your-app/monitoring --apply
```

`--apply` incurs [AWS Secrets Manager charges](https://aws.amazon.com/secrets-manager/pricing/). It stores exactly `{"password": MONITOR_PASSWORD}` from the private env file, using AWS-managed encryption by default. It refuses to overwrite an existing secret. The deployer needs `secretsmanager:CreateSecret`. The script never prints the password or SDK exception details.

On success it records `MONITOR_SECRET_ARN` in local `.env` and writes:

- `build/monitoring/runtime.env`: AWS password source, secret ARN, explicit secret-read enablement, region, and secure cookies. No password.
- `build/monitoring/read-secret-policy.json`: `secretsmanager:GetSecretValue` scoped to the exact created secret ARN, for attachment to the application’s runtime role.

Use that runtime configuration with the AWS application workload and its IAM role. Do not ship the local `.env` password file or mount personal AWS credentials into the application. Ensure the workload has Secrets Manager network access (a suitable VPC endpoint or approved egress) and HTTPS at its public boundary. This script provisions the secret and produces runtime configuration; it does not provision the entire application, TLS endpoint, VPC endpoint, or IAM role.

The server supports `MONITOR_PASSWORD_SOURCE=aws`, `MONITOR_SECRET_ARN`, and `ENABLE_AWS_MONITOR_SECRET=true`. It [retrieves the secret via the AWS SDK](https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets-python.html), caches it for five minutes, and fails closed when unavailable. There is no fallback to a local env password in AWS mode. Local `.env` intentionally remains in env mode after secret creation so the isolated local containers do not need AWS access. Keep or delete that local copy according to your operating process after deployment. If secret creation succeeds but later file writing fails, inspect the created secret in AWS before retrying; the script will not overwrite it.

## Checks

```sh
make monitor-test
make agentcore-monitor-test
```

These test protected APIs, admin bypass rejection, six saved outcomes, exact recorded denial flows, chat request-to-response correlation, logout and unchanged bookings. Unit tests cover tampering, expiry, rotation, provider failures/cache, redaction, and generic deployment plan/apply with a mocked AWS client. No real AWS resources are created by the tests.
