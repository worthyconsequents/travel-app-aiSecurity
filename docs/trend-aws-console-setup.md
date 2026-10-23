# Vision One setup for the AWS boring-travel test

This guide configures only the new AWS test resources. It does not authorize changes
to existing identities, guardrails, local upstreams or paid-model routes.

The gateway deployment name is `dannytran-boring-travel-trend-lab01-01`.
The enrollment package registers the gateway; it is not the application's virtual key.

## Application identity and virtual key

Create an application/service identity for this AWS test, then an application virtual
key for gateway requests. Keep it separate from the gateway enrollment token, a
Vision One tenant API key and the AI Guard detection token used by AgentCore.
Save the downloaded/raw virtual key privately as:

`infra/trend-gateway/private/aws-travel-virtual-key`

Use owner-only file permissions. Do not paste the value into chat, a command line,
Git, a screenshot or a routing-rule field. Deployment copies it into the private
AWS runtime; the running app does not read files from the developer's computer.

## Private MCP upstreams

Add these HTTP upstreams to the AWS gateway's configuration. The names are exact
because the reviewed application mapping includes their namespaced tool names.
All URLs are AWS-internal Kubernetes services, not public website endpoints.

| Upstream name | URL |
| --- | --- |
| `dannytran-boring-travel-trend-lab01-01-discovery` | `http://mcp-bridge.dannytran-boring-travel-trend-lab01-01.svc.cluster.local:8082/travel-discovery/mcp` |
| `dannytran-boring-travel-trend-lab01-01-reservations` | `http://mcp-bridge.dannytran-boring-travel-trend-lab01-01.svc.cluster.local:8082/reservations/mcp` |
| `dannytran-boring-travel-trend-lab01-01-payments` | `http://mcp-bridge.dannytran-boring-travel-trend-lab01-01.svc.cluster.local:8082/customer-payments/mcp` |
| `dannytran-boring-travel-trend-lab01-01-tool-changes` | `http://tool-change-fixture:8000/mcp/` |

For each upstream, configure the file-backed API-key credential to send header
`X-MCP-Service-Key`, reading `/etc/secrets/gateway/mcp-boring-travel` in the AWS
gateway. The deployer generates and mounts that secret; the operator does not
need to copy its value. Do not substitute the enrollment token or virtual key.

The current AWS test also mounts that same upstream credential under each complete
upstream name, for example
`/etc/secrets/gateway/dannytran-boring-travel-trend-lab01-01-discovery`.
These four aliases match the operator's saved console configuration. Keep this
mapping in `scripts/trend_aws_bootstrap.py` when resynchronizing credentials.
A gateway reload may be needed after adding missing credential files to retry
upstream clients that previously failed initialization.

A console import/Discover tools action is separate from the gateway's actual
`tools/list` runtime path. If console import fails, record it rather than exposing
these services publicly or disabling authentication. The previous local preview
had a file-context mismatch in that separate console operation.

## Mock-only model discovery route

When ready for the separately bounded discovery experiment:

- OpenAI provider name: `dannytran-boring-travel-trend-lab01-01-mock`.
- Base URL: `http://mock-model-provider:8000`, without `/v1`.
- File-backed provider credential: `/etc/secrets/gateway/mock-boring-travel`.
- Manually add model `dannytran-mock-model`; this is an inert fixture, not paid inference.
- Attach it to alias `dannytran-boring-travel-trend-lab01-01-mock`.
- Exact requested-model routing match:
  `dannytran-boring-travel-trend-lab01-01-discovery-probe`.
- Target only the mock alias. No wildcard, real model or fallback provider.

The deployer will explicitly enable the private LLM proxy for this experiment.
MCP-derived definitions must be submitted in the model request to repeat the
verified local discovery path. Inventory observation, actual tool execution,
application authorization and vendor blocking are separate findings.

## Inspection and access scope

Authorize the new application identity only for the AWS test's registered resources.
Apply a reviewed blocking inspection assignment to the new identity/upstreams for
vendor inspection tests. Preserve the existing content policy and other assignments.
Do not disable the signed capability checks or inspection to make a test pass.

The current AWS app uses opaque capability references to resolve the observed
full-token false positive; backend signature/scope/expiry checks remain enabled.
Current core request and response probes pass. Local full-token historical results
are recorded separately; AWS gateway per-tool denial still needs remediation.

## Corrected model route and remaining access check

The October 23 saved rule uses the complete exact requested-model string above,
AWS mock weight 1 / 100%, local mock weight 0 / excluded, and no fallback alias.
Both baseline and added phases passed with HTTP 200 and independent provider/backend
receipts after correction. The prior screenshot had a missing leading `d` and
AWS/local models at 50/50; the contribution of each correction was not isolated.

Runtime readiness and credential-file presence alone do not prove the model route.
Ensure the alias contains the provider/model association and check the per-model
weights in the rule. See [the illustrated explanation](aws-discovery-explained.md)
for why provider, model, alias, requested-model label and MCP upstream are separate.

The dynamic-tool run observed new tools through explicit `tools/list` refresh.
Application authorization denied `fixture_new_tool`, but a direct Trend call
executed it on the isolated fixture. Review access rules scoped only to
`dannytran-boring-travel-aws-test` and the AWS `-tool-changes` upstream. Determine
whether this preview supports explicit reviewed tool grants/default denial of new
tools. If unavailable, record the limitation and retain application approval.
Require observed vendor denial and no backend receipt before claiming a fix.

Independently check Vision One Discovered Tools for both fixture tools with AWS
provider/model attribution around October 23 08:06 PDT / 15:06 UTC. Earlier local
inventory entries and generic Events are insufficient. Current code deliberately
reports `inventory_verified=false` pending that observation.

[Current issue register](aws-deployment-issues.md) ·
[Passing model-route evidence](trend-aws-model-discovery-results.json) ·
[Dynamic access failure evidence](trend-aws-dynamic-results.json)
