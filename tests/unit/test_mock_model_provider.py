import copy
import stat

import pytest
from fastapi.testclient import TestClient

from services.mock_model_provider import MODEL, create_app
from services.tool_change_fixture import catalog


def payload(added=False):
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Local synthetic inventory probe."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
            }
            for t in catalog("added" if added else "baseline")
        ],
        "max_tokens": 32,
        "stream": False,
    }


@pytest.fixture
def provider(monkeypatch, tmp_path):
    p = tmp_path / "key"
    p.write_text("mock-only-credential-" * 3)
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("MODEL_PROBE_ENABLED", "true")
    monkeypatch.setenv("MODEL_PROBE_KEY_FILE", str(p))
    return TestClient(create_app()), {"Authorization": "Bearer " + p.read_text()}


def test_mock_requires_auth_and_returns_only_synthetic_tools(provider):
    client, headers = provider
    assert client.post("/v1/chat/completions", json=payload()).status_code == 401
    for added, name in [(False, "fixture_status"), (True, "fixture_new_tool")]:
        response = client.post("/v1/chat/completions", json=payload(added), headers=headers)
        assert response.status_code == 200
        call = response.json()["choices"][0]["message"]["tool_calls"][0]
        assert call["function"] == {"name": name, "arguments": "{}"}
        assert response.json()["usage"]["total_tokens"] == 0
    assert client.get("/probe-receipts").status_code == 401
    receipts = client.get("/probe-receipts", headers=headers).json()
    assert len(receipts["calls"]) == 2 and receipts["paid_model_calls"] == 0


@pytest.mark.parametrize(
    "change",
    ["paid-model", "stream", "prompt", "unknown-tool", "changed-schema", "duplicate", "extra"],
)
def test_mock_rejects_unbounded_or_nonfixture_requests(provider, change):
    client, headers = provider
    body = copy.deepcopy(payload())
    if change == "paid-model":
        body["model"] = "real-provider-model"
    elif change == "stream":
        body["stream"] = True
    elif change == "prompt":
        body["messages"][0]["content"] = "An arbitrary prompt"
    elif change == "unknown-tool":
        body["tools"][0]["function"]["name"] = "issue_mock_refund"
    elif change == "changed-schema":
        body["tools"][0]["function"]["parameters"] = {}
    elif change == "duplicate":
        body["tools"] *= 2
    else:
        body["callback_url"] = "https://untrusted.invalid/"
    assert client.post("/v1/chat/completions", json=body, headers=headers).status_code == 422
    assert client.get("/probe-receipts", headers=headers).json()["calls"] == []


def test_cloud_and_disabled_mock_provider_refused(monkeypatch):
    monkeypatch.setenv("APP_MODE", "aws-demo")
    monkeypatch.setenv("MODEL_PROBE_ENABLED", "true")
    with pytest.raises(RuntimeError):
        create_app()
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("MODEL_PROBE_ENABLED", "false")
    with pytest.raises(RuntimeError):
        create_app()


def test_fresh_setup_creates_private_files_and_preserves_existing(monkeypatch, tmp_path):
    from scripts.tool_changes_setup import main

    monkeypatch.chdir(tmp_path)
    main()
    p = tmp_path / "infra/trend-gateway/private/tool-change-control-key"
    original = p.read_bytes()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    mock = tmp_path / "infra/trend-gateway/private/mock-model-key"
    assert stat.S_IMODE(mock.stat().st_mode) == 0o600
    mock_original = mock.read_bytes()
    main()
    assert mock.read_bytes() == mock_original
    assert p.read_bytes() == original
