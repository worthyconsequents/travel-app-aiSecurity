# AgentCore alternative build checklist

- [x] Preserve original site, database, current local gateway and Trend deployment.
- [x] Isolated alternative Compose profile on localhost:8081.
- [x] Buffered model and namespaced MCP adapters; IAM SigV4 implementation; no fallback.
- [x] Shared HTTP/MCP Lambda interception contracts and deterministic offline inspection fixture.
- [x] Live AI Guard client with scoped Secret lookup, bounded cache, endpoint validation and safe logs.
- [x] Offline model/tool/model flow with existing ownership and single-use approvals.
- [x] 61 unit tests, HTTP/MCP integration, six reference fixtures, interception smoke and real stopped-gateway test.
- [x] CloudFormation foundation, default-deny/read-only Cedar request templates, local ZIP packaging and static checks.
- [x] Setup instructions, cost boundary, verification evidence and cloud prerequisites documented.
- [ ] Cost-approved AWS account/Region/model, resources and teardown plan.
- [ ] Actual AI Guard detection API credential/schema and assigned blocking policy verification.
- [ ] Cloud private MCP/database hosting, API-key-verifying ingress and production user authentication.
- [ ] Full least-privilege model/target/caller IAM bindings and workload-specific mutation policies.
- [ ] Service-side Cedar validation; deployed AWS gateway/Lambda allow/deny/outage/bypass tests.
