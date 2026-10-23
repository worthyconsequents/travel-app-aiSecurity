"""Explicit, deployment-bound activation of inert AWS discovery fixtures."""

import os

from services.deployment_names import valid_trend_namespace


def cloud_enabled():
    return (
        os.getenv("APP_MODE") == "aws-demo"
        and os.getenv("ENABLE_AWS_TREND_GATEWAY") == "true"
        and os.getenv("ENABLE_AWS_TREND_FIXTURE") == "true"
        and os.getenv("MODEL_MODE", "mock") == "mock"
        and bool(valid_trend_namespace(os.getenv("TREND_K8S_NAMESPACE", "")))
    )


def allowed_mode():
    return os.getenv("APP_MODE", "local") == "local" or cloud_enabled()
