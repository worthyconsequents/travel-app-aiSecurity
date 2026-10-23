# AWS deployment status and issue register

Reviewed October 23, 2026. **The hosted application and bounded mock-discovery
flow are working. Full security acceptance is incomplete.** This report covers the
recorded local-discovery investigation and current single-copy AWS Trend deployment;
the separate AgentCore staging experiment/fleet retains its own historical reports.
The operator subsequently approved publishing the reviewed build to the
`working-edition` branch on October 23. Paid inference remains disabled.

## Subsequent Bedrock option build

A private IAM-backed Bedrock adapter, bounded read-only chat loop, guarded add-on
deployment commands and [LLM guide](LLM_GUIDE.md) have been implemented locally.
They have not been deployed, exercised with a real model or used to change the
running AWS mock environment. [Runbook and scope](bedrock-deployment-option.md).
The historical/current AWS test records below still describe the mock deployment.

## Current verification

| Area | Result | Evidence / limit |
|---|---|---|
| AWS runtime | All 11 deployments ready at 08:09 PDT, October 23 | [Read-only readiness snapshot](trend-aws-health-verification.json); not a load or availability guarantee |
| Public HTTPS | Certificate verified; `/monitor` redirects to Cognito (302) | Fresh unauthenticated check; human previously completed login |
| Monitor browser launcher | Inspection 3/3 passed | Durable run `73fe40996a13727dff09386d064e7bd4`, verified operator attribution |
| Core AWS synthetic suite | 12/12 passed, business data unchanged | [Current reference-transport result](trend-aws-core-reference-results.json); an earlier missed request block is preserved |
| AWS mock-model discovery flow | Baseline and added phases passed | [HTTP 200 + provider/backend receipts](trend-aws-model-discovery-results.json); fixture restored |
| Dynamic catalog and security suite | 10 passed, 1 failed, 2 unavailable | [Result](trend-aws-dynamic-results.json); vendor new-tool denial failed |
| Independent AWS Discovered Tools inventory | Pending human verification | Existing local entries do not establish AWS attribution |
| Paid LLM use | Disabled; zero calls in recorded suites | Inert mock response; real-model reasoning/susceptibility untested |
| Offline regression suite | 257 passed | Last completed full unit run; ruff and diff-whitespace checks passed |

Runtime hosting is AWS-only. Local files support administration/building, not live
serving. Resources remain running and incur hosting charges. The operator withdrew
the previous $100 ceiling; no AWS billing alert or hard cap was created or changed.

## Resolved issues and investigation findings

| ID | Symptom / issue | Cause or evidence | Resolution and verification |
|---|---|---|---|
| R01 | Earlier command-permission approval reviews timed out | Client command-approval layer; no evidence it was an AWS service error or application component | Later authorized commands ran; no infrastructure workaround bypass was added. Exact review timeout cause was not established |
| R02 | AWS session expired during earlier work | Missing/expired operator session; authentication is external to deployment code | Operator signed in through normal AWS workflow; current account identity verified. No embedded login or credentials |
| R03 | Enrollment token/tenant API key mistaken for app request key | Enrollment, tenant management, AI Guard detection and gateway virtual keys have different roles | Dedicated service identity and virtual key; missing/invalid key tests returned 401 and valid key initialized MCP |
| R04 | User's downloaded virtual-key file was RTF | Formatting container was not a raw token file | Converted privately with explicit RTF handling, owner-only permissions; key never printed |
| R05 | NGINX services failed with read-only root filesystem | Default fastcgi/uwsgi/scgi temporary directories were unwritable | All temporary paths use `/tmp`; root stays read-only; services ready |
| R06 | Worker jobs failed before database schema existed | Initialization ordering | API normal initialization creates required tables before acceptance jobs; no database reset |
| R07 | New virtual key returned 401 despite configuration | Gateway coordination/catalog was stale while Kubernetes API access was blocked | Gateway-only TCP 443 egress to private control-plane subnets and Kubernetes Service IP; lease/catalog renewal and accepted key observed |
| R08 | Private MCP upstream client initialization failed | Console credential paths used full upstream names; matching mounted filenames were missing | Project same upstream key under four exact names plus generic alias; reload initialized clients; reviewed business schemas observed |
| R09 | Historical local upstreams appeared as failed in AWS gateway logs | Global catalog retains local entries whose private files/endpoints are absent in AWS | Preserve local entries; validate only AWS-owned upstreams. Do not copy unrelated local keys or treat old log failures as AWS app failure |
| R10 | Injection initially was not content-blocked | New AWS identity/upstreams did not yet have the intended scoped guardrail assignment | Operator added assignment; subsequent fixed request probe blocked. Earlier failed result retained |
| R11 | Benign signed booking/search requests then content-blocked | Eight-case comparison associated false positives with full encoded capability values; precise classifier internals unknown | Short opaque reference in AWS tool argument, hashed lookup to private signed grant; backend retains signature/scope/expiry verification. Current benign/core tests pass |
| R12 | Custom MCP `_meta` transport failed | SDK round trip worked locally, but this gateway did not deliver custom authorization metadata to backend | Experiment failed closed and was replaced with opaque references. No unsigned or raw-token fallback |
| R13 | Response-inspection case unavailable | No suitable controlled response probe existed | Added leased fixed response fixture; requires backend receipt plus explicit response-policy rejection; current case passes and fixture restores |
| R14 | Earlier full run missed expected request block (11/12) | Reproducibility/cause not established; later direct and full runs blocked the fixed probe | Preserve earlier result; latest core run 12/12. Do not claim deterministic or universal protection |
| R15 | Direct MCP Events existed while local Discovered Tools stayed empty | Events and inventory are separate observations; exact vendor feed implementation not established | Local model request carrying MCP definitions populated inventory; AWS route and execution later passed. AWS inventory still awaits human confirmation |
| R16 | Console Discover/import failed with credential-file lookup errors | Gateway-local secret file existed, but separate console discovery context could not resolve it; exact backend cause unconfirmed | Used authenticated runtime MCP refresh for the diagnostic. Console import path remains a historical unresolved observation, not an AWS exposure workaround |
| R17 | Local mock route originally returned 404 | Provider URL path composition | Provider root URL omits `/v1`; API path is appended. Fixed local flow passed; AWS uses same root convention |
| R18 | AWS mock route returned HTTP 400, no upstreams configured | Screenshot showed requested-model typo and AWS/local candidates at 50/50; earlier suspected missing linkage was not proven | Saved exact `dannytran-...-discovery-probe` match; AWS weight 1 / 100%, local weight 0. Both phases passed afterward. Individual contribution of each change was not isolated |
| R19 | Mock provider key filename uncertainty | Provider credential filename aliases differed in setup | Mounted generic and AWS-specific filenames, checked presence privately; no values printed. Do not attribute the HTTP 400 solely to this suspicion |
| R20 | Prior diagnostic job result missing on resume | Kubernetes job expired; CloudWatch query did not recover final result | One bounded dynamic rerun produced preserved 13-case evidence; no pass inferred from missing logs |
| R21 | Chrome inspection attempts unavailable | This chat had no callable Chrome control; open-tab context exposed URL only | Used operator screenshots and supplied event fields. Independent console verification remains a human step |
| R22 | Old $100 validator conflicted with latest instruction | Planning guard hardcoded earlier approval ceiling | Optional positive planning amount or blank; actual config blank. Negative/zero/NaN rejected; no billing-side mutation |
| R23 | Secret recovery needed to work without developer files | AWS runtime must not depend on a local key file | Sync can read deployment-owned Secrets Manager key; cluster endpoint/secret ownership checks precede use. Unit checks cover mismatched cluster and ownership; live disaster recovery is not claimed |

## Outstanding issues and limitations

| ID | Finding | Next acceptance step |
|---|---|---|
| O01 | **Direct Trend call executed the newly added fixture tool**; application allowlist rejected it | Review scoped per-tool access rules/default-denial support for the test identity/upstream. Require observed denial with no backend execution receipt before marking fixed. Do not weaken the application allowlist |
| O02 | AWS Vision One inventory attribution unverified | In Discovered Tools confirm `fixture_status` and `fixture_new_tool` under the AWS mock provider/model around 08:06 PDT on October 23. A screenshot or exported record should distinguish earlier local entries |
| O03 | Automatic tool-change notification delivery unavailable | Stateless fixture intentionally uses explicit `tools/list` refresh. A stateful `listChanged` experiment would be separate implementation/testing |
| O04 | No real LLM/Bedrock susceptibility testing | Current assistant is scripted and diagnostic provider inert. Any real-model work needs separate cost/configuration scope |
| O05 | Live short-reference tampering/expiry checks not separately run | Unit coverage validates tampering, scope, expiry and hashing; historical full-token probes must not be described as live short-reference tests |
| O06 | Generic deployment/teardown not fully automated | Runbook describes manual stages. RDS, secrets and log groups are retained; stack deletion alone is not zero-cost cleanup and retained RDS can block networking deletion |
| O07 | Production and fleet readiness not established | Single-copy synthetic acceptance does not cover scale, long-running reliability, real customer identity mapping or the separate AgentCore fleet |

## Supporting records

- [Discovery explanation, model linking and diagrams](aws-discovery-explained.md)
- [Single-copy deployment runbook](../infra/trend-aws/README.md)
- [Vision One console setup](trend-aws-console-setup.md)
- [Historical pre-assignment baseline](trend-aws-test-results.json),
  [historical guardrail retest](trend-aws-guardrail-results.json),
  [full-capability comparison](trend-capability-comparison.md)
- [Historical HTTP 400](trend-aws-model-discovery-before-route-correction.json),
  [corrected model route](trend-aws-model-discovery-results.json),
  [dynamic access finding](trend-aws-dynamic-results.json)
- [Local discovery investigation](trend-discovery-diagnosis.md),
  [verified local follow-up](model-discovery-probe.md)

Private deployment ledgers, earlier 11/12 core result, browser attribution evidence
and health snapshot remain under ignored `build/trend-aws/<namespace>/`. Do not put
keys, passwords, enrollment files or raw business payloads in documentation.
