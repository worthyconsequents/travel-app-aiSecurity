# AWS Trend gateway status — October 23, 2026

The single-copy boring-travel app is hosted and working for its tested mock paths.
Full security acceptance remains incomplete. All 11 application deployments were
ready at 08:09 PDT; HTTPS certificate verification and Cognito redirect passed.
Runtime components are in AWS; local app services are not required.

| Check | Current result |
|---|---|
| Core synthetic acceptance | 12/12 passed, unchanged bookings |
| Human browser/monitor launch | Inspection 3/3, verified operator attribution |
| Mock model discovery | Baseline + added HTTP 200, provider/backend receipts matched |
| Dynamic catalog/access suite | 10 passed, 1 failed, 2 unavailable |
| Direct gateway new-tool denial | Failed: synthetic new tool executed |
| Application unknown-tool denial | Passed |
| Independent AWS Vision One inventory | Pending |
| Automatic listChanged notifications | Unsupported by current stateless fixture |
| Offline unit tests | 257 passed |
| Paid inference | Disabled; zero calls in recorded tests |

Read [the issue/fix register](aws-deployment-issues.md) for all recorded failures,
fixes, evidence limits and outstanding checks; [the discovery explanation](aws-discovery-explained.md)
shows model/provider/alias linking and the separate MCP execution path.

## Current implementation

Cognito protects public HTTPS; the monitor has a separate password. Secrets Manager
and private Kubernetes mounts supply runtime credentials. The business gateway
retains ownership, scope, expiry and mutation-approval checks. The AWS Trend path
uses an opaque short reference to a private signed grant, resolving the observed
full-token false positive without bypassing backend verification or inspection.
Local and AgentCore profiles retain their existing transport.

A scoped network rule restored Trend control-plane coordination/catalog refresh.
Private credential filename aliases match the four AWS MCP upstreams. The private
LLM listener is enabled for the mock experiment. The exact model routing rule now
selects the AWS mock at weight 1 / 100%, with local mock excluded at weight 0.
The provider/alias name match is incidental: they are separate objects.

## Evidence and boundaries

- [Latest core result](trend-aws-core-reference-results.json)
- [Dynamic tool/access result](trend-aws-dynamic-results.json)
- [Corrected mock route](trend-aws-model-discovery-results.json)
- Historical results: [pre-assignment baseline](trend-aws-test-results.json),
  [guardrail retest](trend-aws-guardrail-results.json),
  [capability comparison](trend-capability-comparison.md),
  [HTTP 400 before route correction](trend-aws-model-discovery-before-route-correction.json)

An earlier core run missed its request-block expectation (11/12); the private
result is retained. Later fixed-probe success does not establish deterministic
classification, general protection or real-model susceptibility. Model requests
here are fixed mock calls. AWS inventory is not verified by HTTP 200 or Events.
The separate historical AgentCore staging test and fleet have different evidence.

## Operations and review boundary

AWS resources remain running and incur charges. The earlier $100 planning ceiling
was withdrawn; no billing-side budget/alert changed. RDS, secrets and logs are
retained; deleting stacks alone does not ensure zero cost or complete cleanup.
Use the [runbook](../infra/trend-aws/README.md) and [handoff](AWS_TREND_RESUME.md).
The user approved publishing the reviewed changes on `working-edition` on October
23. This does not merge main or enable paid inference. Verify the remote commit
after pushing.
