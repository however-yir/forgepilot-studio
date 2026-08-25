from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from pydantic import BaseModel, Field

from openhands.forgepilot.harness.action_schema import HarnessActionType
from openhands.forgepilot.tool_registry.schema import (
    ToolPermission,
    summarize_tool_output,
)


class HarnessObservationStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    DENIED = 'denied'
    CONFIRMATION_REQUIRED = 'confirmation_required'


class HarnessObservation(BaseModel):
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    action_type: HarnessActionType
    permission: ToolPermission
    target: str
    redacted_input: dict[str, Any] = Field(default_factory=dict)
    status: HarnessObservationStatus
    latency_ms: int = 0
    output_summary: str = ''
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


_SENSITIVE_KEY_PARTS = (
    'api_key',
    'apikey',
    'authorization',
    'credential',
    'password',
    'refresh_token',
    'secret',
    'token',
)
_INLINE_SECRET_PATTERN = re.compile(
    r'(?i)\b(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*([^\s,;]+)'
)
# Match credentials embedded in a URL's userinfo component
# (https://user:password@host). Captures the userinfo prefix so we can
# replace it with a redacted marker.
_URL_USERINFO_PATTERN = re.compile(r'([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s@]+:[^/\s@]+@')


def redact_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                redacted[key_text] = '[REDACTED]'
            else:
                redacted[key_text] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        scrubbed = _INLINE_SECRET_PATTERN.sub(r'\1=[REDACTED]', value)
        # Redact URL userinfo AFTER the inline-secret pass so a token-style
        # password still gets handled consistently.
        scrubbed = _URL_USERINFO_PATTERN.sub(r'\1[REDACTED]@', scrubbed)
        return scrubbed
    return value


def summarize_runtime_output(result: Any, *, max_chars: int = 1200) -> str:
    if result is None:
        return ''
    if hasattr(result, 'content'):
        return summarize_tool_output(str(result.content), max_chars=max_chars)
    if hasattr(result, 'output_summary'):
        return summarize_tool_output(str(result.output_summary), max_chars=max_chars)
    return summarize_tool_output(str(result), max_chars=max_chars)


def status_from_runtime_output(result: Any) -> HarnessObservationStatus:
    if result.__class__.__name__ == 'ErrorObservation':
        return HarnessObservationStatus.ERROR
    error = getattr(result, 'error', False)
    if isinstance(error, bool):
        return (
            HarnessObservationStatus.ERROR
            if error
            else HarnessObservationStatus.SUCCESS
        )
    if error:
        return HarnessObservationStatus.ERROR
    return HarnessObservationStatus.SUCCESS


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace('-', '_')
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
