"""Untrusted catalog comparison. Never promote observed tools into an approved registry."""

import hashlib
import json


def contract(tool):
    value = tool if isinstance(tool, dict) else tool.model_dump(exclude_none=True)
    # Include all advertised metadata, not only names and a capability property.
    return {
        k: v
        for k, v in value.items()
        if k != "name" and v is not None and not (k == "description" and v == "")
    }


def fingerprint(tool):
    return hashlib.sha256(
        json.dumps(contract(tool), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def inventory(tools):
    result = {}
    for tool in tools:
        name = tool["name"] if isinstance(tool, dict) else tool.name
        if name in result:
            raise ValueError("Duplicate advertised tool identity")
        result[name] = fingerprint(tool)
    return result


def compare(approved, observed):
    before, after = inventory(approved), inventory(observed)
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": sorted(k for k in before.keys() & after.keys() if before[k] != after[k]),
        "before": before,
        "after": after,
    }
