"""Tests for HarnessObservation and payload redaction."""

from openhands.forgepilot.harness.action_schema import HarnessActionType
from openhands.forgepilot.harness.observation import (
    HarnessObservation,
    HarnessObservationStatus,
    redact_payload,
)
from openhands.forgepilot.tool_registry.schema import ToolPermission


def test_redact_payload_redacts_url_userinfo():
    """URL userinfo (``https://user:password@host``) must be redacted.

    The previous redaction only matched ``key=value`` and ``key: value``
    pairs, so a credential embedded in a URL's authority component
    leaked into audit logs as a parameter.
    """
    assert (
        redact_payload('https://user:password@host.com/path')
        == 'https://[REDACTED]@host.com/path'
    )
    assert (
        redact_payload('curl https://alice:s3cr3t@example.org/api')
        == 'curl https://[REDACTED]@example.org/api'
    )


def test_redact_payload_preserves_url_without_credentials():
    """URLs without userinfo must be returned unchanged."""
    assert (
        redact_payload('https://example.com/api?q=1') == 'https://example.com/api?q=1'
    )


def test_redact_payload_handles_tuples():
    """Tuples must be treated as sequences, not mappings.

    The redaction walks each element and redacts inline secrets inside
    string items; the result is a list (sequence, not tuple) so callers
    can mutate the redacted value if needed.
    """
    redacted = redact_payload(('api_key=ghp_secret', 'visible'))
    assert redacted == ['api_key=[REDACTED]', 'visible']
    assert isinstance(redacted, list)


def test_redact_payload_does_not_mutate_input():
    """Redaction must be a pure projection; the original payload stays intact."""
    payload = {
        'api_key': 'ghp_secret',
        'nested': {'password': 'hunter2', 'safe': 'value'},
    }
    snapshot = {
        'api_key': 'ghp_secret',
        'nested': {'password': 'hunter2', 'safe': 'value'},
    }
    redact_payload(payload)
    assert payload == snapshot


def test_harness_observation_default_trace_id_is_unique():
    """Two fresh observations must have independent trace ids.

    A shared default would collapse unrelated events on the audit timeline
    into a single node — exactly the bug fixed in the event-stream audit
    by ``assign_unique_node_ids``.
    """
    a = HarnessObservation(
        action_type=HarnessActionType.FILE_READ,
        permission=ToolPermission.READ,
        target='a.md',
        status=HarnessObservationStatus.SUCCESS,
    )
    b = HarnessObservation(
        action_type=HarnessActionType.FILE_READ,
        permission=ToolPermission.READ,
        target='b.md',
        status=HarnessObservationStatus.SUCCESS,
    )
    assert a.trace_id != b.trace_id
