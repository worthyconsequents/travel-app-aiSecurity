# Resume the single-copy AWS Trend deployment

Updated October 23, 2026. Context and evidence do not grant new deployment,
spending, deletion or publication authority. Follow current user instructions.

## Latest user request and review boundary

Document encountered issues/fixes and explain discovery/model routing with diagrams.
The user subsequently approved committing/pushing the current build on October 23.
Keep `working-edition`; do not merge main. Verify the remote commit after pushing.
AWS runtime stays running; no teardown requested. The previous $100 planning ceiling
was withdrawn. Config supports an optional blank planning amount; this is not an
AWS budget or permission for unrelated spending. Paid model inference stays disabled.

## Read first

- [Current issue register/status](aws-deployment-issues.md)
- [Discovery and model linking explained](aws-discovery-explained.md)
- [Deployment runbook](../infra/trend-aws/README.md)
- [Vision One configuration](trend-aws-console-setup.md)
- [Test inventory](test-validation-matrix.md)

Repository: `/Users/dannytran/Documents/ChatGPT/travel-agent-security-demo`.
Namespace/cluster: `dannytran-boring-travel-trend-lab01-01`.
Website: `https://boring-travel.trendcyberrange.com/monitor`.
Credentials, kubeconfig, images and deployment ledgers remain ignored/private.

## Current verified state

- All 11 deployments ready at October 23 08:09 PDT; HTTPS/TLS and Cognito redirect
  pass. Human previously completed Cognito + separate monitor login.
- Human browser-launched Inspection job `73fe40996a13727dff09386d064e7bd4` passed
  3/3 and durable job attribution verified the operator.
- Latest core AWS synthetic suite: 12/12 passed, unchanged bookings, paid calls 0.
  Earlier 11/12 run missed its request block; retained separately. Do not imply
  deterministic/general protection or real-model susceptibility from fixed probes.
- Current AWS capability transport uses short random references. Private PostgreSQL
  stores original HMAC-signed grant under SHA-256(reference); backend resolves it,
  verifies reference/grant expiry, signature and exact tool/arguments. No raw-token
  or direct-MCP fallback. Local and AgentCore modes retain original contracts.
- The earlier custom MCP `_meta` experiment failed closed because this gateway did
  not deliver the authorization metadata. It was replaced, not silently accepted.
- Response probe uses the leased fixed fixture response state; success requires
  backend receipt plus explicit response content-policy rejection. It restores state.
- AWS mock discovery now passes baseline + added phases: HTTP 200, mock-provider
  receipt and backend execution receipt, added phase selects `fixture_new_tool`,
  baseline restored, paid calls 0. User fixed exact requested-model prefix and
  set AWS target weight 1 / 100%, local target weight 0 / excluded. Provider and alias
  share a name but remain separate objects. Individual fix contributions not isolated.
- Dynamic suite: 10 passed, 1 failed, 2 unavailable. Explicit catalog refresh reveals
  add/remove/schema/description changes. Application denies new tool; **direct Trend
  call executes it**, so vendor new-tool ACL denial failed. Fixture restored and
  bookings unchanged. Stateless fixture has no listChanged notification delivery.
- Latest offline suite: 257 passed; ruff and whitespace checks passed.

## Remaining acceptance

1. Human verifies AWS inventory attribution in Vision One Discovered Tools for
   `fixture_status` and `fixture_new_tool`, AWS mock provider/model, around October
   23 08:06 PDT / 15:06 UTC. Tool RPC and HTTP 200 do not verify inventory.
2. Review scoped per-tool/default-denial support for this test identity/upstream.
   Require observed vendor denial with absent backend receipt to fix the failed
   direct new-tool check. Do not weaken the passing application allowlist.
3. Automatic notifications, real-model behavior, live reference tamper/expiry,
   production/fleet readiness and full disaster recovery are not established.
4. Teardown remains staged/manual. RDS, secrets and logs are retained; stack deletion
   alone does not remove all charges and retained RDS can block network deletion.
5. User authorized current branch publication after review. Verify remote commit.
   Documentation changes do not require an image
   rebuild or deployment. Do not restart runtime merely to publish docs.

## Evidence and tool details

Public sanitized docs:
`trend-aws-core-reference-results.json`, `trend-aws-dynamic-results.json`,
`trend-aws-model-discovery-results.json`, `trend-aws-health-verification.json`.
Historical failed snapshots stay separate; see issue register links.
Private `build/trend-aws/<namespace>/` also retains original core miss, browser
attribution, immutable images, rollback sets and deployment ledgers. Prior dynamic
Job expired; a CloudWatch query did not recover its result; a bounded rerun supplied
current evidence. Do not infer a pass from expired/missing logs.

Current Python image digest:
`sha256:75507692e02e484315816fce1875581c26c55cd95952d49cf4fe878f0c27e200`.
Pinned Helm binary: `infra/trend-gateway/private/helm` (not on default PATH).
Gateway chart 0.1.159; virtual-key auth; private MCP 8081 and enabled LLM proxy 8080.
Gateway credential aliases match all AWS upstream names plus mock provider names.
Gateway-only private Kubernetes API egress keeps catalog/lease renewal working.
Secret sync checks selected cluster endpoint and ownership before use; it can read
an existing application virtual key from Secrets Manager without a local key file.

Chrome control was unavailable in this session. Screenshots and operator-provided
fields establish console observations; do not claim automated console inspection.


Next design topic: [Bedrock automation boundaries](bedrock-deployment-option.md).
No real-provider adapter or paid inference is enabled by publishing this build.
