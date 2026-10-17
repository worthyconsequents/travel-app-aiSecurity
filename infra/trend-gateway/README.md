# Trend AI Gateway — local installation and integration handoff

Installed on 2026-10-17 after the user confirmed their license/trial covers registration and testing without additional charges. No AWS infrastructure or paid model inference was used. The gateway does communicate with the configured Trend Vision One API for enrollment, policy/catalog refresh and activity reporting.

## Inspected inputs and authoritative source

- `AI_Gateway/AI_GatewayHelm`: vendor Helm command; treated as reference, not automatically executed.
- `AI_Gateway/overrides.yaml`: gateway name, Vision One API host and a bootstrap credential. This file is now ignored by Git/build contexts and restricted to its owner. Do not paste or commit its contents.
- Public OCI chart `public.ecr.aws/trendmicro/ai-security/ai-gateway`, version **0.1.159**, app **lts-0.1.159**. Vendored under `vendor-chart-0.1.159/`; its README and values are the primary technical reference.
- Chart content layer digest: `sha256:0dd83e32d57761ae0bc4ba496e5440f9e7f3d69d35bb205999fddf7c6290716b`.
- Chart requires Kubernetes >=1.27 and Helm 3. The image manifest supports linux/amd64 and linux/arm64. Temporary tooling was downloaded from official Helm/kind releases and SHA-256 checked against their published checksums.

## What is running

The pre-existing docker-desktop Kubernetes API returned EOF. It was not reset or modified. A dedicated kind cluster **boring-travel**, context **kind-boring-travel**, was created inside local Docker. Its kubeconfig and temporary Helm/kind tools are stored in the ignored owner-only `private/` folder. The default kubeconfig was not changed.

Helm release: **trendai-gateway**, namespace **trendai-gateway**. Deployment and Service: **trendai-gateway-gateway**.

`local-values.yaml` sets one replica, no Redis, no Ingress or cloud LoadBalancer, virtual-key authentication, admin master-key protection and enabled MCP/scanning. The LLM proxy is explicitly disabled. Resource request: 1Gi RAM; memory limit: 3Gi. Model calls remain disabled in the travel app as well.

Private service ports: 8081 MCP, 9090 manager. Port 8080 exists in the chart's Service but the LLM proxy module is disabled and does not listen. The MCP proxy uses root `/`, not `/mcp`, and aggregates upstream tools with namespaced names. The current travel client expects per-server `/mcp` endpoints with canonical names, so changing only GATEWAY_URL is not a valid integration.

## Verified results

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

## Remaining integration steps

1. In Vision One, confirm gateway `dtran-test-gateway` is connected. Register the three upstream MCP server URLs in its MCP catalog, using Streamable HTTP. Exact console menus/API contracts were not provided, so their names have not been guessed.
2. Create a scoped application virtual key for the travel workload and the intended MCP tools. The enrollment/bootstrap token is not an application key. The user supplied `AI_Gateway/visionOneapikey.txt`, now owner-only and excluded from Git/build contexts. The empty `private/travel-virtual-key` placeholder was removed at the user’s request. Confirm this is an AI Gateway application virtual key before using it for MCP authentication; the filename does not establish its type. Do not paste it into chat or commit it.
3. Implement the app-side Trend MCP transport with virtual-key authentication and an exact catalog-tool-name mapping learned from authenticated `tools/list`. Provide a private return path from Compose to the Kubernetes MCP proxy. Fail closed on unavailable Trend; never silently fall back to direct MCP.
4. Keep customer ownership and approval consumption in the app enforcement path. Confirm the vendor's supported workload/human identity mapping and policies before attributing those controls to Trend. Do not use unverified model arguments or arbitrary user headers as identity.
5. Run authenticated allowed/denied tool tests and all six applicable fixtures, showing both Trend policy evidence and unchanged synthetic records. If the local policy rejects first, label it local enforcement. Never claim commercial protection solely because Trend is installed.

Application requests have NOT been switched to Trend yet: a virtual key, catalog entries, policy settings and the transport integration above are still required. The website continues working through its reference gateway.

## Local administration

All commands below must be run from the repo root. Tools are in ignored private storage and are not a system installation.

```sh
kubectl --kubeconfig infra/trend-gateway/private/kubeconfig --context kind-boring-travel -n trendai-gateway get pods,svc
infra/trend-gateway/private/helm test trendai-gateway --kubeconfig infra/trend-gateway/private/kubeconfig --kube-context kind-boring-travel --namespace trendai-gateway
```

Upgrade the existing release using the pinned local chart and its original bootstrap file; the chart preserves the live device credential:

```sh
infra/trend-gateway/private/helm upgrade trendai-gateway infra/trend-gateway/vendor-chart-0.1.159 --kubeconfig infra/trend-gateway/private/kubeconfig --kube-context kind-boring-travel --namespace trendai-gateway -f AI_Gateway/overrides.yaml -f infra/trend-gateway/local-values.yaml --wait --timeout 8m
```

Stop the gateway workload while preserving cluster state (this is a shutdown command, not a deployment step):

```sh
kubectl --kubeconfig infra/trend-gateway/private/kubeconfig --context kind-boring-travel -n trendai-gateway scale deployment/trendai-gateway-gateway --replicas=0
```

Use `--replicas=1` to start it again. The travel app's `make down` only stops its Compose services, not the kind cluster. The chart marks some Secrets keep-on-uninstall; do not assume Helm uninstall removes device/master keys or deregisters the gateway in Vision One. No teardown or deregistration has been performed.
