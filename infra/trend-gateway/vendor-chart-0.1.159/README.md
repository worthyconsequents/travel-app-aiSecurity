# TrendAI Gateway

Secures LLM and MCP traffic. The gateway sits between your applications and
their model and tool providers, enforces the policy you configure in
TrendAI Vision One&trade;, and sends activity data back to the console.

## Requirements

- Kubernetes 1.27 or later
- Helm 3.x
- Outbound HTTPS on port 443 from the cluster to the Vision One API. The gateway
  initiates outbound connections, so no inbound access to your cluster is
  required.

## Install

TrendAI Vision One&trade; generates an `overrides.yaml` and an install command
with your account's values already filled in. Copy each to the corresponding
location.

```bash
helm install trendai-gateway oci://public.ecr.aws/trendmicro/ai-security/ai-gateway \
  -f overrides.yaml \
  --namespace trendai-gateway --create-namespace
```

The release name is fixed at `trendai-gateway` — your Kubernetes resources
are named after it, so the Deployment and Service become
`trendai-gateway-gateway`. The name the gateway reports to the console comes
from the overrides file instead:

`overrides.yaml` carries your region's API host and a one-time enrollment token:

```yaml
gateway:
  gatewayName: my-gateway
  visionone:
    url: https://api.xdr.trendmicro.com
    authToken:
      bootstrap:
        token: <enrollment-token>
```

| Field | What it is |
|---|---|
| `gateway.gatewayName` | The name this gateway reports to the console. Defaults to the Helm release name when omitted. |
| `gateway.visionone.url` | The TrendAI Vision One&trade; API host for your region. Use scheme and host only; the gateway builds the rest of the path. |
| `gateway.visionone.authToken.bootstrap.token` | A one-time enrollment token. On first startup the gateway exchanges it for a device token, then rotates that device token automatically. |

The enrollment token is shown only once. If you lose it, restart setup to
generate a new one.

Images come from the public gallery and are anonymously pullable, so no
`imagePullSecrets` are needed.

## Confirm it connected

```bash
kubectl -n <namespace> rollout status deploy/<gateway-name>-gateway
helm test <gateway-name> --namespace <namespace>
```

When the gateway's status changes to **Connected** in the console, it has
enrolled using its token and polls for policy and catalog updates every 30
seconds.

## Ports

Three ports, all `ClusterIP` by default.

| Port | Name | Serves |
|---|---|---|
| 8080 | `llmProxy` | OpenAI-compatible LLM traffic |
| 8081 | `mcpProxy` | MCP tool traffic |
| 9090 | `manager` | `/health`, `/readyz`, `/metrics`, `/version` |

**8080 — LLM proxy.** Provider-native passthrough over an OpenAI-shaped surface:
`/v1/chat/completions`, `/v1/responses`, `/v1/completions`, `/v1/embeddings`,
`/v1/rerank`, `/v1/models`, `/v1/audio/{speech,transcriptions,translations}`,
and `/v1/messages` for Anthropic-style clients.

**8081 — MCP proxy.** MCP streamable-HTTP (JSON-RPC over SSE) served at the root
path; `/health` and `/readyz` are carved out. Tools from every registered
upstream are aggregated into a single namespaced `tools/list`.

**9090 — manager.** Probes and Prometheus metrics. Keep this cluster-internal.

Expose the two proxies with `gateway.ingress` or `gateway.service.type`.

## Send traffic through it

Point an existing application at the in-cluster Service address — no SDK or code
changes:

```
http://<gateway-name>-gateway.<namespace>.svc.cluster.local:8080/v1
```

```bash
kubectl -n <namespace> port-forward svc/<gateway-name>-gateway 8080:8080

curl -sS http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer <virtual-key>" \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}]}'
```

Applications authenticate with **virtual keys**, created in the console. If a
key is compromised you can revoke it without changing your provider
credentials.

## Common values

| Key | Default | Purpose |
|---|---|---|
| `gateway.replicaCount` | `2` | Replicas. More than one requires Redis. |
| `gateway.redis.enabled` | `true` | Bundled Redis for shared catalog state across replicas. |
| `gateway.visionone.url` | `""` | Vision One API host for your region. Required. |
| `gateway.ingress` | disabled | Ingress for the LLM and MCP proxies. |
| `gateway.autoscaling` | disabled | HorizontalPodAutoscaler. |
| `image.registry` | `public.ecr.aws/trendmicro/ai-security` | Override to pull from your own registry. |

Run `helm show values` for the full schema, and see `examples/` for
production-shaped values files.

## Upgrade

```bash
helm upgrade <gateway-name> oci://public.ecr.aws/trendmicro/ai-security/ai-gateway \
  --version <new-version> -f overrides.yaml --namespace <namespace>
```

The enrollment token is not reset on upgrade — the live device token is
preserved.
