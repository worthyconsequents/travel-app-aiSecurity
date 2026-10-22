# AWS session handoff — remote monitoring test launcher

Prepared 2026-10-22. Read this file, root `AGENTS.md`, `docs/AGENT_HANDOFF.md`,
`docs/test-launcher.md` and `docs/test-validation-matrix.md` before editing.
This document is context, not permission to deploy or spend money.

## User intent and current boundary

The user wants the travel website and protected monitoring page hosted in AWS with
a domain, and a monitoring button that launches bounded tests remotely. They asked
to complete local portions first and move AWS work to another session. They clarified
that the requested teardown was **local**, and explicitly said AWS sign-in was not
needed. Do not resume the outstanding AWS login/audit request automatically.

Keep the `working-edition` branch; do not merge main. This launcher/handoff is
committed locally; verify that the commit has been pushed before continuing on
another machine. This session did not publish the new changes to GitHub. Keep boring-travel branding.
Use the `dannytran-` prefix for AWS resources where allowed; Cedar uses underscores.
No personal account/profile/domain is embedded. Do not deploy AWS, register a paid
domain or invoke models without fresh user approval of scope and cost.

## What was built

- Monitoring suite picker and asynchronous **Run tests** button, progress, history,
  per-case status/source and recorded request flows.
- Strict operator-authenticated API with suite allowlist, custom action header,
  idempotent enqueue and sanitized job polling.
- Durable DB queue, unique per-deployment run lock, atomic worker claims, heartbeat
  readiness, hard deadline, stale-worker fencing and preserved partial results.
- Separate local worker and reference/offline/Trend adapters. Fixed synthetic cases
  only; no shell/URL/code submission, mutation approvals, resets or outage controls.
- Local reference/offline Compose recipes and a repeatable HTTP smoke helper.

Reference files: `services/test_jobs.py` (queue contract), `services/test_cases.py`
(allowlisted adapters), `services/test_worker.py` (local polling process),
`services/monitor.py` (endpoints), `frontend/app/monitor/page.tsx` (UI),
`compose.test-runner*.yaml`, `scripts/test_runner_smoke.py`.

## Important: not a deploy-ready AWS launcher

The launch/worker configuration **deliberately refuses APP_MODE=aws-demo,
DEPLOYMENT_PROFILE=agentcore-aws, paid model modes and backend=ecs**. Existing AWS
fleet templates do not yet contain the new worker/dispatcher or its permissions.
Do not merely remove those guards or enable the old synchronous runner in AWS.

The existing worker polls indefinitely and claims queued work. The proposed AWS
plan uses one isolated Fargate task per run; implement an exact-job/one-shot worker
entry point and authenticated ECS dispatcher for that plan. Local enqueue currently
requires a recent worker heartbeat; an on-demand ECS backend needs a different
explicit readiness/dispatch contract rather than pretending a stopped worker is ready.

## Next implementation steps, before any cloud writes

1. Review the existing AWS fleet factories, lifecycle safeguards, frozen blueprint
   behavior and native AgentCore private MCP targets. Choose AgentCore as the first
   cloud route unless the user chooses otherwise. The standalone local Trend kind
   cluster and its private Docker URLs cannot serve AWS workloads.
2. Bind run authorization to verified Cognito operator identity/group, in addition
   to the monitor password. Verify signed ALB claims and trusted proxy boundaries;
   never trust user-supplied role/identity headers. Record the initiating operator
   using a safe identifier. Preserve per-copy DB and namespace isolation.
3. Fix/review HTTPS-origin validation behind the actual trusted ALB/NGINX chain.
   Current API compares Origin to request scheme/Host; HTTPS termination followed
   by HTTP proxying needs explicit trusted-proxy handling. Do not bypass CSRF checks
   or blindly trust public forwarding headers.
4. Add exact-task-definition Fargate dispatch, tightly scoped RunTask/PassRole,
   private networking and a separate worker role. Use run ID as an idempotency
   token; reconcile task-placement/dispatch failure to the saved job. Ensure
   enqueue/dispatch recovery cannot duplicate execution. Bound queue wait, task
   runtime, launch frequency and concurrency; do not use the local 180-second
   enqueue deadline blindly for cloud task cold start.
5. Preserve business authorization before AgentCore tool dispatch. Adapt AWS-safe
   test expectations to Cedar's narrower read-only policy. Do not assume the six
   local fixture reason codes are cloud policy results. The worker must not read
   the shared AI Guard detection credential: inspection Lambdas retain exact-secret
   access; the app/worker/browser do not receive that credential.
6. Integrate domain/certificate preparation into the reviewed deployment workflow.
   Existing settings: `DEPLOYMENT_DOMAIN`, `DEPLOYMENT_HOSTED_ZONE_ID`,
   `DEPLOYMENT_CERTIFICATE_ARN`, `DEPLOYMENT_ALLOWED_CIDR`, expected account/Region,
   image digests and shared AI Guard secret ARN. Each copy uses
   `https://<copy-name>.<domain>` and `/monitor`. Confirm real DNS delegation and an
   issued ACM certificate covering each hostname; do not buy/register a domain
   without authorization. Keep public tool/DB ingress closed.
7. Add scoped evidence collection. Application traces and real vendor/CloudWatch
   decisions are currently separate. Never fabricate vendor events or treat an app
   failure/unsigned denial as a content block. Keep secret values and capabilities
   out of event exports. Add retention limits and cleanup inventory.
8. Add offline tests for AWS dispatcher shapes, authorization, duplicate dispatch,
   task failure, startup timeout, per-copy isolation, secret access, HTTPS origins
   and no paid fallback. Render/lint/security-check all updated templates.
9. Present one-copy resource inventory, current regional cost estimate, domain
   prerequisites and teardown plan. Obtain approval before AWS writes. Start one
   copy with paid inference disabled; validate login, HTTPS, remote button, replay,
   worker loss, authorization denials and actual input/output inspection evidence
   before increasing `DEPLOYMENT_COUNT`.

## Known gateway issue

The previous local Trend test discovered ten tools and blocked one synthetic
request injection, but legitimate signed app requests also received prompt-attack
denials. The signed capability in inspected arguments appears involved; exact
classifier cause is unconfirmed. Console tool import also reported a missing
platform-secret file, and explicit vendor tool ACLs were not configured. Keep both
inspection and backend capability checks. Do not report vendor acceptance complete.
The historical AWS gateway fixture separately allowed its injection; that test was
removed in October 2026. Neither result is proof of real-model susceptibility.

## Earlier runtime/cleanup snapshot (superseded locally)

All three original local app Compose stacks were removed without deleting their
Postgres volumes. The dedicated `boring-travel-control-plane` kind container was
stopped, preserving its cluster state. Private `.env`, vendor keys and kubeconfig
remain ignored/owner-only. Images and the unused kind network are intentionally
retained; no Docker-wide prune was used. Trend console objects were not deleted.
Temporary launcher-validation stacks were also removed after checks, including
only their disposable new DB volumes. Verify the cleanup JSON before asserting a
runtime is active. The later approved tool-change experiment restarted local previews on 8085/8082
and the kind node. See [current runtime](tool-changes-verification.json). The AWS
scope below remains unchanged.

AWS was not changed. An initial read-only STS check failed due to an expired login;
after the user's clarification, no login or further AWS audit was attempted. The
old private manifest records the 2026-10-19 AWS teardown as complete, but this
session did not independently re-verify AWS absence. Do not claim a fresh AWS audit.

Use the next session's operator credential chain, not copied local credentials.
Private ledgers under `build/` are not portable deployment inputs and must not be
published. If using another machine, supply fresh runtime secrets and explicit
account/Region/domain settings. GitHub does not include those private files.

## Dynamic MCP tool changes — 2026-10-22

See [the tool-change report](tool-changes.md) and the two new diagrams embedded in
the root README. The opt-in local monitoring suite has 13 cases. Complete unit suite:
217 passed. Local fixture run: 10 passed/3 unavailable. Live Trend run: 10 passed,
1 failed, 2 unavailable. Discovery refresh worked; the app rejected a new tool;
a direct gateway call executed it and Vision One recorded Allow. Inventory still
appeared empty when checked, and console discovery retained a missing-secret error.
Do not claim vendor least-privilege enforcement or notification support.
Travel contracts now use a reviewed full-metadata/schema baseline; no network
observation auto-approves tools. Fixture state restored, bookings unchanged.
This work used local Docker/kind and the existing Trend subscription; no AWS or
paid models. Current runtime state is recorded in the tool-change verification
JSON; the earlier local-cleanup snapshot is historical. Changes stay on
working-edition, without an automatic commit, push, merge or cloud rollout.
