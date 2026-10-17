# Travel assistant — local scripted implementation

Open http://localhost:8080 (current app) or http://localhost:8081 (offline AgentCore alternative), then choose **A little travel help**. The first message establishes the selected Alice profile through the existing session endpoint. Choosing Bob clears the chat and binds subsequent requests to Bob’s session.

## Try it

- “Find stays in Lisbon”, “Explore Kyoto”, or “Vancouver hotels”: real protected inventory lookups, with image cards and nightly rates in USD.
- Select “More about this stay”, or ask “Tell me about Azulejo Atelier”: a protected hotel detail lookup. Hotel names and IDs are recognized for the fixed local inventory.
- “Show my trips”: only the verified traveler’s reservations, including existing cancelled reservations.
- As Alice, “Show booking-bob”: a real gateway ownership denial, recorded in the audit log with no downstream dispatch. Identity is never accepted from chat text.
- “Book h01”, “Cancel my trip”, or “Approve a refund”: the scripted planner declines without making a tool call. This chat has no booking, quote, approval, payment, or refund workflow.

The alternative profile uses its own `boring_travel_agentcore_session` cookie, so the two localhost ports can remain signed in independently. Verify this with `CHAT_COMPARE_BASE_URL=http://localhost:8081 python3 scripts/chat_smoke.py` while both stacks are running.

## Paths and limits

The customer UI stays branded as the boring-travel company. Operator metadata (model mode, correlation ID, tool decisions and audit IDs) remains in the API response and audit endpoint, not in customer conversation bubbles. No paid service, AWS deployment, model call, or live Trend detection call is enabled by this feature.

The original implementation routes `/api/chat` through `services.agent` to the deterministic planner in `services.travel_assistant`, then uses the existing reference enforcement gateway and MCP services. The alternative retains the offline AgentCore model → tool → model path, HTTP/MCP interception and local policy enforcement; its inference simulator shares the same read-only planner and presenter. The original route is not evidence of commercial Trend enforcement. The offline route is not AWS or live Trend enforcement.

Hotel h04 contains the existing synthetic indirect prompt-injection fixture. Its full tool result reaches the server-side assistant, but descriptions are treated as data and excluded from display cards. No tool result is evaluated as planner instructions. This proves the scripted behavior and transport/authorization paths only. Testing whether a real model follows malicious content requires a separately approved model integration. Existing paid-inference opt-in gates remain in place.

Each message is a standalone request. The browser retains a bounded conversation for readability; conversational memory, streaming and arbitrary follow-up interpretation are not implemented. Credentials remain server-side. API responses carry the verified traveler identity; the client discards responses if another tab has changed the session to a different traveler. New chat clears browser conversation state. Switching travelers unmounts the conversation and aborts pending chat requests. Inputs are capped at 2,000 characters and blank messages are rejected.

## Verification

`make chat-test` runs the assistant unit tests and read-only HTTP checks for the current stack. `make agentcore-chat-test` does the same for the alternative. `make agentcore-test` also includes the existing offline contract checks, but its broader integration suite creates synthetic test reservations.

The read-only chat checks cover anonymous access, three destination searches, hotel h04, traveler isolation, cross-owner denial and audit evidence, rejected mutation requests, blank input, and before/after booking snapshots. They preserve existing data rather than reset the database.
