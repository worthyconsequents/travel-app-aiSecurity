# Consolidating the second deployment working directory

On October 23, 2026, the operator supplied the `boringTravelApp-working-edition_dtrantmemu`
working-directory export and requested consolidation into `working-edition`.
The export has no `.git` history, so this is a reviewed content integration, not
an automatic merge of two histories. It had 18 differing public source/documentation
files against this checkout, no additional public source files, and none of this
checkout's four new recovery/teardown files. Private/vendor/build directories,
credentials, local environments and dependency caches were excluded.

## Decisions

| Area | Source difference | Consolidated behavior |
| --- | --- | --- |
| Naming | Additional `boring-travel-bedrock-dtran` prefix in five independent regexes | One shared naming contract supports the original and imported prefix; full single-copy namespaces still require a valid environment, `-01`, and the 43-character limit |
| Bedrock Kubernetes manifest | Adapter Deployment used core `v1` | Corrected to `apps/v1`; regression asserts the API version |
| ALB authentication | Long names are compacted and lose the literal `dannytran-` prefix | Validate ARN structure/Region, then continue verifying JWT signatures against the exact configured signer, issuer and client; wrong signers still fail |
| Public website | One CIDR opened both ALB and EKS to `0.0.0.0/0` | New `DEPLOYMENT_PUBLIC_WEB=true` opens website HTTPS only; default remains false and EKS administration still requires an IPv4 `/24` or narrower operator CIDR |
| Guard validation | Removed public-control-plane restriction and checked only an ingress port | Retain private control-plane/database checks; require explicit public-web metadata and TCP port 443; reject public IPv6. Six rule tests include negative cases |
| Corporate build CA | Optional Docker COPY glob and broad `.crt` packaging | Optional BuildKit secret mount for Node build steps; no trust certificate copied into image layers or packaged contexts; private keys refused by the publisher |
| Operational history | Export describes another live deployment; original checkout has verified teardown/recovery | Preserve both scopes with explicit evidence labels; never overwrite the confirmed original teardown with an imported running-state claim |

Neither input's private files were imported. No API key, enrollment token, virtual
key, Cognito credential, `.env`, kubeconfig, recovery key, deployment ledger or
machine certificate belongs in this commit. Existing recovery material stays
ignored and local. The supplied directory is unchanged.

## What the export reports, and what remains unverified

The source README reports a second deployment named
`boring-travel-bedrock-dtran-demo01-01`, at
`https://boring-travel.boringpapercompany.com/`, using `amazon.nova-micro-v1:0`.
It reports one benign, tool-grounded hotel chat working through Trend and Bedrock.
These are imported observations, not a new live verification by this consolidation.
Current health, independent account/Region isolation and attack behavior have not
been checked here. The source's public EKS configuration is not reproduced by the
consolidated default or public-web option.

The source also reports a Vision One console issue where a saved platform-secret
path lost its final character, and a temporary extra-character workaround. That
behavior was not reproduced or verified here and must not be treated as universal
vendor behavior. Reopen the saved field and compare it to the exact mounted file
path before changing anything; do not append characters blindly. This merge does
not change Vision One configuration.

The original `dannytran-boring-travel-trend-lab01-01` deployment was independently
verified torn down. Its local encrypted archive, two available encrypted snapshots,
ECR images, secrets and logs remain intentionally retained. See
[teardown status](aws-teardown-status.md) and [recovery guide](recovery-bundle.md).
The other account/deployment was not contacted or modified by this consolidation.

## Public web and optional build CA

In a private Trend AWS configuration file:

```dotenv
DEPLOYMENT_ALLOWED_CIDR=203.0.113.1/32
DEPLOYMENT_PUBLIC_WEB=true
```

This changes generated website ingress only. Cognito and the exact ALB-token checks
still gate application access. It does not create WAF, harden a public demonstration
for production, allow public MCP/DB access, or open EKS administration. Configuration
rendering is offline; deployment still requires a separate authorized operation.

For builders behind a corporate TLS proxy, supply a public PEM CA from outside the
repository using Docker's [BuildKit secret support](https://docs.docker.com/build/building/secrets/):

```sh
docker buildx build --secret id=corporate_ca,src=/absolute/private/path/public-ca.pem \
  --file frontend/Dockerfile .
```

When using the authorized image-publishing workflow, its frontend `publish` command
accepts `--build-ca-file /absolute/private/path/public-ca.pem`. That command writes
ECR/build state and is not a local-only test. The CA is optional; ordinary builds
need no extra file. No local CA was imported from the supplied build. A daemon or
base-image pull may require separate host trust configuration; this mount applies
only to the Node build steps.

## Validation and boundaries

The consolidated offline suite passes 310 tests. Lint passes. Both restricted and
public-web foundation/Bedrock template variants pass local cfn-lint, and foundation
Guard checks pass. Six Guard scenarios verify opt-in public HTTPS and reject
unapproved world ingress, SSH, public EKS, public RDS, and unreviewed IPv6.
The frontend Dockerfile passes Docker BuildKit `--check` with a sanitized context;
this is build validation, not a completed image build or browser acceptance test.

New Python regressions cover both naming families across runtime gates/transport,
exact cross-deployment rejection, shortened ALB signer validation, API version,
separate website/admin CIDRs, strict option parsing, certificate exclusion from
image contexts, optional CA mounts, and private-key rejection. Recovery encryption
and offline integrity checks remain covered. No AWS mutation, paid model invocation,
application-container startup or independent second-deployment acceptance test was
performed during consolidation.

Before commit, a staged-file scan checked credential/token formats, private PEM
keys, literal JWTs, credential assignments and prohibited private paths. No findings
were reported across the 33 staged files. Git ignore checks confirmed recovery keys,
private deployment files, local environments and the optional machine CA remain
untracked. Pattern scanning is an additional check, not proof that every possible
secret format is detectable; reviewed import scope is the primary control.

Repeat the Guard regressions with:

```sh
cfn-guard test -r infra/trend-aws/foundation.guard \
  -t infra/trend-aws/foundation.guard.tests.json
```
