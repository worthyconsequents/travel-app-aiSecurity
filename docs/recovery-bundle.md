# Recovery bundle before AWS teardown

Recovery preparation does not authorize or perform teardown. On October 23, 2026,
the deployment's encrypted manual RDS snapshot became available. The user selected local-only recovery storage. Capture completed on October 23, 2026: 316 files, 9,116,370 encrypted bytes.
Saved-file decryption/checksum verification and the offline CLI check passed.
The private `latest-recovery-receipt.json` records successful local verification.
No S3 bucket was created and no recovery data was uploaded.

## What is retained

The recovery tool captures source and a Git bundle, deployment configuration,
CloudFormation templates and inventories, Kubernetes resources, Helm values and
manifests, owned Secrets Manager values, Cognito configuration and user metadata,
DNS record metadata, and container image digests. It encrypts the archive locally
using AES-256-GCM and stores ciphertext locally. It does not create an S3 bucket or upload data.
The separate decryption key stays local with owner-only permissions. Copy that key
to a secure location off this computer; losing it makes the archive unrecoverable.

The database contents stay in the encrypted RDS snapshot. Container layers stay
in ECR; the archive contains their digest inventory, not their bytes. Preserve
those repositories and the snapshot's KMS key. This is a recovery set with external
dependencies, not a self-contained archive. CloudWatch event bodies are not
exported; keeping a log group does not override its existing seven-day retention.
Cognito user passwords cannot be exported; restored users need a new sign-in setup.

## Capture and verify

Run from the repository root using the AWS deployment Python environment:

```sh
python -m scripts.trend_recovery capture --env-file PRIVATE_ENV_PATH \
  --snapshot-id OWNED_AVAILABLE_ENCRYPTED_SNAPSHOT --apply --acknowledge-costs
```

Capture verifies account, stack, snapshot and namespace ownership, encrypts locally, re-reads the saved archive, and verifies authenticated
decryption and every file checksum. It performs no S3 operations.
It never creates a snapshot or tears down resources. This capture is local-only; any future export needs separate authorization.

Private artifacts are under `infra/trend-gateway/private/recovery/`. The latest
receipt is under `build/trend-aws/DEPLOYMENT/latest-recovery-receipt.json`; it records
the snapshot, local archive hash, and separate key file path. Keep the
receipt with the archive. Neither keys nor decrypted contents belong in Git.

Offline verification and extraction require no AWS credentials:

```sh
python -m scripts.trend_recovery verify --deployment DEPLOYMENT \
  --archive ARCHIVE_PATH --key-file KEY_PATH
python -m scripts.trend_recovery unpack --deployment DEPLOYMENT \
  --archive ARCHIVE_PATH --key-file KEY_PATH --output NEW_PRIVATE_DIRECTORY
```

## Retention cost estimate

Rates checked October 23, 2026 for us-east-1. These estimates apply after the
running infrastructure is removed; keeping it running still incurs its charges.

| Retained item | Budget basis | Monthly estimate |
| --- | --- | ---: |
| RDS snapshot | 20 GB at $0.095/GB-month | $1.90 |
| Six Secrets Manager secrets | $0.40 per secret-month | $2.40 |
| Existing ECR images | 1.13 GiB summed image sizes at $0.10/GB-month | $0.12 |
| CloudWatch archive allowance | 1 GB at $0.03/GB-month | $0.03 |
| Local recovery archive | Stored on this computer | $0 |
| **Estimated total** | Rounded budget | **about $4.50/month** |

RDS snapshot billing uses actual incremental backup storage, not provisioned DB
capacity; 20 GB is a conservative allowance. No account-wide free backup allocation
is assumed after teardown. ECR summed image sizes can count shared layers more
than once. The archive is stored locally and incurs no S3 charge.
Requests, transfers, tax, extra snapshots, restoration, existing DNS/domain costs,
and running compute/network/database charges are excluded.

Sources: [RDS PostgreSQL pricing](https://aws.amazon.com/rds/postgresql/pricing/),
[Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/),
[ECR pricing](https://aws.amazon.com/ecr/pricing/),
[S3 pricing](https://aws.amazon.com/s3/pricing/), and
[CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/).
Exact regional backup, secret, S3 and log rates were checked with AWS's public
Pricing API. The snapshot uses an AWS-managed KMS key; no new customer-managed
key was created for this backup.

## Recovery procedure and limits

1. Verify and decrypt the archive privately. Recover source from the Git bundle
   and inspect the saved working tree state before choosing a revision.
2. Reconcile retained ECR, secret and other resource names with CloudFormation.
   Fresh stacks can collide with retained names; use reviewed imports or existing
   resource references instead of blindly recreating everything.
3. Rebuild networking, EKS and add-ons from reviewed templates. Restore RDS from
   the saved snapshot into a new compatible DB instance with explicit encryption,
   subnet and security settings. Update the DB endpoint; do not seed/reset its data.
4. Restore secret bindings and generate a fresh kubeconfig. Review Kubernetes
   exports before use: references, PVC bindings and endpoints may be stale. Install
   the supported gateway Helm chart with reviewed values; obtain fresh Trend
   enrollment if required rather than reusing a consumed enrollment token.
5. Recreate Cognito, certificates and the application's DNS record as required.
   Reinvite users and invalidate stale application sessions/grants as appropriate.
   Preserve the existing shared DNS zone and unrelated applications.
6. Recheck Vision One upstreams, access policies, model route and guardrails against
   the new endpoints. Run benign application tests, inspection, and discovery tests.
   Keep Bedrock disabled until separately authorized for deployment and inference.

Archive verification and snapshot availability do not establish a successful
restore drill or a recovery time objective. A restore has not been tested. Database
snapshot and runtime configuration capture are not one atomic point in time.
Historical vendor new-tool quarantine failures remain unresolved acceptance items.

Before any later authorized teardown, preserve the local encrypted archive,
separate key, snapshot/KMS key, ECR images and required secrets. The foundation's
retained live database can continue charging and block VPC deletion after stack
removal; explicitly plan its removal only after verifying recovery prerequisites.

AWS references: [Creating a manual snapshot](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_CreateSnapshot.html)
and [Restoring from a snapshot](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_RestoreFromSnapshot.html).

## Completed teardown

The user subsequently authorized runtime teardown. At October 23, 2026 23:20 UTC,
both deployment stacks were deleted and the final scoped audit confirmed the
runtime/network resources absent. Recovery assets remain intentionally retained.
The newer final snapshot is recorded in [teardown status](aws-teardown-status.md)
and the private companion final audit; the original archive/receipt is unchanged.
The final snapshot adds incremental backup storage to the earlier one-snapshot
retention estimate. No S3 upload occurred and a full restore remains untested.
