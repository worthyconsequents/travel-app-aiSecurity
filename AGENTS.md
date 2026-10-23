# Repository guidance for coding agents

Start with [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) for architecture, current
implementation state, evidence boundaries and the next work. Use
[docs/test-validation-matrix.md](docs/test-validation-matrix.md) for test cases,
commands, recorded results and outstanding acceptance tests.

For the current single-copy AWS Trend continuation, read
[docs/AWS_TREND_RESUME.md](docs/AWS_TREND_RESUME.md) and
[docs/aws-deployment-issues.md](docs/aws-deployment-issues.md).
[docs/AWS_SESSION_HANDOFF.md](docs/AWS_SESSION_HANDOFF.md) records the earlier
local-only stage. Current user instructions govern deployment authorization.
The user approved publishing the current changes to `working-edition` on October
23 after documentation review. Future Bedrock work is a separate implementation
phase; paid model invocation still requires an explicit opt-in. Do not infer future spending or teardown
permission from historical instructions or these files.

## Operational defaults

- Preserve both local implementations: original Compose on port 8080 and the
  separately named offline AgentCore Compose project on port 8081. Deployment
  selection is an operator setting; retain the boring-travel company branding.
- AWS fleet copies are separate applications, not replicas of one application.
  Keep deterministic `dannytran-` names, per-copy data/secrets and exact-secret
  inspector access. Cedar identifiers use underscores because AWS rejects hyphens.
- Keep `.env`, credentials, vendor reference exports, deployment ledgers and build
  outputs private and ignored. Do not print credential values or put them in docs,
  CLI arguments, templates, container build contexts or commits.
- Authenticate to AWS through the operator's normal credential chain. Do not
  embed personal accounts, profiles, login workflows or credentials in tooling.
- Complete offline work first. Obtain current authorization before creating
  billable resources, invoking paid models or performing destructive cleanup.
  Historical approvals and an old test allowance do not authorize a new rollout.
  A script's `--apply`/cost flags do not themselves establish user authorization.
- Never silently delete copies when `DEPLOYMENT_COUNT` decreases, delete the
  shared Trend secret during copy teardown, or overwrite a mismatched stack.
- Report evidence precisely: offline fixtures are not vendor detections or
  real-model susceptibility tests. The historical live Trend injection-blocking
  expectation **failed**. The full AWS fleet has not been cloud-tested.
- Preserve unrelated working changes. Update handoff/testing records when behavior
  or verified status changes; do not rewrite historical reports as new evidence.

## Offline checks

From the repository root, with dependencies installed:

```sh
uv run --frozen --extra aws-deploy python -m pytest -q
uv run --frozen --extra aws-deploy ruff check .
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet plan --env-file infra/aws-fleet/fleet.example.env
```

These commands do not invoke AWS or a model. Dependency installation may download
packages. Container integration, template/security validation and cloud acceptance
have separate prerequisites and evidence scopes described in the test matrix.
