# Trend AI Gateway — local installation and integration handoff

Installed on 2026-10-17 after the user confirmed their license/trial covers registration and testing without additional charges. No AWS infrastructure or paid model inference was used. The gateway does communicate with the configured Trend Vision One API for enrollment, policy/catalog refresh and activity reporting.

This file describes the historical **local** installation. The currently running
single-copy AWS deployment has a separate [runbook](../trend-aws/README.md),
[status and issue register](../../docs/aws-deployment-issues.md), and
[discovery/model-linking diagram](../../docs/aws-discovery-explained.md).
Local addresses, key paths and dated test outcomes below must not be copied into
AWS configuration or read as current local-container health.

## Inspected inputs and authoritative source

- `AI_Gateway/AI_GatewayHelm`: vendor Helm command; treated as reference, not automatically executed.
- `AI_Gateway/overrides.yaml`: gateway name, Vision One API host and a bootstrap credential. This file is now ignored by Git/build contexts and restricted to its owner. Do not paste or commit its contents.
- Public OCI chart `public.ecr.aws/trendmicro/ai-security/ai-gateway`, version **0.1.159**, app **lts-0.1.159**. Vendored under `vendor-chart-0.1.159/`; its README and values are the primary technical reference.
- Chart content layer digest: `sha256:0dd83e32d57761ae0bc4ba496e5440f9e7f3d69d35bb205999fddf7c6290716b`.
- Chart requires Kubernetes >=1.27 and Helm 3. The image manifest supports linux/amd64 and linux/arm64. Temporary tooling was downloaded from official Helm/kind releases and SHA-256 checked against their published checksums.

## Historical local installation topology

The pre-existing docker-desktop Kubernetes API returned EOF. It was not reset or modified. A dedicated kind cluster **boring-travel**, context **kind-boring-travel**, was created inside local Docker. Its kubeconfig and temporary Helm/kind tools are stored in the ignored owner-only `private/` folder. The default kubeconfig was not changed.

Helm release: **trendai-gateway**, namespace **trendai-gateway**. Deployment and Service: **trendai-gateway-gateway**.

`local-values.yaml` sets one replica, no Redis, no Ingress or cloud LoadBalancer, virtual-key authentication, admin master-key protection and enabled MCP/scanning. The base values keep the LLM proxy disabled; the opt-in local model-discovery
experiment enables it using `model-probe-values.yaml` (see below). Resource request: 1Gi RAM; memory limit: 3Gi. Model calls remain disabled in the travel app as well.

Private service ports: 8081 MCP, 9090 manager, and 8080 LLM when its opt-in module
is enabled. In the base installation that module does not listen. The MCP proxy uses root `/`, not `/mcp`, and aggregates upstream tools with namespaced names. The current travel client expects per-server `/mcp` endpoints with canonical names, so changing only GATEWAY_URL is not a valid integration.

## Installation verification — historical 2026-10-17

- Helm lint and offline template rendering passed with placeholder credential references, not the real bootstrap token.
- Helm install completed, release status deployed, deployment 1/1 ready.
- Manager `/readyz`: MCP and policy ready; prompt_attack_scanner, harmful_scanner and skyeyes_scanner all loaded.
- Manager `/version`: v0.1.159, server mode on, modules mcp-proxy and policy only.
- Kubernetes auth-token Secret differs from the bootstrap token, verifying the enrollment credential exchange without displaying either token. The console Connected badge itself was not inspected.
- Vendor `helm test` succeeded.
- Temporary in-cluster network test discovered tools from all three MCP services through the private bridge.
- Unauthenticated MCP request to Trend returned HTTP 401.
- All six existing reference-gateway attack fixtures still pass. Those are not commercial-product enforcement tests.

## Private upstream link

`compose.trend.yaml` runs `trend-mcp-bridge`, an NGINX bridge attached to the app's private network and the kind Docker network. It publishes no host ports, mounts no credentials and retains the existing backend capability checks. It routes only the three MCP paths; other requests are rejected.

Current catalog URLs, verified from Kubernetes:

- travel-discovery: `http://172.20.0.3:8082/travel-discovery/mcp`
- reservations: `http://172.20.0.3:8082/reservations/mcp`
- customer-payments: `http://172.20.0.3:8082/customer-payments/mcp`

These are private Docker addresses, for the gateway catalog, not browser links. If the bridge is recreated, obtain its current kind-network address:

```sh
docker inspect travel-agent-security-demo-trend-mcp-bridge-1 --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}'
```

Restart only the bridge:

```sh
docker compose -f compose.yaml -f compose.trend.yaml up -d --wait trend-mcp-bridge
```

## Current local integration — 2026-10-22

The former transport/key/catalog gaps have been implemented in a separate
`boring-travel-trend` Compose project on port 8082. The original app and offline
AgentCore projects retain their existing routes. See [setup and exact test
results](../../docs/trend-local-test.md).

Three `dannytran-travel-test-*` HTTP upstreams and an independent service account
with an application virtual key were created in Vision One. The key is stored in
ignored owner-only local storage. The test bridge requires its own upstream key;
Kubernetes mounts that credential under the paths referenced by these upstreams.
Ten actual namespaced tools were discovered through the local gateway and mapped
explicitly. No direct MCP fallback is used.

A request/response guardrail assignment references existing `Boring-Travel-AI`,
scoped to only the new identity and three test upstreams. The existing content
policy itself was not modified. With that assignment active, a synthetic injection
gets a vendor content-policy denial, but ordinary signed app calls also get request
prompt-attack denials. Benign calls without a capability reach the backend and
correctly fail its signature check. This points to a compatibility problem involving
the signed capability in inspected arguments; exact classifier cause is unconfirmed.
The app fails closed. Do not call this option fully working or disable either control
without an explicit reviewed decision.

The console's Discover tools operation still reports a missing platform-secret
file even though local authenticated `tools/list` returns all ten tools. Its
Associated tools counts remain zero. Console import and explicit tool access-control
rules remain unfinished; do not interpret resource registration as a least-privilege
access policy. The default tenant access behavior allowed this test key to discover
the catalog before the scoped inspection assignment.

The original bridge addresses documented above are historical. The new isolated
bridge's current address is discovered from `boring-travel-trend-trend-mcp-bridge-1`;
it must be rechecked after recreation. Do not register the original application's
bridge as a substitute.

## Local administration

All commands below must be run from the repo root. Tools are in ignored private storage and are not a system installation.

```sh
kubectl --kubeconfig infra/trend-gateway/private/kubeconfig --context kind-boring-travel -n trendai-gateway get pods,svc
infra/trend-gateway/private/helm test trendai-gateway --kubeconfig infra/trend-gateway/private/kubeconfig --kube-context kind-boring-travel --namespace trendai-gateway
```

Base-installation upgrade example using the pinned chart and original bootstrap
file; the chart preserves the live device credential. This reapplies base values
and disables the diagnostic LLM proxy. To preserve the model-probe configuration,
use the narrow `--reuse-values` procedure in the probe guide instead:

```sh
infra/trend-gateway/private/helm upgrade trendai-gateway infra/trend-gateway/vendor-chart-0.1.159 --kubeconfig infra/trend-gateway/private/kubeconfig --kube-context kind-boring-travel --namespace trendai-gateway -f AI_Gateway/overrides.yaml -f infra/trend-gateway/local-values.yaml --wait --timeout 8m
```

Stop the gateway workload while preserving cluster state (this is a shutdown command, not a deployment step):

```sh
kubectl --kubeconfig infra/trend-gateway/private/kubeconfig --context kind-boring-travel -n trendai-gateway scale deployment/trendai-gateway-gateway --replicas=0
```

Use `--replicas=1` to start it again. The travel app's `make down` only stops its Compose services, not the kind cluster. The chart marks some Secrets keep-on-uninstall; do not assume Helm uninstall removes device/master keys or deregisters the gateway in Vision One. No teardown or deregistration has been performed.

## Verified local model-tool discovery — 2026-10-22

The opt-in local experiment now populates Vision One **Discovered Tools**. Sending
MCP-derived definitions through the LLM proxy to an inert mock provider registered
`fixture_status` and newly introduced `fixture_new_tool`, with one call each.
Both model requests returned 200 and both MCP executions had matching private
provider/backend receipts. This required no AWS deployment or paid inference.

[Complete setup, failures resolved, validation and retirement procedure](../../docs/model-discovery-probe.md) ·
[Sanitized evidence](../../docs/model-discovery-verification.json) ·
[Architecture source](../../docs/architecture/09-model-tool-discovery.mmd).

The experiment adds `compose.model-probe.yaml`, a private return link, local-only
NodePort `dannytran-local-llm-probe`, and the LLM-enabled values overlay. The exact
requested model `dannytran-tool-discovery-probe` routes only to alias
`dannytran-local-tools` and inert provider `dannytran-local-mock`; no wildcard,
paid provider or fallback is configured. The provider base URL omits `/v1` because
the tested gateway appends it. All private keys and runtime addresses stay out of
tracked deployment configuration. Recheck the mock's Docker address after recreation.

The mock-only route, local LLM module and test services remain enabled for review.
The travel assistant itself remains scripted. This result does not fix active MCP
console import, signed-request inspection compatibility, automatic notifications
or vendor per-tool blocking. Observation never promotes a tool into the app's
approved mapping. Complete unit suite: 227 passed, plus Ruff lint/format checks.
