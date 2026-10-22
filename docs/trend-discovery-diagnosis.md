# Vision One discovered-tools diagnosis — 2026-10-22

Runtime MCP discovery and Vision One inventory are separate outcomes. Runtime
refresh passed, but **Vision One inventory population has not passed**. This
investigation changed no application code, vendor settings, policies or credentials.
No AWS operations, paid models, gateway upgrades or external support messages.

## What was verified

| Check | Finding |
|---|---|
| Gateway health | `/readyz` 200, server mode on, v0.1.159, commit abca741, MCP proxy + policy modules |
| Official public OCI chart | Helm resolved 0.1.159 / lts-0.1.159; no newer chart was identified and no upgrade performed |
| Fresh client `tools/list` | Eleven tools returned at 17:54:06 UTC: ten travel tools plus the restored fixture baseline |
| Cloud activity | That same list request appears in Vision One Events as an allowed `tools/list` record |
| Event delivery | Current-process snapshot: 75 sent, zero buffered/dropped/shipping failures; catalog sync failure counter zero |
| Inventory filters | Provider, model and alias all set to All; page still says “No tools observed yet” |
| Console active discovery | Reproduced HTTP 502 credential-file lookup failure; no candidates imported |
| Local secret-file presence | Exact reported singular filename exists and is nonempty in the active local gateway; plural alias and travel upstream filename also exist |

The fresh cloud event is `01a164bf-b0be-70f2-8837-e12e32188f71`, request
`01a164bf-b0bd-7ea7-b974-a29ae6270a92`, timestamp
`2026-10-22T17:54:06.654062043Z`. Its displayed data includes method, protocol,
identity and timing, but no tool definitions or tool-name list. Local sanitized
activity shapes likewise have no definitions and a null resource field. Call
activity includes tool names, and the earlier new-tool execution is independently
confirmed in Events.

**Limit:** activity records are not proof of a separate inventory feed's contents.
The exact vendor component or code defect is not established without source or
supported backend diagnostics. The observed activity shape is a useful clue,
not a claim that we inspected all outgoing payloads.

## Two distinct failure paths

1. **Discovered Tools inventory:** tool RPCs and activity delivery work, but the
   tool inventory remains empty. This narrows the failure to inventory reporting/
   ingestion or the preview feature's support for this MCP path. We have not
   verified which record schema/feed the inventory consumes. A functioning Events
   page does not establish that the inventory has received definitions and linkage.
2. **MCP → Discover tools → import:** the console stops at credential resolution:
   `/etc/secrets/gateway/dannytran-tool-change` cannot be found. That file exists
   in our working local gateway. This strongly suggests a different discovery
   execution/secret context, possibly another runtime or cached context. We did
   not establish where this console action executes. If it executes remotely,
   the private Docker address would also need a supported reachability path after
   credential lookup is fixed; we did not expose it publicly to test that theory.

The active gateway instance shown in Management matches the instance in the
received activity. One older inactive registry entry also exists; no evidence
establishes that it is being selected for discovery, and we did not remove it.

These failures are independent until proven otherwise. A failed manual import
must not automatically be cited as the cause of an automatic inventory failure.

## What this means for routing rules

[Trend's Resources documentation](https://docs.trendmicro.com/en-us/documentation/article/trend-vision-one-AIG-resources)
describes an automatically populated observed-tool inventory and a separate
candidate-discovery/import workflow for MCP upstreams. Model routing rules map
requested models to aliases. No verified requirement says a paid model or a model
routing rule is necessary for our direct MCP traffic. The console itself prompts
for MCP `tools/list` or `tools/call` traffic, which we supplied and verified in Events.
Adding a model routing rule does not remedy a missing credential file.

## Supported next investigation

Use the event/request IDs, version and reproducible file-presence mismatch to ask
Trend to confirm:

- Does this build publish MCP observed-tool inventory records, and through which
  supported schema/channel? Do those records require upstream resource linkage?
- Does the tenant inventory consume direct MCP traffic or only certain model/
  function observations in this preview build? The UI wording suggests MCP support.
- Where does console “Discover tools” execute, and how is the self-hosted gateway
  selected? Which secret store/filesystem must resolve a platform-file reference?
- Does another supported build or tenant rollout fix this workflow?

Once the execution context is known, use its supported secret and connectivity
mechanism, then retest catalog → inventory → imported tools → scoped ACLs separately.
Do not disable authentication, paste credentials into arbitrary headers, expose
private MCP servers publicly, add guessed management APIs, auto-create inventory
entries, or invoke paid models to make the screen appear populated.

The application tests remain useful and truthful: they record runtime catalog
changes and application enforcement, with console inventory unavailable. No local
application patch has been identified that can fix this vendor-side inventory path.
See the [machine-readable evidence](trend-discovery-diagnosis.json).
