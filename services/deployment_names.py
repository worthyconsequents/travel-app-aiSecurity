"""Naming contracts shared by deployment configuration and AWS Trend runtime gates."""

import re

TREND_PREFIX_PATTERN = r"(?:dannytran-boring-travel|boring-travel-bedrock-dtran)(?:-[a-z0-9]+)*"


def valid_trend_prefix(value):
    return isinstance(value, str) and re.fullmatch(TREND_PREFIX_PATTERN, value) is not None


def valid_trend_namespace(value):
    if not isinstance(value, str) or len(value) > 43:
        return False
    parts = value.rsplit("-", 2)
    return (
        len(parts) == 3
        and valid_trend_prefix(parts[0])
        and re.fullmatch(r"[a-z][a-z0-9]{0,9}", parts[1]) is not None
        and parts[2] == "01"
    )
