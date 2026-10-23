# Proposed Bedrock option and automation boundaries

Design note, October 23, 2026. The current hosted Trend build uses mock inference.
The operator authorized publishing that build first and asked whether a subsequent
Bedrock deployment can be automated. This note does not enable Bedrock or invoke
models. Preserve the tested mock option as a separate selectable mode.

## Automatable AWS work

Deployment tooling can render/apply the compute, private networking, service roles,
model-scoped IAM permissions, secret references and application configuration.
It can expose an explicit Bedrock mode, model/Region configuration, bounded output
tokens, tool-call limits, timeouts and usage reporting. The normal tool route must
retain business authorization, signed grants, approval checks and Trend MCP
inspection. IAM-backed workloads should use temporary role credentials rather
than embedding access keys.

The chatbot needs a real conversation/tool loop: submit reviewed definitions,
validate each selected tool and arguments, authorize it, execute through Trend,
and return the tool result to the model. The mock currently makes a fixed selection;
changing only a Vision One model name does not implement this application loop.
Bedrock client-side tool use supports model-selected tool requests with application
execution. [AWS documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html).

## Vision One work still to verify

The public guides describe console operations to register a provider, add its model,
associate an alias, create weighted routing rules, assign identity access and apply
content policies. They do not by themselves establish a supported automation API
for these operations. Do not assume an undocumented browser endpoint is supported
or use browser automation as the default deployment contract.

[Official resource guide](https://docs.trendmicro.com/en-us/documentation/article/trend-vision-one-AIG-resources) ·
[Official controls guide](https://docs.trendmicro.com/en-us/documentation/article/trend-vision-one-AIG-controls).

First verify this installed gateway version's native Bedrock provider/API/auth
support. If suitable support exists, configure it through the supported mechanism.
Otherwise a private OpenAI-shaped adapter in AWS could accept the inspected model
request from Trend and call Bedrock using its workload IAM role. That is a proposed
compatibility path requiring implementation and testing, not a deployed feature.

The intended request path is:

`chatbot -> Trend LLM proxy -> native Bedrock integration or private adapter -> Bedrock`

Then:

`selected tool -> application authorization -> Trend MCP proxy -> business MCP service`

Direct model calls from the chatbot to Bedrock would bypass Trend's model-request
observation path, which is the path used in the verified discovery experiment.
The model provider and MCP upstreams remain separate configuration objects.

## Practical initial deployment contract

Automate the AWS side and generate a deployment-specific Vision One checklist with
exact provider URL, credential reference, model ID, alias and exact routing label.
Keep a one-time console checkpoint for registration/access/policy assignment until
a supported API is verified. If the provider URL and model/alias remain stable,
ordinary compatible application redeployments should not need those entries
re-created; changes to model or policy scope can still need configuration updates.
Human/model access eligibility and AWS terms or subscriptions may also require
operator action for the selected model. Verify the actual account/Region/model.

After configuration, run bounded benign and adversarial checks, compare real
model behavior against mock wiring tests, and independently verify Vision One
inventory/Events. The existing gateway new-tool ACL failure remains separate;
Bedrock does not fix it automatically. Real inference remains disabled until its
configuration and paid-call scope are explicitly enabled.
