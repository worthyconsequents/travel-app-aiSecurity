import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from services.agentcore.transport import deployment_profile, mcp_route


async def with_session(server, operation):
    url, _, auth = mcp_route(server)
    async with httpx.AsyncClient(
        timeout=12, follow_redirects=False, trust_env=False, auth=auth
    ) as client:
        async with streamable_http_client(url, http_client=client) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await operation(session)


async def discover(server):
    async def operation(session):
        result = await session.list_tools()
        if deployment_profile() == "trend-gateway":
            from services.trend_transport import canonical_catalog

            return canonical_catalog(server, result.tools)
        tools = []
        _, prefix, _ = mcp_route(server)
        for t in result.tools:
            if prefix and not t.name.startswith(prefix):
                continue
            canonical = t.name.removeprefix(prefix) if prefix else t.name
            schema = t.inputSchema.copy()
            schema["properties"] = {
                k: v for k, v in schema.get("properties", {}).items() if k != "gateway_capability"
            }
            schema["additionalProperties"] = False
            tools.append(
                {
                    "name": canonical,
                    "description": t.description or canonical,
                    "inputSchema": schema,
                }
            )
        return tools

    return await asyncio.wait_for(with_session(server, operation), timeout=15)


async def invoke(server, tool, args):
    async def operation(session):
        _, prefix, _ = mcp_route(server)
        if deployment_profile() == "trend-gateway":
            from services.trend_transport import tool_map

            remote = tool_map(server)[tool]
        else:
            remote = prefix + tool
        if deployment_profile() == "trend-gateway":
            from services.capability_transport import outgoing

            args_to_send = outgoing(args, tool)
        else:
            args_to_send = args
        result = await session.call_tool(remote, args_to_send)
        if result.isError:
            raise ValueError("MCP tool rejected the request")
        if result.structuredContent is not None:
            return result.structuredContent
        import json

        return json.loads(result.content[0].text)

    return await asyncio.wait_for(with_session(server, operation), timeout=15)
