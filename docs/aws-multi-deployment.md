# Isolated AWS application deployments

This option builds **X independent AWS copies of the whole application**, driven by `.env`.
Each copy gets its own HTTPS URL, Cognito operator login, VPC, private Fargate task,
PostgreSQL database, application secrets, AgentCore gateways, inspection Lambda and logs.
All inspection Lambdas read **one existing Trend AI Guard detection secret** through
their own narrowly scoped IAM roles. The browser, application task role and gateway
roles have no permission to read that shared credential.

**Status:** implemented and tested offline. This fleet has not been deployed or
verified in an AWS account. CloudFormation schema checks cannot prove regional
feature availability, runtime integration or successful attack detection.
See the [offline verification record](aws-fleet-offline-verification.json).

![Approved separation and shared-key design](architecture/04-aws-multi-deployment.png)

The illustration shows the separation model. The concrete hosting implementation
uses one ECS Fargate task containing the app's containers in each copy, an encrypted
RDS PostgreSQL database, two HTTPS ALBs, one NAT gateway and native private MCP
targets through managed VPC Lattice. Containers within a copy share a task IAM role
and network trust boundary; the inspection Lambda runs separately. Copies are
isolated within **one AWS account**, not separate account security boundaries.

## Configuration and names

Add the AWS settings from `.env.example` to your ignored local `.env`. Keep that
file private. Use `AI_GUARD_SECRET_ARN` for a **secret reference**, never the API key.
The existing secret must contain the detection token as plain text or JSON such as
`{"token":"..."}`. A Vision One tenant API key or gateway enrollment token is not
interchangeable with a working AI Guard detection credential.

```dotenv
DEPLOYMENT_TARGET=aws
DEPLOYMENT_PREFIX=dannytran-travel
DEPLOYMENT_ENV=lab01
DEPLOYMENT_COUNT=3
AWS_REGION=us-east-1
AWS_EXPECTED_ACCOUNT_ID=YOUR_ACCOUNT_ID
AI_GUARD_SECRET_ARN=YOUR_EXISTING_SECRET_ARN
ENABLE_PAID_INFERENCE=false
```

| Resource scope | Example |
|---|---|
| Shared artifacts and image repositories | `dannytran-travel-lab01-shared` |
| Copy 1 hosting | `dannytran-travel-lab01-01` |
| Copy 1 AgentCore | `dannytran-travel-lab01-01-agentcore` |
| Copy 2 hosting | `dannytran-travel-lab01-02` |
| Copy 1 monitoring password | `dannytran-travel-lab01-01-monitor` |
| Copy 1 website | `https://dannytran-travel-lab01-01.YOUR_DOMAIN` |
| Copy 1 private MCP alias | `dannytran-travel-lab01-01-mcp.YOUR_DOMAIN` |

Count accepts 1–20. Increasing it adds copies; reducing it **never deletes** existing
copies. Existing indices keep their names. Use a new environment slug for a new
configuration, image revision or model setting. The tool refuses to overwrite an
existing stack with a changed blueprint. Its only automatic stack update binds
gateway endpoints after the private application has started. Concurrent local
operations for the same fleet are refused.

ALB and S3 names are shortened with deterministic hashes to meet AWS limits while
retaining the `dannytran-` prefix. Cedar engine/policy names use `dannytran_` because
AWS prohibits hyphens in those names. Tool target names also include the copy prefix;
the application maps them back to canonical tool names.

## Preview without AWS access

From the repository root:

```sh
uv sync --frozen --extra aws-deploy
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet plan --env-file .env
```

`plan` never creates AWS clients, even if credentials are available. To inspect all
templates using fictitious offline references:

```sh
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet render --env-file infra/aws-fleet/fleet.example.env
cfn-lint build/aws-fleet/rendered/dannytran-travel-lab01/*.json
cfn-guard validate -d build/aws-fleet/rendered/dannytran-travel-lab01 -r infra/aws-fleet/fleet.guard
```

`render` also makes no AWS calls. Generated AgentCore templates expose hosting and
artifact references as parameters for review. The deploy command fills these from
the stacks it creates. The fictitious example file is not deployable infrastructure.

## Prepare for a real deployment

The operator signs in to AWS separately with their chosen CLI/SSO/login method.
The script uses the normal credential chain or `--profile PROFILE`; it does not
contain an account-specific login workflow. Install Docker with amd64 build support
before publishing images.

Supply these references in your local `.env`:

- `AWS_EXPECTED_ACCOUNT_ID`: explicit target account. The script checks STS before writes.
- `DEPLOYMENT_DOMAIN` and `DEPLOYMENT_HOSTED_ZONE_ID`: a public Route 53 zone containing
  that domain, with working delegation. The private MCP alias resolves to internal
  ALB addresses; it does not expose an internet service.
- `DEPLOYMENT_CERTIFICATE_ARN`: an issued ACM certificate in the deployment Region
  covering `*.DEPLOYMENT_DOMAIN`. Certificate/domain registration is not automated.
- `DEPLOYMENT_ALLOWED_CIDR`: your operator public IPv4 `/32`, or trusted subnet of
  `/24` or narrower. Public HTTPS access is also gated by Cognito login. There is no
  public HTTP listener, database ingress or task address.
- `AI_GUARD_SECRET_ARN`: one existing active secret in that account and Region.
  If it uses a customer-managed key, supply its exact `AI_GUARD_SECRET_KMS_ARN` and
  permit the inspector roles in the key policy. The deploy script reads secret
  metadata, never the detection token.

Ensure the operator can create the generated CloudFormation resources, pass the
generated roles, use the selected ECR repositories and artifact bucket, and provision
the AgentCore Gateway networking service-linked role. Policy creation/validation
also needs the documented Gateway invocation permission. Verify AgentCore inference,
Policy and managed VPC egress support and quotas in the chosen Region. Confirm RDS
PostgreSQL 17.11 and two availability zones are available there before deployment.
An existing account CloudTrail should record control-plane activity; this option
does not create a duplicate account trail.

**Cost approval comes before these commands.** Each copy runs Fargate, RDS, two
ALBs, NAT, public IPv4 addresses, logs, secrets and Lattice resources. These cost
money while idle. The count and acknowledgement flag are not spending limits.
Review the rendered inventory and current regional prices before starting with one copy.

```sh
# Creates only the shared artifact bucket and three retained ECR repositories.
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet foundation --env-file .env --apply --acknowledge-costs

# Builds sanitized local contexts for linux/amd64, then pushes immutable ECR images.
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet publish-images --env-file .env --apply --acknowledge-costs
```

Copy the three printed `AWS_*_IMAGE` digest references into `.env`. Tags are not
accepted for deployment. Build contexts exclude `.env*`, key files, symlinks, build
outputs, vendor reference directories and dependency caches. Build/push failures
stop the command; successfully published immutable images are reused on retries.

```sh
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet deploy --env-file .env --apply --acknowledge-costs
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet status --env-file .env
```

The deployment order is shared foundation → copy hosting → AgentCore targets and
policy → bind app gateway endpoints. It runs copies serially and saves account,
Region, stack IDs and outputs under ignored `build/aws-fleet/`. Failures stop the
batch. Re-running the same settings discovers owned stacks and resumes completed
phases. Stacks in rollback/failure state require inspection and explicit teardown
or remediation; retries do not silently replace them. A completed stack is marked
`DEPLOYED_UNTESTED`, rather than claiming that application tests passed.

## Operator access and application testing

Use the output `UserPoolId` to invite an operator using Cognito's administrator
workflow. Self-registration is disabled. Each copy has its own pool; invite the
operator to each copy they should access. Do not put passwords on command lines.
Open that copy's URL, complete login, then select one of the synthetic travel
personas. Those personas exercise business authorization scenarios; they are not
production customer accounts or a mapping of Cognito groups to traveler roles.

Retrieve the copy's `MonitorSecretArn` through the Secrets Manager console when
needed. Its generated JSON `password` unlocks `/monitor` after the Cognito login.
Passwords, signing keys, ingress keys and database passwords are independently
generated per copy. Rotating injected app secrets requires restarting ECS tasks;
database password rotation additionally requires updating RDS consistently.

Start with paid inference disabled. The chatbot uses the deterministic planner,
while tool requests go through the **real** AgentCore tool gateway and Trend
inspection. There is no paid model target or model invocation permission by default.
Cedar permits only five read tools; mutations, refunds and bulk records default
to deny, even if the local reference application allows an action.

For each copy, test login, stay search, hotel details, own trips, another traveler's
booking denial and monitor access. Verify unsigned direct gateway requests fail,
private MCP ingress rejects missing/wrong service keys, and MCP tools reject
missing/tampered/expired capabilities. Verify a session or monitoring cookie from
copy 1 fails in copy 2. Review `/monitor` for app activity and the copy's CloudWatch
inspector log group for independent request/response decisions. CloudWatch entries
are not ingested into the app monitor; correlate time, copy and Lambda invocation
IDs. The monitor's automated attack runner remains local-only and refuses cloud runs.

Before claiming live content blocking, verify an assigned Trend blocking policy
using benign, synthetic attack and inspection-outage cases. The earlier isolated
AWS test established connectivity/fail-closed behavior, but **Trend allowed its
synthetic injection**. This fleet does not resolve or hide that detection outcome.

For an approved paid-model trial, use a new environment, set
`ENABLE_PAID_INFERENCE=true`, choose a Messages-compatible Mantle model as
`AGENTCORE_MODEL_ID=bedrock-mantle/MODEL`, and set
`AGENTCORE_MANTLE_PROJECT_ARN=arn:aws:bedrock-mantle:REGION:ACCOUNT:project/default`.
The optional gateway role permits only `CreateInference` in that project with a
model condition; the interceptor also requires the configured model, buffered
requests and a maximum of 512 output tokens. The app's bounded tool loop uses 400
tokens per call. These are request bounds, not an aggregate budget. Model access,
regional availability and a real end-to-end inference test remain to be verified.

## Shared-key impact and teardown

The key is a shared dependency. Revoking it affects all copies. Inspectors cache it
for up to five minutes, so rotation may overlap briefly. Unique application names
provide attribution; they do not give separate tenant credentials or quotas. A
compromised inspector could expose that same vendor credential. AWS data and
application passwords remain scoped to the separate copies.

Teardown always selects one index and requires its exact name:

```sh
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet teardown --env-file .env --instance 2 --confirm dannytran-travel-lab01-02 --apply --acknowledge-costs
```

This deletes that copy's AgentCore stack before its hosting stack. RDS is snapshotted
before its instance/network are removed; generated application secrets and log groups
are retained. The manifest/output lists those retained billable resources and
snapshots for explicit review and cleanup. **Teardown is not a zero-cost guarantee.**
Other copies, the shared foundation and the external Trend secret are preserved.
Shared artifact buckets and ECR images also retain data. There is deliberately no
batch/shared-secret purge command. Review retained resources before reusing a
deleted copy's name, since retained Secrets Manager names will conflict.

## Source references

- [AgentCore managed private VPC egress](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-vpc-egress.html)
- [AgentCore inference connector and IAM outbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-inference-connector.html)
- [Exact-secret IAM permissions](https://docs.aws.amazon.com/secretsmanager/latest/userguide/auth-and-access_iam-policies.html)
- [Mantle project and model authorization](https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam-projects.html)
- [RDS PostgreSQL release calendar](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-release-calendar.html)
