import os

from services.settings import require_runtime_configuration


async def converse(message, login, correlation):
    require_runtime_configuration()
    from services.agentcore.transport import deployment_profile

    profile = deployment_profile()
    if profile == "agentcore-aws" and os.getenv("MODEL_MODE", "mock") == "mock":
        from services.travel_assistant import converse as scripted_converse

        return await scripted_converse(message, login, correlation)
    if profile in {"agentcore-offline", "agentcore-aws"}:
        from services.agentcore.agent import converse as agentcore_converse

        return await agentcore_converse(message, login, correlation)
    mode = os.getenv("MODEL_MODE", "mock")
    if mode == "bedrock":
        from services.bedrock_chat import converse as bedrock_converse

        return await bedrock_converse(message, login, correlation)
    from services.travel_assistant import converse as scripted_converse

    return await scripted_converse(message, login, correlation)
