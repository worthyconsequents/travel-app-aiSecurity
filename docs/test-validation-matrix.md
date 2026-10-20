# Test and validation inventory

Snapshot: 2026-10-19. This file records cases, how to run them, what was verified,
and what remains untested. It is not permission to incur costs or change cloud
resources. The [agent handoff](AGENT_HANDOFF.md) supplies architecture/context.

## Latest result and exact unit inventory

The fleet implementation's latest local run passed **156 unit cases**, plus Ruff,
CloudFormation schema/security checks and local image/configuration checks described
below. One existing TestClient/httpx deprecation warning remained. Machine-readable
summary: [aws-fleet-offline-verification.json](aws-fleet-offline-verification.json).

[unit-test-cases.txt](testing/unit-test-cases.txt) lists all 156 collected pytest
node IDs, including parameter variations. It is a discovery snapshot, not a test
execution log. The source tests and a new run are authoritative after code changes.

| Suite | Cases | Assertions covered |
|---|---:|---|
| `tests/unit/test_aws_fleet.py` | 26 | Configuration, isolation, IAM/key references, deployment lifecycle and cloud runtime guards; detailed below |
| `tests/unit/test_agentcore.py` | 44 | Both HTTP/MCP contracts and directions; allowed/blocked/error results; malformed envelopes/encoding/size/media; body preservation; header/credential exclusion; endpoint confinement; token cache; profiles/namespaces; SigV4; no fallback; explicit paid opt-in; output token bounds |
| `tests/unit/test_agentcore_deployment.py` | 2 | Offline SDK request-shape plan and narrowly scoped interceptor foundation template |
| `tests/unit/test_cloud_staging.py` | 20 | Fixed fixture ignores injected instructions; rejects unknown/extra/missing/unbounded arguments; deterministic private-free package; safe names; no model/booking permissions; credential parser; offline plan; outage restoration; request limit; exact teardown confirmation and foreign-secret rejection |
| `tests/unit/test_foundation.py` | 20 | Mock defaults/cost guards; ownership/workload/approval policy decisions; approval reuse/rescoping rejection; scoped capability expiry/fingerprint; fail-closed gateway errors and audit evidence |
| `tests/unit/test_health.py` | 1 | Foundation health contract |
| `tests/unit/test_monitor.py` | 15 | Locked routes; traveler/admin cannot bypass operator password; login/logout; cookie tamper/expiry/profile binding; password rotation; throttling; provider outage/cache; stored feed/flow; sensitive-field rejection; offline secret plan and mocked apply; validation redaction |
| `tests/unit/test_travel_assistant.py` | 28 | Read-only intent parsing; mutation/approval/identity spoof rejection; untrusted/internal-field exclusion; denial redaction; safe trips/hotel display; no instructions executed from tool prose; session-bound API; independent cookie names |

## AWS fleet cases — automated offline PASS

Test identifiers refer to functions in `tests/unit/test_aws_fleet.py`. Parametrized
configuration rejection has seven cases; the other functions each contribute one.
Mocked AWS/lifecycle assertions establish code behavior, not live cloud outcomes.

| ID | Test function | Expected result |
|---|---|---|
| F01 | `test_plan_has_stable_distinct_names_and_no_client` | Three distinct URLs/names; same index survives count increase; preview creates no AWS session |
| F02 | `test_invalid_config_rejected` | Reject count `0`, `21`, `1.5`; wrong resource prefix; path-like environment; public `/0` operator ingress; invalid boolean |
| F03 | `test_env_is_data_and_duplicates_fail` | Shell-shaped text remains literal data; duplicate assignments fail |
| F04 | `test_missing_or_cross_account_settings_stop_before_aws` | Reject cross-account secret, mutable image tag and missing certificate; incomplete deploy/absent apply flags fail before AWS; plan still works |
| F05 | `test_hosting_copies_do_not_share_state_or_key` | Distinct CIDRs and generated secrets; no vendor secret in hosting; private/encrypted database; snapshot lifecycle; private tasks; mandatory login; no public ingress; no task port collisions |
| F06 | `test_only_inspectors_share_exact_detection_secret` | Distinct inspector roles/application names read the same exact secret; gateway role cannot read it; versioned code; model target absent by default; enforced five-read-tool Cedar policy; private targets |
| F07 | `test_template_sizes_and_all_references_resolve` | Template bodies fit inline size limit; Ref/GetAtt logical dependencies resolve |
| F08 | `test_package_excludes_private_inputs` | Packaging omits `.env.local`, PEM and symlink inputs while retaining allowed source |
| F09 | `test_teardown_rejects_shared_and_ownership_before_writes` | Wrong confirmation/shared namespace and foreign ownership stop before delete API access |
| F10 | `test_stack_scope_rejects_foreign_tags_and_arn` | Wrong ownership tags and cross-account stack ARNs are refused |
| F11 | `test_aws_demo_cannot_use_default_auth_secrets` | Cloud demo requires explicit authenticated-edge mode, strong signing key and secure cookies |
| F12 | `test_cloud_database_uses_tls_and_url_escapes_credentials` | Database URL requires verify-full and CA bundle; special characters remain valid and password is hidden in URL representation |
| F13 | `test_paid_inference_requires_explicit_model_project_and_enforces_it` | Incomplete paid config rejected; opted-in template scopes Mantle inference to the configured project and model |
| F14 | `test_target_prefix_is_per_copy` | Tool prefix contains the copy namespace; malformed prefix rejected |
| F15 | `test_redeploy_bound_stack_is_noop_and_blueprint_drift_rejected` | Same bound config does not create/update; changed blueprint rejected |
| F16 | `test_only_initial_gateway_binding_may_update_existing_stack` | Initial empty endpoint binding updates once, without creating another stack |
| F17 | `test_reduced_count_deploy_does_not_delete_extra_instances` | Deploy loop touches only desired copy; no deletion call |
| F18 | `test_fleet_scope_lock_prevents_concurrent_writes` | A second local operation cannot acquire the same fleet lock |
| F19 | `test_cloud_mock_chat_does_not_invoke_paid_inference` | Cloud mock mode calls the deterministic assistant, not the paid loop |
| F20 | `test_inspector_rejects_unconfigured_model_before_vendor` | Wrong model is rejected before calling the vendor inspector |

## Other validation performed for the fleet build

| Validation | Recorded result | Limit |
|---|---|---|
| Ruff checks and Git whitespace check | PASS | Style/static checks, not runtime verification |
| Three-copy template render | PASS; one shared plus three hosting and three AgentCore templates | Offline, fictitious account/domain/digests |
| cfn-lint 1.57.2 | PASS, no findings for seven rendered templates | Does not establish service availability or permission sufficiency |
| cfn-guard 3.2.1 with `infra/aws-fleet/fleet.guard` | PASS | Project rules only, not comprehensive security certification |
| Optional paid-path template | PASS schema/guard checks using fictitious model/project | No live paid target or model invocation |
| Python image | PASS linux/amd64 build from sanitized source context | No AWS database connection or hosted acceptance run |
| Frontend image | PASS linux/amd64 production build from sanitized source context | No new cloud browser acceptance run |
| AWS-configured module imports | PASS using dummy settings, network disabled | Imports only; not full application startup against RDS |
| NGINX generated configuration | PASS syntax check in cached container, network disabled | Does not prove real ALB/Lattice/ingress-key routing |
| Documentation links | Local links checked | Does not verify external pages or cloud state |

Guard rules check private/encrypted/snapshotted RDS; IAM-authenticated gateways
with both inspection hooks and no forwarded request headers; bounded/versioned real
inspector; Cognito HTTPS edge and private tasks; absence of public IPv4 `/0` SG
ingress; private/encrypted/versioned retained artifacts. They do not simulate IAM,
Cedar decisions, credential rotation, packet routing or vendor policy detection.

## Reproduce offline validation

Run from the repository root. `uv sync`/image builds may download dependencies;
the test, plan and render paths below do not invoke AWS or a model.

```sh
uv sync --frozen --extra aws-deploy
uv run --frozen --extra aws-deploy python -m pytest -q
uv run --frozen --extra aws-deploy ruff check .
git diff --check
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet plan --env-file infra/aws-fleet/fleet.example.env
uv run --frozen --extra aws-deploy python -m scripts.aws_fleet render --env-file infra/aws-fleet/fleet.example.env
cfn-lint build/aws-fleet/rendered/dannytran-travel-lab01/*.json
cfn-guard validate -d build/aws-fleet/rendered/dannytran-travel-lab01 -r infra/aws-fleet/fleet.guard
```

Install the optional validation tools separately if absent. Do not silently replace
missing tools with a claim of success. To discover current exact unit case IDs:

```sh
uv run --frozen --extra aws-deploy python -m pytest --collect-only -q
```

When updating the text inventory, preserve only `tests/unit/...::...` case-ID lines;
record execution results separately. Do not replace PASS counts based on collection
alone. Keep historical evidence files dated and unchanged.

## Local integration and browser checks — historical, not rerun for fleet changes

The existing Compose checks use real local service-to-service HTTP/MCP and
PostgreSQL. Their results are recorded in [base verification](verification.md),
[offline AgentCore evidence](agentcore-verification.json), and
[monitoring evidence](monitoring-verification.json), with older unit counts.

| Runner | Cases/behavior | Mutation and prerequisites |
|---|---|---|
| `make smoke` / `scripts/smoke.py` | Published proxy health and backend identity, cookie/session flow, owned bookings | Original local stack running |
| `make test` / `scripts/integration.py` | Ten-tool discovery; 12 stays/three destinations; filtering/details/profile; cross-owner denial; explicit booking approval; approval reuse rejection; idempotent replay; cancellation; mock chat; six attack fixtures | Creates/cancels synthetic reservations; not an AWS fleet test |
| `make scenarios` | Six fixtures: indirect injection, cross-owner read, privileged-tool abuse, approval bypass, bulk-record transfer and identity spoofing; expected policy/audit decisions, no denied downstream dispatch | Creates temporary scenario/session records; compares booking state; synthetic only |
| `make agentcore-test` / `scripts/agentcore_smoke.py` | Offline namespaced tools, mock model/tool loop, request/response inspection, marker block/outage behavior | Separate offline Compose stack; broader integration includes synthetic booking writes |
| `make chat-test` / `make agentcore-chat-test` | Read-only chat regressions through each proxy | Appropriate stack running; preserve existing bookings |
| `make monitor-test` / `make agentcore-monitor-test` | Password/session locks, saved records/flow, logout and public app regressions | Private local monitoring password configured; saved local scenario results |
| Historical outage/browser work | Offline gateway stop/recovery, blocked dispatch; public stay/persona navigation and monitor review | Evidence is dated; no automated Playwright fleet suite is claimed |

Local Docker images/containers must contain the source version under test. Host
unit tests passing do not mean an already-running container has the new source.
Do not run reset/seed-reset commands against data you intend to preserve.

## Historical live AWS test — completed and torn down

The [gateway fixture report](aws-test-deployment.md) and
[redacted JSON](aws-cloud-test-verification.json) describe 2026-10-18 testing,
not the full app/fleet. It made 17 gateway requests and zero model calls.

| Case | Actual result |
|---|---|
| Unsigned gateway request | PASS — HTTP 401 |
| Signed tool discovery | PASS — one fixed read-only hotel tool |
| Benign lookup | PASS — request inspection, fixture dispatch and response inspection evidenced in CloudWatch |
| Malformed input | PASS — HTTP 400 / `UNSUPPORTED_PAYLOAD`, no probe event in the request window |
| Inspector concurrency zero, recovery | PASS — no hotel/dispatch during failure; restored concurrency two and successful recovery independently verified |
| Synthetic prompt injection blocked by Trend | **FAIL — Trend allowed it and the fixture ran**; cause unresolved |
| Teardown and independent absence checks | PASS for all test-created stacks, gateway, functions, logs, roles, dedicated secret and versioned artifact bucket |

Timestamp-window evidence was serialized test evidence, not a general distributed
trace. The fixed fixture cannot establish LLM persuasion or booking/data-plane
protection. Do not recreate it, repeat the outage or delete other resources merely
to refresh documentation; those operations require current authorization.

## Pending AWS fleet acceptance — NOT RUN

Run only after current resource/cost authorization. Start with one copy and paid
inference off. These are acceptance targets, not promised outcomes or existing
automated tests. Record date, commit, exact scope, expected/actual result and redacted
evidence for each. Do not include tokens, passwords, raw chat prompts or private ledgers.

| ID | Acceptance case | Required evidence |
|---|---|---|
| C01 | Preflight real account/Region, DNS, certificate, RDS/images, quotas and AgentCore feature support | Correct-account checks and required regional prerequisites; stop on mismatch |
| C02 | Deploy one complete copy | Successful stack/service/target/policy readiness; private healthy app and DB; no unexpected resources |
| C03 | HTTPS/Cognito protection | Unauthorized requests reach login, not app data; invited operator signs in; self-registration unavailable |
| C04 | Monitoring password boundary | Separate monitor login required after Cognito; customer/admin persona, invalid password, tampered and expired cookies fail |
| C05 | Real private MCP route | Benign tool reaches intended copy through AgentCore/Lattice/TLS; no public task/DB/tool bypass; missing/wrong service key rejected |
| C06 | Shared-secret IAM boundary | Each inspector reads same exact secret; app/gateway roles cannot read it or another copy's application secrets |
| C07 | Business/capability checks | Own-booking reads work; cross-owner access, missing/tampered/expired/re-scoped capabilities denied; no forbidden downstream effects |
| C08 | Live Cedar policy | Five read tools allowed as intended; mutations/refunds/bulk/unknown tools denied by enforced policy |
| C09 | Trend benign/block/outage behavior | Assigned application policy allows benign text, blocks approved synthetic attack, fails closed during authorized inspector outage, recovers afterward; no downstream dispatch on deny |
| C10 | App and inspector evidence | App correlation/audit flow recorded; separate CloudWatch decisions match copy/request window; no credential/prompt leakage |
| C11 | Second copy and cross-copy isolation | Distinct URLs, data, roles, logins and app secrets; copy 1 session/monitor/capability cannot access copy 2; no cross-copy database access |
| C12 | Shared-key rotation | Authorized vendor/secret rotation affects all copies as expected, cache behavior observed, independent application credentials unchanged |
| C13 | Retry/count/failure recovery | Same-config retry avoids duplicates; increase adds intended copy; decrease deletes none; changed blueprint/foreign ownership/concurrent operation refused; rollback recovery documented |
| C14 | One-copy teardown | Only selected copy removed; DB snapshot and retained secrets/logs inventoried; other copies/shared key preserved; remaining costs identified |
| C15 | Shared-foundation cleanup review | Explicitly assess retained ECR/S3/snapshots/logs/secrets before separate cleanup; no blanket purge or shared-key deletion |
| C16 | Optional paid-model trial | Separate model/cost approval; real scoped model invocation, input/output inspection, tool loop bounds and denied-model/stream/token checks; actual usage recorded |

Do not report the full fleet as cloud-verified until the relevant cases have actual
evidence. Static isolation assertions, mock lifecycle tests and successful image
builds do not substitute for C01–C16.
