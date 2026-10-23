# Agent handoff — AI Gateway Travel App

Snapshot: 2026-10-22. Read this with the repository's root `AGENTS.md` and the
[test/validation matrix](test-validation-matrix.md). This is context and recorded
state, not authorization to deploy, spend money, delete resources or publish changes.
Current user instructions determine the authorized work.

## Latest consolidation and deployment state

Read [consolidation decisions](deployment-consolidation.md), [current teardown](aws-teardown-status.md)
and [recovery](recovery-bundle.md) before the historical notes below. Original AWS
runtime was verified torn down; retained recovery assets remain. The supplied export
reports another deployment's benign live Bedrock success, not independently verified
here. Reviewed code fixes are consolidated; no private export files were imported.
The consolidated offline suite passes 310 tests. Current user direction authorizes
committing on `working-edition`; no AWS rollout or paid inference is authorized.

## New Bedrock option and agent instructions

The operator requested an optional automated AWS Bedrock integration and a guide
for other LLMs. Start with [LLM_GUIDE.md](LLM_GUIDE.md) and
[the Bedrock runbook](bedrock-deployment-option.md). New adapter/chat/deployment
code is implemented and offline-tested, **not deployed or invoked with real models**.
Offline suite: 287 passed; lint, cfn-lint and three project Guard rules pass.
Preserve the live mock environment and its original evidence. The user has now requested publication of this subsequent work to `working-edition`;
verify the remote commit. The prior build was pushed as `32e1c83`.

## Latest user direction and resume point

The user reviewed documentation/diagrams and subsequently authorized publishing
the current changes to GitHub on October 23. Preserve `working-edition`; do not
merge main. Verify the remote commit before reporting publication complete. Runtime remains running; paid models
stay disabled and the old $100 ceiling is withdrawn.

Read [current status and issues](aws-deployment-issues.md),
[discovery mechanism](aws-discovery-explained.md) and
[the concise AWS handoff](AWS_TREND_RESUME.md). Core 12/12 and browser Inspection
3/3 passed; corrected mock discovery phases pass. AWS inventory attribution remains
pending; direct Trend new-tool denial failed while application denial passed.
Historical notes below retain their dated scope.

## Latest AWS Trend test continuation

See [AWS Trend test status](trend-aws-status.md) for the currently authorized
single-copy deployment, confirmed key authentication, resolved networking issues
and remaining upstream/attack acceptance checks. This supersedes older statements
below that no AWS Trend hosting exists; AgentCore fleet verification stays pending.

## Purpose and user decisions

The product is **the boring-travel company**, a realistic-looking travel website
with synthetic hotels, travelers, reservations and payments. Keep the public UI
focused on travel. Security demonstrations, attack results and request flows belong
in the separate password-protected `/monitor` operator page.

The user approved building a generic AWS multi-deployment option: `.env` selects
X independent copies, each with separate application state and infrastructure,
while their inspection Lambdas share one Trend AI Guard detection API credential.
Use `dannytran-` for created resource names where AWS permits it. Accounts, Regions,
profiles, domains and credentials must be deployer supplied rather than embedded.

The approved build has been implemented locally. It does not authorize a new paid
AWS rollout. The earlier $5 allowance was for a completed, removed gateway test.
No model calls or AWS API operations were made during the fleet implementation.

## Implementation scopes

| Scope | Actual behavior | Evidence boundary |
|---|---|---|
| Original local app | `compose.yaml`; original Compose project; website 8080; reference authorization gateway and three real HTTP MCP services; PostgreSQL | Deterministic assistant; application policy enforcement, no live model |
| Offline AgentCore alternative | Separate project `boring-travel-agentcore`; `compose.agentcore.yaml`; website 8081; local tool/inference contract simulator and shared interceptor handler | Simulated inference and inspection markers; no AWS/Trend calls |
| Local Trend alternative | Separate `boring-travel-trend` project; `compose.trend-test.yaml`; port 8082; virtual-key MCP proxy with exact tool map and authenticated private bridge | Ten tools discovered; scoped inspection active; legitimate signed app requests currently denied, so normal-use acceptance is blocked. See [Trend results](trend-local-test.md) |
| AWS fleet option | Full app hosting/gateway template factories and lifecycle runner; each copy gets Fargate, private RDS, VPC, Cognito-gated HTTPS ALBs, native private MCP targets, policy engine, inspector and secrets | Locally tested/validated; not deployed or verified end to end in AWS |

Do not apply the offline overlay with the original Compose project name. Local
stacks have separate networks, databases and cookies. Their private Docker service
networks have no internet egress. The separately installed local Trend AI Gateway
is not on the original application's active request path.

## Request paths and security boundaries

Original path: browser → NGINX → Next.js/FastAPI → reference business authorization
gateway → travel-discovery, reservations or customer-payments MCP service → database.
Authorization checks ownership, workload permissions, argument schemas, approvals,
single-use approval consumption and idempotency. The gateway signs a short-lived,
argument-scoped capability that backend tools verify. Model text cannot grant
identity, authority or approval.

The AWS path retains those business checks, then routes MCP requests through an
IAM-authenticated AgentCore gateway with request/response inspection and Cedar
enforcement. Native private targets reach TLS MCP ingress through managed VPC
Lattice. Per-copy NGINX verifies an additional ingress key before proxying tools.

Each AWS copy contains a single Fargate task with app containers; those containers
share a task role/network trust boundary. The inspector is a separate Lambda and
execution role. Copies are in one AWS account/Region, not separate account-level
security boundaries. Task and gateway roles cannot read the shared detection key;
only each copy's inspector has exact-secret access, plus scoped KMS decryption if
needed. The key is externally owned, not copied into each stack or browser.

Each copy has separate database, signing, MCP-ingress and monitoring secrets. RDS
connections use certificate verification with the AWS CA bundle. A Cognito login
gates every public route; self-registration is disabled. After login, operators can
select synthetic personas for scenarios. This is **not** production customer
identity mapping or Cognito group-based traveler authorization.

Shared credential rotation/revocation affects all inspectors; their token cache is
up to five minutes. Distinct Trend application names provide attribution, not
separate credentials, quotas or proof of independent vendor policy configuration.
A compromised inspector can expose the shared vendor key.

## Fleet configuration and lifecycle

See [deployment instructions](aws-multi-deployment.md) and `.env.example` for the
complete configuration. Main settings:

```dotenv
DEPLOYMENT_TARGET=aws
DEPLOYMENT_PREFIX=dannytran-travel
DEPLOYMENT_ENV=lab01
DEPLOYMENT_COUNT=3
ENABLE_PAID_INFERENCE=false
```

- Namespace: `dannytran-travel-lab01`; copies: `...-01`, `...-02`, `...-03`.
- One `...-shared` stack holds retained artifacts/ECR repositories. A copy uses
  hosting stack `...-01` and AgentCore stack `...-01-agentcore`.
- Count accepts 1–20. Increasing count adds copies; decreasing it never deletes.
  Existing indices keep their names. ALB/S3 names use stable shortened hashes.
  Cedar engine/policy names use `dannytran_` because hyphens are disallowed.
- `plan` and `render` are offline. `status` contacts AWS read-only. `foundation`,
  `publish-images`, `deploy` and `teardown` write to AWS and require apply/cost flags.
- Deployment checks the expected account; reads metadata for the shared secret,
  certificate, public zone, RDS version and image digests before provisioning the app.
  It does not read the detection token during this preflight.
- Deploy serially: shared foundation → hosting → AgentCore targets/policy → bind
  gateway endpoints. Local locks prevent concurrent operations for the same scope.
- The account/Region/namespace ledger is ignored under `build/aws-fleet/`. Stack
  identity and ownership tags are rechecked. Same-config retries resume completed
  phases. Changed blueprints require a new environment; automatic updates are
  limited to the initial binding of gateway parameters.
- Failure/rollback stacks require explicit inspection/remediation. Never delete a
  ledger to force adoption, overwrite ownership tags or broadly delete by prefix.
- Teardown selects one exact copy. It deletes AgentCore before hosting, snapshots
  RDS, retains app secrets/logs, and records retained resources. Other copies,
  shared artifacts/ECR and the external Trend key remain. Retention still costs
  money and can cause name conflicts if a deleted namespace is reused.

With paid inference disabled, cloud chat uses the deterministic planner and real
AgentCore tool routing. No model target or model invocation permission is created.
Cedar permits five read tools; mutations/refunds/bulk records default to deny.
The optional paid path uses a Messages-compatible Mantle model, a project-scoped
role with a model condition, an interceptor model allowlist, buffered responses and
bounded output tokens/tool iterations. It is not an aggregate spending cap and
has not been live-tested.

## Evidence and known failures

Latest complete unit pass: **227 unit cases passed**, including 10 model-probe/setup
cases added after the prior 217-case baseline. Ruff passed for the current tree;
production frontend/TypeScript checks passed in the earlier unchanged frontend.
Current local/live results and running previews are recorded in
[tool-changes-verification.json](tool-changes-verification.json). Earlier fleet
validation, not repeated for this local-only change: seven generated
three-copy templates passed cfn-lint and project cfn-guard rules. The optional paid
template passed static checks with fictitious references. Python/frontend amd64
images built from sanitized contexts; AWS-configured runtime imports and NGINX
configuration were checked with networking disabled. See
[offline verification JSON](aws-fleet-offline-verification.json).

These results do not prove that CloudFormation can deploy in a chosen Region,
the real MCP ingress/policy integration works, copies are isolated in a live account,
or a model/vendor detector blocks an attack. No service-side fleet validation,
full AWS deployment or browser/cloud acceptance run has been performed.

Historical live test on 2026-10-18 was a **different, limited gateway fixture**:
one read-only fixed hotel Lambda, real AgentCore gateway and Trend inspection.
Unsigned calls failed, benign lookup/discovery worked, malformed input was rejected,
and inspector outage failed closed with recovery verified. **Trend allowed the
synthetic injection; the expected content-blocking test failed.** The cause was
not established. No live LLM or real booking system was involved. Its 17 gateway
requests and results are documented in [the historical test report](aws-test-deployment.md).
All resources created by that test were subsequently removed and absence checked.
Do not reuse its deleted endpoint as a current deployment.

Application `/monitor` shows saved app activity/audits/results, not CloudWatch log
ingestion. Inspector decisions are in per-copy CloudWatch logs. The monitor's
automated scenario runner is local-only and refuses cloud runs. Local injection
fixtures force an attempted malicious tool request; unprotected outcomes are inert
illustrations, not actual data exfiltration or proof of model persuasion.

Historical evidence files contain older test counts and earlier milestone limits.
Preserve them as dated records. One existing FastAPI/Starlette TestClient httpx
deprecation warning remains; it did not fail the suite.

## Source map

| Area | Main files |
|---|---|
| API, personas and sessions | `services/api.py`, `services/auth.py`, `services/settings.py` |
| Business authorization and capabilities | `services/gateway.py`, `services/policy.py`, `services/capability.py` |
| MCP discovery/execution and storage | `services/mcp_client.py`, `services/mcp_server.py`, `services/tool_runtime.py`, `services/db.py` |
| Chat and model routing | `services/agent.py`, `services/travel_assistant.py`, `services/agentcore/agent.py`, `services/agentcore/transport.py` |
| Interception and vendor secret cache | `services/agentcore/interceptor.py`, `services/agentcore/inspection.py` |
| Monitor, auth and activity | `services/monitor.py`, `services/monitor_auth.py`, `services/telemetry.py` |
| Fleet CLI/config/templates/packaging | `scripts/aws_fleet.py`, `scripts/fleet_config.py`, `scripts/fleet_templates.py`, `scripts/fleet_package.py` |
| Fleet containers/security checks | `infra/aws-fleet/` |
| Historical gateway fixture and teardown | `scripts/aws_cloud_test.py`, `infra/agentcore/cloud-test*.json` |
| Approved diagrams | `docs/architecture/`, linked from root README |

## Working state and next action

The user requested that this build be isolated on **`working-edition`**, branched
from the `main` baseline `7efa23c` (approved architecture diagrams). Keep the fleet
implementation and these handoff/testing documents on that branch until full
acceptance testing and an explicit merge decision. Do not merge or push these
changes to `main` automatically. Inspect `git status`, `git log` and remote state
for the current commit/publication status; this note is not proof of a push.
Do not discard or overwrite unrelated user changes.

The next technical acceptance step is an authorized **one-copy AWS trial**, after
the deployer supplies real domain/certificate/image/secret references and approves
the current inventory and costs. Start with paid inference off. Follow the pending
cloud checklist in the test matrix. Verify Trend blocking independently before
claiming attack prevention; verify teardown and retained costs afterward. Publishing
to GitHub is a separate user-requested action, not a deployment prerequisite.

## Local Trend continuation — 2026-10-22

Read [trend-local-test.md](trend-local-test.md) before operating this profile. The local
integration is maintained on working-edition. Keep the original 8080/8081 stacks intact.
No AWS resources or paid model calls were used. Never print private runtime files,
virtual keys, upstream keys or signed capabilities. Scoped vendor inspection remains
active; legitimate signed requests currently fail closed. Do not silently fall back
or bypass inspection to make the site appear healthy. Console tool import, explicit
least-privilege access policy and full normal-use/outage acceptance remain pending.
The probe verifies one real content denial, not general attack protection.

## Portable monitoring launcher and current runtime state

The user requested local completion and moved AWS work to another session. Start
with [AWS_SESSION_HANDOFF.md](AWS_SESSION_HANDOFF.md) and
[test-launcher.md](test-launcher.md). The suite picker, durable queue, separate
worker, HTTP API, progress/history, locks, deadlines and redacted traces are built
and locally validated. APP_MODE=aws-demo and backend=ecs remain disabled for this
launcher; cloud operator authorization and dispatch are explicit next-session work.

Original local Compose containers/networks were removed, preserving their database
volumes. The dedicated kind node was stopped at the earlier teardown; the approved
tool-change experiment subsequently restarted it. See the current runtime record. Temporary
validation stacks/volumes were removed after checks. Private configuration and
Trend console entries were not deleted. No local web page should be assumed live.
The user clarified that no AWS login/audit was needed; AWS was not changed or
freshly verified absent in this session. See the cleanup verification record.

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

For the subsequent empty-inventory investigation, read
[trend-discovery-diagnosis.md](trend-discovery-diagnosis.md). Runtime list requests
and activity delivery are verified; no exact vendor inventory root cause is proven.
Console discovery still fails resolving a file that exists in the active local
gateway. Do not infer that model routing/paid inference is required or change
credentials/policies to bypass the mismatch. The temporary loopback diagnostic
forward was closed; the existing app/gateway previews were left running.

## Publication request — 2026-10-22

The user explicitly requested publishing the completed tool-change implementation,
README diagrams and discovery diagnosis to GitHub on `working-edition`. This also
publishes the preceding monitoring-launcher commit. Keep `main` unchanged. The
verification JSON files retain their capture-time publication/runtime snapshots;
use Git history and remote state for current publication status. The pre-push
check passed 217 unit tests, Ruff lint/format checks and credential/path screening.

## Local model-routing discovery follow-up — 2026-10-22

Read [model-discovery-probe.md](model-discovery-probe.md) and its sanitized JSON.
Both baseline and added-tool phases passed with independent provider/backend receipts.
Vision One displayed both tools with one call each; LLM and MCP Allow events matched.
This supersedes the earlier empty-inventory result only for this new model-request
path. Direct MCP inventory, active console import, automatic notifications, real-model
behavior and vendor attack blocking are not established by this result.
227 unit cases and Ruff checks passed. No AWS or paid inference. Local mock-only
route/proxy and previews remain enabled for review, with no paid fallback.
The CLI diagnostic is separate from the monitor's durable suites. The user
authorized committing and pushing this follow-up on working-edition. Keep main
unchanged and consult Git history for the publication result.


October 23 resumption: see [AWS Trend handoff](AWS_TREND_RESUME.md) and the
[single-copy runbook](../infra/trend-aws/README.md). AWS session and application
health verified; core acceptance is 12/12 with opaque references, browser Inspection
3/3. Mock discovery route remains HTTP 400; paid models stay disabled. The obsolete
$100 validator ceiling is removed and a blank planning amount is supported. No
commit or push is implied by this continuation.
