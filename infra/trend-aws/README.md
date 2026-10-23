# Single-copy boring-travel on AWS with Trend Gateway

This option hosts the web application, monitor, test worker, business gateway,
three MCP services, isolated discovery fixtures and self-hosted TrendAI Gateway
in AWS. It preserves the local Compose and AgentCore deployment options.
Current acceptance and exact deployment evidence:
[issue register](../../docs/aws-deployment-issues.md) ·
[discovery mechanism and diagram](../../docs/aws-discovery-explained.md) ·
[resume handoff](../../docs/AWS_TREND_RESUME.md).

![AWS discovery mechanism](../../docs/architecture/10-aws-discovery-mechanism.png)

Core suite: 12/12; browser Inspection: 3/3; mock discovery: both phases passed.
Full security acceptance is incomplete: direct gateway new-tool denial failed and
AWS inventory attribution is pending. Resources remain running.

## Ownership, credentials and configuration

Use an authenticated AWS SDK/CLI session supplied by the operator. No login flow,
account credentials or personal profile is embedded in the application. Copy
`trend.example.env` to an ignored private environment file and supply the expected
account, Region, operator IAM principal, a narrow operator CIDR, an unused hostname
and its public hosted zone. The deployment name is
`DEPLOYMENT_PREFIX-DEPLOYMENT_ENV-01`; component suffixes identify owned resources.
This option currently supports one copy; the separate AgentCore fleet option has
its own deployment-count implementation.

`AWS_TEST_BUDGET_USD` is an optional planning amount; blank means unspecified. It
neither establishes permission to spend nor creates/enforces an AWS budget. The
current operator withdrew the earlier $100 ceiling. Hosting continues to incur
charges until resources are removed. Paid inference stays disabled.

## Preparation and deployment stages

Run commands from the repository root with the locked project dependencies.
Start with offline preparation, substituting your private environment-file path:

```sh
python -m scripts.trend_aws plan --env-file infra/trend-gateway/private/aws-trend.env
python -m scripts.trend_aws render --env-file infra/trend-gateway/private/aws-trend.env
python -m scripts.trend_aws_bootstrap render-addons --env-file infra/trend-gateway/private/aws-trend.env
python -m scripts.trend_aws_bootstrap gateway-values --env-file infra/trend-gateway/private/aws-trend.env
```

Validate generated CloudFormation with cfn-lint and inspect IAM, networking and
resource ownership before provisioning. `preflight` contacts AWS but makes no
resource changes. Foundation creation explicitly requires both `--apply` and
`--acknowledge-costs` in addition to operator authorization. Never rerun foundation
creation over an existing deployment; inspect `status` instead.

The deployment is staged, **not a one-command finished installer**:

1. Create the foundation: VPC/private nodes, EKS, private encrypted PostgreSQL,
   ECR repositories, generated Secrets Manager secrets, Cognito and certificate.
2. Configure a dedicated kubeconfig for this exact cluster. Provision the addons
   template, Pod Identity, load balancer controller and namespace-scoped logging.
3. Use `scripts.trend_aws_publish` to prepare sanitized contexts and publish immutable
   `linux/amd64` image digests into the three deployment-owned ECR repositories.
   Keep private files and reference exports outside every build context.
4. Synchronize generated credentials with `trend_aws_bootstrap sync-secrets --apply`.
   The helper verifies the Kubernetes endpoint and secret ownership first. It can
   restore the application virtual key from Secrets Manager without a local copy.
5. Install the vendored Trend chart with a fresh private enrollment package and the
   generated values. A consumed enrollment token cannot be reused. The application
   virtual key is a separate credential. No auth bypass is needed.
6. Render and review the app manifests with `render-app --images-file <images.json>`;
   bind the exact ALB ARN when available. Apply the private services, bounded worker,
   network policies, HTTPS ingress and verified Cognito edge configuration.
7. Wait for healthy targets and the issued certificate. Create a new DNS alias only
   after checking ownership and that the hostname is unused. Do not overwrite an
   existing application record. Invite the operator through the deployment's pool.
8. Follow [Vision One setup](../../docs/trend-aws-console-setup.md) for private MCP
   upstreams, service-identity access, blocking guardrails and mock-only model route.

Public HTTPS is restricted to the configured operator CIDR. The gateway listeners,
MCP endpoints, database and mock provider have no public ingress. Rotating operator
IP addresses requires an explicit scoped configuration update, not opening access.

## Runtime and test acceptance

Open the deployment hostname and complete Cognito sign-in. `/monitor` additionally
requires its separate password stored in the deployment-owned Secrets Manager secret.
The test launcher submits bounded durable jobs; workers run inside AWS and require
no local tunnel, browser session or local containers to execute. The operator
computer is used only for administration/building, not runtime hosting.

Keep these findings separate:

- Core tests: catalog contract, benign requests, application authorization denials,
  request/response inspection and unchanged business data.
- Dynamic tools: explicit refresh/addition/removal/schema drift, unknown-tool denial
  and backend receipts. Stateless fixture notification support is a separate check.
- Model discovery: exact mock route, baseline/added submitted definitions, provider
  receipt and MCP execution receipt. HTTP 200 alone is insufficient.
- Vision One inventory: independently confirm the new AWS provider/tool in the
  console. Tool-call logs do not by themselves establish inventory population.

The latest core suite passed 12/12, and the human browser-launched Inspection job
passed 3/3. A prior core run missed one request-block expectation and remains in the
private evidence set. The corrected mock route passed baseline/added-tool phases with independent
provider/backend receipts on October 23; Vision One inventory is not yet verified.
No paid model behavior is tested or enabled. Historical full-capability false
positives are documented separately; the current AWS transport uses short grant
references while retaining signature, expiry and argument-scope enforcement.

## Recovery, rotation and cleanup

Keep generated image digests and rollback manifests private under `build/trend-aws/`.
Never reset the database to recover a deployment or rotate credentials merely
because a pod restarts. Reconcile only resources belonging to the exact deployment.
After intentional key rotation, update Secrets Manager, synchronize Kubernetes
secrets and verify dependent clients reload the changed file. Never print keys.

There is no completed automated full-stack teardown runner for this option.
Cleanup must inventory the exact deployment and remove ingress/DNS dependencies,
services, nodes/addons and stacks in dependency order. **RDS, secrets and log groups
are retained**; deleting stacks alone does not stop all charges and retained RDS
can prevent network deletion. Separately review databases/snapshots, NAT/EIPs,
ALBs, ECR images, logs and retained secrets. Preserve shared resources and unrelated
Vision One identities/providers. No cleanup is implied by reducing a count or
by finishing a test. Request explicit operator authorization for teardown.
