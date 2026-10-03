import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api-key",
        "api_key",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-account-id",
        "x-route-id",
        "x-request-id",
        "encrypted_content",
        "prompt_cache_key",
        "safety_identifier",
        "turn_id",
        "user",
    }
)
DROPPED_KEYS = frozenset({"attribution"})
DROPPED_KEY_PREFIX = "internal_"
BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
PROVIDER_ID_PATTERN = re.compile(r"\b(resp|msg|rs|req|fc|call)_[0-9a-f]{20,}\b")
REQUEST_ID_PATTERN = re.compile(r"(?i)(request-id:\s*)[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def _sanitize_string(value: str) -> str:
    value = BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
    value = PROVIDER_ID_PATTERN.sub(rf"\1_{REDACTED}", value)
    return REQUEST_ID_PATTERN.sub(rf"\1{REDACTED}", value)


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED
                if str(key).lower() in SENSITIVE_KEYS and item is not None
                else sanitize(item)
            )
            for key, item in value.items()
            if str(key).lower() not in DROPPED_KEYS
            and not str(key).lower().startswith(DROPPED_KEY_PREFIX)
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    return value
