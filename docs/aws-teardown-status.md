# AWS teardown and recovery retention — October 23, 2026

The user explicitly authorized teardown after selecting local-only recovery storage.
Teardown completed at October 23, 2026 16:20 PDT / 23:20 UTC. Both foundation
and add-ons stacks are `DELETE_COMPLETE`. The final scoped audit confirmed no
remaining EKS cluster, active worker instance, live RDS database, ALB/target group,
NAT gateway, VPC, network interface, Elastic IP or application DNS record.
Application workloads were scaled to zero and test scheduling suspended before
infrastructure deletion. The hosted application is offline.

Deployment: `dannytran-boring-travel-trend-lab01-01`, region `us-east-1`.
Only this deployment's verified resources are targeted. The existing shared DNS zone
and unrelated applications are outside the deletion scope. No S3 recovery bucket
was created and no recovery archive was uploaded.

## Recovery assets intentionally retained

- Local AES-256-GCM archive: 316 files, 9,116,370 bytes; saved-file and independent
  offline verification passed. The archive and separate key remain under the ignored
  private recovery folder. Keep the key securely off this computer.
- Original encrypted manual RDS recovery snapshot, plus a final snapshot created
  when deleting the live database. Both are available and encrypted. Preserve the AWS-managed KMS key needed to restore.
- Three ECR repositories: python (9 images), frontend (3), edge (6). No automatic
  image-expiration policy was configured when checked.
- Six deployment-owned Secrets Manager secrets, plus retained application/EKS log
  groups. Logs keep their existing retention periods.

The earlier approximately $4.50/month retention estimate allowed one 20 GB snapshot,
six secrets, images and a small log allowance. The final snapshot adds incremental
backup storage beyond that estimate; actual AWS snapshot storage is usage-dependent.
Retained resources continue charging. Stack deletion is not an all-account cost audit.

Private operation records are in `build/trend-aws/DEPLOYMENT/`: recovery receipt,
teardown inventory (including original templates/resources), removed DNS record,
teardown progress, and `teardown-final-audit.json`. These records are ignored and must not be committed.

See [recovery and restore guide](recovery-bundle.md). Archive verification and available
snapshots do not establish a successful full restore; restore testing remains pending.
A rebuild must reconcile retained resource names, restore RDS into a new instance,
recreate authentication/DNS, and recheck Vision One enrollment/upstreams/policies.
The Bedrock option remains locally implemented and undeployed; no paid inference
was performed for this teardown.

## Cleanup dependencies encountered

The foundation retained its live RDS instance by design. Teardown therefore
explicitly deleted that verified instance with a final snapshot. CloudFormation
attempted DB subnet-group deletion while the instance was still finishing; that
resource reported `DELETE_FAILED`. Once RDS was absent, remaining stack deletion
could be retried without changing retention policies or deleting a snapshot.

The last EKS worker was in `Terminating:Wait` on a 1,800-second termination hook.
After checking the final snapshot, exact EKS ownership, deleting node-group state,
and Auto Scaling minimum/desired capacity zero, the termination lifecycle action
was completed with `CONTINUE`. The node group then disappeared and EKS/NAT removal
proceeded. No application workload was running when that wait was released.

## Final recovery identifiers

- Original snapshot: `dannytran-boring-travel-trend-lab01-01-recovery-20261023-225505`.
- Newest final snapshot: `dannytran-boring-travel-trend-lab01-01-final-20261023-231025`.
- Local recovery directory: `infra/trend-gateway/private/recovery/20261023-230541-2773a3/`.

The archive's original capture manifest and receipt remain unchanged. The companion
final audit records the newer final snapshot and completed teardown. Prefer the
newest compatible snapshot when preparing a reviewed restore. No automatic full
restore was performed. Shared DNS zone access and the snapshot KMS key were
verified intact. This audit covers the recorded deployment in us-east-1, not
unrelated resources elsewhere in the account.
