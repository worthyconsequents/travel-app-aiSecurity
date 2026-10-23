import copy
import json
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mcp.types import Tool

from services.tool_catalog import compare, fingerprint, inventory
from services.tool_change_fixture import Fixture, catalog, create_app


def test_fingerprint_canonical_keys_and_full_metadata():
    tool = catalog()[0]
    assert fingerprint(tool) == fingerprint(dict(reversed(list(tool.items()))))
    for field, value in [
        ("description", "changed"),
        ("outputSchema", {"type": "object"}),
        ("annotations", {"readOnlyHint": True}),
        ("inputSchema", {"type": "object"}),
    ]:
        assert fingerprint(tool) != fingerprint(tool | {field: value})
    assert fingerprint(tool) == fingerprint(Tool(**tool))


@pytest.mark.parametrize(
    "state,added,removed,changed",
    [
        ("baseline", [], [], []),
        ("added", ["fixture_new_tool"], [], []),
        ("schema", [], [], ["fixture_status"]),
        ("description", [], [], ["fixture_status"]),
        ("collision", ["search_hotels"], [], []),
        ("removed", [], ["fixture_status"], []),
        ("behavior", [], [], []),
    ],
)
def test_catalog_drift_classification(state, added, removed, changed):
    delta = compare(catalog(), catalog(state))
    assert [delta[k] for k in ("added", "removed", "changed")] == [added, removed, changed]


def test_duplicate_identity_rejected():
    with pytest.raises(ValueError):
        inventory(catalog() * 2)


def test_lease_exclusivity_expiration_and_stale_reset():
    f = Fixture()
    a, b = "a" * 32, "b" * 32
    f.acquire(a)
    f.change(a, "added")
    with pytest.raises(HTTPException):
        f.acquire(b)
    with pytest.raises(HTTPException):
        f.release(b)
    f.until = time.monotonic() - 1
    f.acquire(b)
    assert f.state == "baseline" and not f.receipts
    with pytest.raises(HTTPException):
        f.change(a, "schema")
    with pytest.raises(HTTPException):
        f.release(a)
    assert f.owner == b


def test_current_schema_enforced_and_same_name_behavior_observable():
    import jsonschema

    f = Fixture()
    with pytest.raises(ValueError):
        f.call("fixture_status", {})
    f.acquire("a" * 32)
    with pytest.raises(ValueError):
        f.call("fixture_new_tool", {})
    f.change("a" * 32, "schema")
    with pytest.raises(jsonschema.ValidationError):
        f.call("fixture_status", {})
    assert not f.receipts
    f.change("a" * 32, "behavior")
    assert f.tools() == catalog()
    assert f.call("fixture_status", {})["behavior"] == "changed"
    f.release("a" * 32)
    assert f.tools() == catalog() and not f.receipts


@pytest.fixture
def fixture_app(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("TOOL_CHANGES_ENABLED", "true")
    for setting, name in [
        ("TOOL_CHANGE_CONTROL_KEY_FILE", "control"),
        ("TOOL_CHANGE_UPSTREAM_KEY_FILE", "upstream"),
    ]:
        p = tmp_path / name
        p.write_text(name * 10)
        monkeypatch.setenv(setting, str(p))
    return create_app()


def test_control_auth_separated_from_mcp_and_no_arbitrary_states(fixture_app):
    with TestClient(fixture_app) as c:
        body = {"owner": "a" * 32}
        assert c.post("/control/acquire", json=body).status_code == 401
        assert (
            c.post(
                "/control/acquire", json=body, headers={"X-MCP-Service-Key": "upstream" * 10}
            ).status_code
            == 401
        )
        headers = {"X-MCP-Service-Key": "control" * 10}
        assert c.post("/control/acquire", json=body, headers=headers).status_code == 200
        assert (
            c.post(
                "/control/change", json=body | {"state": "execute-shell"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            c.post(
                "/control/change", json=body | {"url": "http://elsewhere"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            c.post("/control/observe", json={"owner": "b" * 32}, headers=headers).status_code == 409
        )
        assert c.post("/mcp/", json={}, headers=headers).status_code == 401
        assert c.get("/control/observe").status_code == 401


def test_disabled_and_cloud_fixture_refused(monkeypatch):
    monkeypatch.setenv("TOOL_CHANGES_ENABLED", "false")
    with pytest.raises(RuntimeError):
        create_app()
    monkeypatch.setenv("TOOL_CHANGES_ENABLED", "true")
    monkeypatch.setenv("APP_MODE", "aws-demo")
    with pytest.raises(RuntimeError):
        create_app()


def test_suite_is_opt_in_and_excluded_from_all(monkeypatch):
    from services import test_jobs as jobs
    from services.test_cases import case_plan

    monkeypatch.setenv("TOOL_CHANGES_ENABLED", "false")
    with pytest.raises(HTTPException) as caught:
        jobs.enqueue("tool-changes", "unique-test-key-1234")
    assert caught.value.status_code == 403
    assert len(case_plan("all")) == 12
    assert len(case_plan("tool-changes")) == 13


def test_pinned_travel_schema_and_description_rejected(monkeypatch, tmp_path):
    from pathlib import Path

    from services.trend_transport import canonical_catalog

    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("ENABLE_TREND_GATEWAY", "true")
    monkeypatch.setenv("TREND_MCP_URL", "http://trend-gateway-link:8081/")
    monkeypatch.setenv("TREND_VIRTUAL_KEY_FILE", "unused")
    names = ["search_hotels", "get_hotel_details", "search_flights"]
    path = tmp_path / "map"
    path.write_text(json.dumps({k: "remote-" + k for k in names}))
    monkeypatch.setenv("TREND_TOOL_MAP_FILE", str(path))
    baseline = json.loads(Path("services/approved_trend_catalog.json").read_text())
    approved = [Tool(**(baseline[k] | {"name": "remote-" + k})) for k in names]
    assert len(canonical_catalog("travel-discovery", approved)) == 3
    for field, value in [
        ("description", "new instructions"),
        ("inputSchema", {"type": "object"}),
        ("outputSchema", {"type": "object"}),
    ]:
        changed = copy.deepcopy(approved)
        setattr(changed[0], field, value)
        with pytest.raises(ValueError, match="reviewed baseline"):
            canonical_catalog("travel-discovery", changed)


@pytest.mark.parametrize("failure", ["startup", "catalog", "release"])
def test_failed_dependencies_never_count_as_vendor_block(monkeypatch, failure):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from services import test_cases
    from services import tool_change_tests as checks

    class DB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def add(self, row):
            pass

        def get(self, *args):
            return None

    class Sessions:
        def begin(self):
            return DB()

    class Probe:
        live = True
        mapping = {"fixture_status": "fixture_status", "fixture_new_tool": "fixture_new_tool"}
        released = False
        client = SimpleNamespace(aclose=None)

        def __init__(self):
            async def close():
                pass

            self.client = SimpleNamespace(aclose=close)

        async def control(self, action, state="baseline"):
            if action == "acquire" and failure == "startup":
                raise OSError("private-token-must-not-leak")
            if action == "release":
                self.released = True
                if failure == "release":
                    raise OSError("private-token-must-not-leak")
            return {"receipts": []}

        @asynccontextmanager
        async def session(self):
            raise ConnectionError("private-token-must-not-leak")
            yield

    probe = Probe()
    monkeypatch.setattr(checks, "Probe", lambda: probe)
    monkeypatch.setattr(checks, "Session", Sessions())
    monkeypatch.setattr(checks, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(test_cases, "snapshot", lambda: "unchanged")
    observed = []
    result, status = asyncio.run(checks.execute(lambda value: observed.append(value)))
    assert status == "blocked" and result["no_mutations"] is True
    assert len(result["scenarios"]) == 13
    assert result["fixture_restored"] == (failure == "catalog")
    assert probe.released == (failure != "startup")
    assert "private-token" not in json.dumps(result)
    assert not any(s["passed"] for s in result["scenarios"] if "gateway" in s["name"].lower())


def test_unmapped_new_fixture_tools_remain_visible_in_inventory():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from services.tool_change_tests import Probe

    p = Probe.__new__(Probe)
    p.prefix = "observed-fixture__"
    p.mapping = {"fixture_status": "observed-fixture__fixture_status"}
    session = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[
                    Tool(**(catalog()[0] | {"name": name}))
                    for name in [
                        "observed-fixture__fixture_status",
                        "observed-fixture__unexpected_future_tool",
                        "other-upstream__search_hotels",
                    ]
                ],
                nextCursor=None,
            )
        )
    )
    result = asyncio.run(p.tools(session))
    assert {t["name"] for t in result} == {"fixture_status", "unexpected_future_tool"}
    assert compare(catalog(), result)["added"] == ["unexpected_future_tool"]


def test_absent_and_empty_descriptions_are_equivalent_but_text_is_drift():
    tool = catalog()[0]
    empty = tool | {"description": ""}
    absent = {k: v for k, v in tool.items() if k != "description"}
    assert fingerprint(empty) == fingerprint(absent) == fingerprint(tool | {"description": None})
    assert fingerprint(empty) != fingerprint(tool | {"description": " "})
    assert fingerprint(empty) != fingerprint(tool)


def test_response_probe_is_fixed_leased_and_restored_without_schema_change():
    f = Fixture()
    with pytest.raises(HTTPException):
        f.change("a" * 32, "response")
    f.acquire("a" * 32)
    f.change("a" * 32, "response")
    assert f.tools() == catalog()
    result = f.call("fixture_status", {})
    assert "Ignore all previous instructions" in result["synthetic_instructions"]
    assert f.receipts == [{"tool": "fixture_status", "behavior": "baseline"}]
    f.release("a" * 32)
    assert f.tools() == catalog() and not f.receipts
    with pytest.raises(ValueError):
        f.call("fixture_status", {})
