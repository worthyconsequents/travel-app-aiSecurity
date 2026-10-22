# Architecture diagrams

The diagrams describe repository code and recorded evidence as of 22 October 2026. They separate what is implemented from planned integrations and historical infrastructure.

| Diagram | Scope | Preview | Editable files |
| --- | --- | --- | --- |
| Non-AgentCore local deployment | Implemented local Compose app on port 8080; reference authorization gateway | [PNG](01-non-agentcore-local.png) | [SVG](01-non-agentcore-local.svg), [Mermaid](01-non-agentcore-local.mmd) |
| AgentCore target design | Intended full AWS architecture; not deployed | [PNG](02-agentcore-target-design.png) | [SVG](02-agentcore-target-design.svg), [Mermaid](02-agentcore-target-design.mmd) |
| AgentCore implementation and test scope | Implemented offline alternative on port 8081 versus completed and removed AWS test slice | [PNG](03-agentcore-implementation-and-test-scope.png) | [SVG](03-agentcore-implementation-and-test-scope.svg), [Mermaid](03-agentcore-implementation-and-test-scope.mmd) |
| Multiple AWS copies and shared key | Approved isolation model; [fleet deployment code](../aws-multi-deployment.md) is locally validated, not cloud-tested | [PNG](04-aws-multi-deployment.png) | [SVG](04-aws-multi-deployment.svg), [Mermaid](04-aws-multi-deployment.mmd) |
| Local Trend MCP deployment | Implemented isolated app on 8082; ten tools discovered; legitimate signed calls currently denied | [PNG](05-trend-local-deployment.png) | [SVG](05-trend-local-deployment.svg), [Mermaid](05-trend-local-deployment.mmd) |
| Trend inspection test flows | Observed backend rejection, vendor content denial and signed-request compatibility blocker | [PNG](06-trend-inspection-test-flows.png) | [SVG](06-trend-inspection-test-flows.svg), [Mermaid](06-trend-inspection-test-flows.mmd) |

PNG previews and SVGs share the approved visual layout. Mermaid files preserve the logical relationships for editing or GitHub rendering; their automatic layout can differ. Request and data flows are shown at a high level; return responses generally follow the same path unless response inspection is illustrated explicitly.

## Evidence boundaries

- The original app keeps its reference-gateway path. The separate local Trend profile uses the installed vendor gateway, an application virtual key and an authenticated private bridge. Normal-use acceptance is blocked by legitimate signed-request denials; see [local results](../trend-local-test.md).
- The offline AgentCore simulator uses shared interception code and deterministic marker fixtures; it makes no AWS or Trend detection calls.
- The full AgentCore design retains application ownership and approval checks. Content inspection and Cedar policies do not replace that authorization boundary. The newer fleet option selects Fargate/RDS hosting; its implementation and remaining live validation are described in the fleet guide. The shared-key illustration remains a conceptual deployment model.
- The historical AWS test verified gateway routing, real inspection, malformed-input rejection and inspector outage/recovery with a fixed read-only hotel tool. The synthetic injection was allowed by Trend. No successful real content block, live model or full hosted app was demonstrated. All test-created AWS resources were torn down and verified absent.
- Local Trend testing observed one content-policy denial for a synthetic request injection. This does not change the historical AWS test result, establish response-attack blocking or demonstrate real-model susceptibility.
- Local monitoring displays application records. A unified view of cloud Lambda logs and application events is not implemented.

## Source references

- [Local architecture decision](../adr-001.md), [base Compose configuration](../../compose.yaml), [NGINX routing](../../nginx/default.conf)
- [Application API](../../services/api.py), [reference enforcement gateway](../../services/gateway.py)
- [AgentCore overlay](../../compose.agentcore.yaml), [agent loop](../../services/agentcore/agent.py), [offline gateway](../../services/agentcore/offline_gateway.py)
- [AgentCore implementation and handoff](../agentcore-alternative.md), [offline cloud planner](../../scripts/agentcore_plan.py)
- [AWS test and teardown](../aws-test-deployment.md), [redacted verification evidence](../aws-cloud-test-verification.json)
- [Separate Trend gateway installation](../../infra/trend-gateway/README.md)

## Dynamic MCP experiment

The root README embeds the implemented [test architecture](07-dynamic-mcp-tool-tests.mmd)
and [observed sequence](08-dynamic-mcp-observed-flow.mmd) as GitHub-rendered Mermaid diagrams.
These show the new tool being discovered and called through Trend, while the app
rejects it. Vendor per-tool denial remains unverified; the tested direct call was allowed.
See [the dated report](../tool-changes.md).
