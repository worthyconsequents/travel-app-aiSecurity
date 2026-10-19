# Isolated AWS gateway test deployment

The first live test on 2026-10-18 deployed the security integration in `us-east-1` using the `dannytran-travel-test` prefix. The existing websites remain local at ports 8080 and 8081. The test gateway used an IAM-authenticated MCP endpoint, not a public website or a drop-in deployment of the full application. **The user subsequently requested teardown: all test-created AWS resources are verified removed.** Recorded results below describe the completed test, not a running endpoint.

## Verified results

- 128 offline unit tests passed. cfn-lint 1.57.2 reported no findings for the two staging templates. CloudFormation Guard 3.2.1 passed the project-specific security baseline; this is not a comprehensive compliance certification.
- Unsigned calls were rejected with HTTP 401.
- Signed tool discovery returned exactly one synthetic read-only hotel tool. A benign lookup traversed request inspection, fixture dispatch and response inspection, verified in CloudWatch.
- Malformed tool arguments were rejected with HTTP 400 / `UNSUPPORTED_PAYLOAD`. No probe invocation appeared in that request window.
- Temporarily throttling only the staging inspector caused HTTP 500 with no hotel result and no probe event in the outage request window. Concurrency was restored to two in a finally block; the recovered lookup succeeded and AWS independently confirmed the restored setting.
- **Synthetic injection text was allowed by Trend and reached the read-only fixture. The expected content-blocking check failed.** Review the AI Policy/detections assigned to application `dannytran-travel-test` before claiming attack protection. This test does not establish why the vendor allowed it, or that an LLM would follow the injected instructions.
- 17 gateway requests were made, including initial diagnostics and the controlled outage. No model calls were made. The fixture has no bookings, payment, customer database or model access.

Machine-readable redacted evidence: [aws-cloud-test-verification.json](aws-cloud-test-verification.json). Exact stack IDs, secret ARN and package version are in the ignored deployment manifest under `build/aws-test/<prefix>/<region>/manifest.json`. Do not publish private credential files or this local ledger by default.

## Architecture and constraints

`Local SigV4 test client -> AgentCore Gateway -> request inspection Lambda -> fixed hotel Lambda -> response inspection Lambda -> client`

The inspector uses the same fail-closed handler as the app's AgentCore implementation and reads one dedicated Secrets Manager secret. Its gateway role invokes only the two staging functions. The fixture role writes only its own logs. No Bedrock invocation permission is granted. Both functions have concurrency two, bounded timeouts and seven-day log retention. The artifact bucket is encrypted, private, versioned and rejects non-TLS requests.

The live test exposed and fixed an MCP contract bug: an allowed MCP request/response must explicitly preserve its body. Returning an empty MCP object erased the response in AWS. HTTP/inference has a different pass-through contract. Regression tests now cover body preservation, header exclusion and the offline simulator's treatment of successful response preservation. The running local containers were not recreated by this AWS test.

Names are generated from a deployment prefix supplied at the command line. Use `dannytran-` for this user's deployments; no account ID, personal login or credential is embedded in the scripts/templates. AWS service paths and generated identifiers may add fixed prefixes or suffixes. The two stacks are `<prefix>-artifacts` and `<prefix>`; functions are `<prefix>-inspector` and `<prefix>-probe`, the secret is `<prefix>-aiguard`, and the three roles start with `<prefix>-`.

## Commands for a new authorized test

Authenticate separately with your normal AWS CLI workflow. Python needs the optional CRT dependency when using console-login credentials:

```sh
uv sync --frozen --extra aws-deploy
```

Offline planning and packaging need no AWS credentials and create no resources:

```sh
uv run --frozen --extra aws-deploy python -m scripts.aws_cloud_test plan --name-prefix your-test-prefix --region us-east-1
uv run --frozen --extra aws-deploy python -m scripts.aws_cloud_test package --name-prefix your-test-prefix --region us-east-1
```

Store the detection credential in an ignored owner-only file containing a bare token or JSON with `token`, `apiKey`, or `api_key`. Mixed notes/export files are deliberately rejected. Do not pass a token value on a command line. Confirm the correct regional Trend endpoint and assigned application policy; the script defaults to the US endpoint. Other supported endpoints can be selected with `--ai-guard-url`.

After approving the costs, check one benign live inspection request:

```sh
uv run --frozen --extra aws-deploy python -m scripts.aws_cloud_test check-inspection --name-prefix your-test-prefix --region us-east-1 --key-file /private/path/token.json --apply
```

Deploy after substituting your independently verified 12-digit AWS account ID and a dedicated prefix. These commands incur charges:

```sh
uv run --frozen --extra aws-deploy python -m scripts.aws_cloud_test deploy --name-prefix your-test-prefix --region us-east-1 --profile your-profile --expected-account YOUR_ACCOUNT_ID --key-file /private/path/token.json --apply
uv run --frozen --extra aws-deploy python -m scripts.aws_cloud_test test --name-prefix your-test-prefix --region us-east-1 --profile your-profile --expected-account YOUR_ACCOUNT_ID --apply
uv run --frozen --extra aws-deploy python -m scripts.aws_cloud_test evidence --name-prefix your-test-prefix --region us-east-1 --profile your-profile --expected-account YOUR_ACCOUNT_ID
```

`test` exits with code 2 if a required expectation fails, including an injection that is allowed. This is useful evidence, not a runner success. The optional `outage --apply` action temporarily sets only the recorded staging inspector's concurrency to zero and restores two in a finally block; it requires a working benign baseline first. It still needs operator authorization because it interrupts the test endpoint. If interrupted or restoration fails, independently check and restore that function before resuming traffic.

`update-code --apply` updates only the existing staging package through CloudFormation, retaining template and other parameters. It rejects an account or namespace mismatch. It is intended for reviewed fixes during this test scope, not arbitrary application deployment. `status` reads the local ledger after verifying identity. A saved ledger supports resuming initial creation; existing resources are not silently adopted or credentials overwritten. Do not remove the ledger to force a retry after partial creation: inspect the recorded AWS resources first.

The per-deployment ledger bounds this runner to 100 attempted gateway requests across invocations. This is not an account-wide traffic or dollar cap; run one instance at a time. It does not stop another caller with independently granted IAM access. The endpoint is protected by IAM; no public unauthenticated test endpoint is exposed. Logs contain structured decisions and Lambda invocation IDs, not raw prompts, credentials or vendor reason strings. The `evidence` action reads a bounded number of structured events from the two exact test log groups. Timestamp windows show the serialized test flow; they are not distributed traces for arbitrary concurrent production traffic.

## Costs and resource lifecycle

The user approved a $5 AWS operating allowance for this stage, with no paid model calls. The small bounded test was estimated below $1; actual billing was not queried. AgentCore calls, Lambda, S3, logs and Secrets Manager can incur charges. One secret is listed at $0.40/month, prorated by retention, plus API requests. All test-created resources were removed after the user requested teardown: the gateway/target, both Lambdas and log groups, all three roles, both stacks, the dedicated secret and the artifact bucket including every object version. The secret was deleted without recovery, and its absence was verified. No background traffic generator was started. Charges already incurred can still appear later on the bill; actual billing was not queried. This allowance and request count are not a hard spending cap.

Pricing references: [AgentCore](https://aws.amazon.com/bedrock/agentcore/pricing/), [Lambda](https://aws.amazon.com/lambda/pricing/), [Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/), [S3](https://aws.amazon.com/s3/pricing/), [CloudWatch](https://aws.amazon.com/cloudwatch/pricing/).

## Repeatable teardown after deletion is authorized

The runner now supports exact-manifest cleanup. It verifies the account, deployment namespace, stack/secret ownership tags and artifact bucket's stack ownership before deleting anything. Unexpected stack exports stop cleanup. It never scans a prefix and blindly deletes matches.

```sh
uv run --frozen --extra aws-deploy python -m scripts.aws_cloud_test teardown --name-prefix your-test-prefix --confirm-teardown your-test-prefix --region us-east-1 --profile your-profile --expected-account YOUR_ACCOUNT_ID --apply
uv run --frozen --extra aws-deploy python -m scripts.aws_cloud_test verify-teardown --name-prefix your-test-prefix --region us-east-1 --profile your-profile --expected-account YOUR_ACCOUNT_ID
```

By default, the secret is scheduled for deletion with a seven-day recovery window and the runner reports teardown incomplete until it is absent. Only add `--force-secret-deletion` when permanent removal of that dedicated secret copy is explicitly authorized; the real teardown used this flag. Keep the original credential file private. A pending secret deletion is recorded rather than treated as complete. Preserve the ignored manifest for evidence and safe retries; it contains resource identifiers, not secret values. Use a new prefix for a fresh deployment after teardown.

The completed teardown independently checked both stack records, the gateway, two functions, two log groups, three roles, the bucket and the secret. All checks passed. The final offline suite passed **130 tests** after adding cleanup safety tests; lint and both template/security checks passed. The existing local apps were not stopped.

For manual cleanup or recovery, the required sequence is:


1. Read the exact names/ARNs from this deployment's manifest and verify the account/region. Do not target pre-existing workloads.
2. Delete the test stack and wait for deletion to complete. This removes its gateway/target, two Lambdas, three roles, resource permissions and two log groups. Export redacted evidence first.
3. Delete only the dedicated secret. A scheduled deletion uses a recovery window and must be recorded; do not claim immediate complete deletion while recovery is pending.
4. In the dedicated versioned artifact bucket, remove every object version and delete marker. A simple recursive delete of current objects is insufficient.
5. Delete the empty bucket and artifact stack. The bucket has `DeletionPolicy: Retain`, so deleting that stack alone leaves it behind. Its lifecycle expires current objects after seven days and noncurrent versions after one day; lifecycle is not immediate teardown.
6. Verify absence of the recorded gateway, functions, roles, logs and bucket, and document any retained or pending-delete secret. Keep the local websites and their databases intact.

Full website hosting, production identity, private application MCP endpoints/database, Cedar workload policies and model integration remain separate work. The existing `/monitor` pages do not yet ingest this cloud test ledger or CloudWatch logs.
