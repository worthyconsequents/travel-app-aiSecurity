import os


def require_mock():
    """The base build never authorizes paid inference, even with local AWS credentials."""
    if os.getenv("MODEL_MODE", "mock") != "mock":
        raise RuntimeError(
            "This base build supports MODEL_MODE=mock only. Paid inference requires a "
            "separate, explicitly approved implementation step."
        )


def require_runtime_configuration():
    from services.agentcore.transport import deployment_profile

    if deployment_profile() == "agentcore-aws":
        mode = os.getenv("MODEL_MODE", "mock")
        if mode == "agentcore" and os.getenv("ENABLE_PAID_INFERENCE") == "true":
            return
    if os.getenv("MODEL_MODE") == "bedrock":
        from services.bedrock_chat import require_bedrock_chat

        require_bedrock_chat()
        return
    require_mock()
