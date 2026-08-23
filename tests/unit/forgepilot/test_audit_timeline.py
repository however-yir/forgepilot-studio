"""Tests for the unified audit timeline builder (B-15)."""

from datetime import UTC, datetime

from openhands.forgepilot.audit.schema import AuditEvent, AuditEventType
from openhands.forgepilot.audit.timeline import build_timeline


def _make_event(
    trace_id: str,
    event_type: AuditEventType,
    task_id: str = 'task-1',
    phase: str = 'execute',
    timestamp: datetime | None = None,
    payload: dict | None = None,
) -> AuditEvent:
    return AuditEvent(
        trace_id=trace_id,
        task_id=task_id,
        event_type=event_type,
        phase=phase,
        timestamp=timestamp or datetime.now(UTC),
        summary=f'{event_type.value} event',
        payload=payload or {},
    )


def test_build_timeline_creates_chains():
    now = datetime.now(UTC)
    events = [
        _make_event('e1', AuditEventType.MODEL, timestamp=now),
        _make_event('e2', AuditEventType.COMMAND, timestamp=now),
        _make_event('e3', AuditEventType.FILE_CHANGE, timestamp=now),
        _make_event('e4', AuditEventType.VERIFICATION, timestamp=now),
    ]
    timeline = build_timeline(events)
    assert len(timeline.chains) >= 1
    assert timeline.task_id == 'task-1'
    assert timeline.total_cost_usd == 0.0


def test_build_timeline_links_unified_audit_event_types():
    now = datetime.now(UTC)
    events = [
        _make_event('e1', AuditEventType.MODEL_RESPONSE, timestamp=now),
        _make_event('e2', AuditEventType.COMMAND_RUN, timestamp=now),
        _make_event('e3', AuditEventType.FILE_CHANGE, timestamp=now),
        _make_event('e4', AuditEventType.TEST_RESULT, timestamp=now),
    ]

    timeline = build_timeline(events)
    chain_nodes = timeline.chains[0].nodes
    assert [node.event.event_type for node in chain_nodes] == [
        AuditEventType.MODEL_RESPONSE,
        AuditEventType.COMMAND_RUN,
        AuditEventType.FILE_CHANGE,
        AuditEventType.TEST_RESULT,
    ]


def test_build_timeline_empty_events():
    timeline = build_timeline([])
    assert timeline.chains == []
    assert 'No events' in timeline.summary


def test_timeline_with_orphan_nodes():
    now = datetime.now(UTC)
    events = [
        _make_event('e1', AuditEventType.MODEL, timestamp=now),
        _make_event('e2', AuditEventType.REPORT, timestamp=now),
    ]
    timeline = build_timeline(events)
    # MODEL events that don't trigger anything end up as roots or orphans
    assert timeline.summary  # should produce a summary


def test_build_timeline_preserves_events_sharing_trace_id():
    """Events from the same LLM response share a trace_id — none may be lost.

    function_calling assigns one response_id to every action of a response, so
    real streams contain MODEL_RESPONSE/COMMAND_RUN/FILE_CHANGE events with
    identical trace_ids. The timeline must keep all of them as distinct nodes.
    """
    now = datetime.now(UTC)
    shared = 'resp-1'
    events = [
        _make_event(shared, AuditEventType.MODEL_RESPONSE, timestamp=now),
        _make_event(
            shared, AuditEventType.COMMAND_RUN, timestamp=now, payload={'command': 'ls'}
        ),
        _make_event(
            shared, AuditEventType.FILE_CHANGE, timestamp=now, payload={'path': 'a.py'}
        ),
        _make_event(
            shared,
            AuditEventType.TEST_RESULT,
            timestamp=now,
            payload={'exit_code': 0},
        ),
    ]

    timeline = build_timeline(events)

    all_nodes = [node for chain in timeline.chains for node in chain.nodes]
    all_nodes += timeline.orphan_nodes
    assert len(all_nodes) == 4, 'every event must survive as its own node'

    node_ids = [node.node_id for node in all_nodes]
    assert len(set(node_ids)) == 4, 'node ids must be unique despite shared trace_id'

    event_types = [node.event.event_type for node in all_nodes]
    assert set(event_types) == {
        AuditEventType.MODEL_RESPONSE,
        AuditEventType.COMMAND_RUN,
        AuditEventType.FILE_CHANGE,
        AuditEventType.TEST_RESULT,
    }


def test_assign_unique_node_ids_suffixes_repeated_trace_ids():
    from openhands.forgepilot.audit.timeline import assign_unique_node_ids

    now = datetime.now(UTC)
    events = [
        _make_event('resp-1', AuditEventType.MODEL_RESPONSE, timestamp=now),
        _make_event('resp-1', AuditEventType.COMMAND_RUN, timestamp=now),
        _make_event('resp-2', AuditEventType.COMMAND_RUN, timestamp=now),
        _make_event('resp-1', AuditEventType.FILE_CHANGE, timestamp=now),
    ]

    identified = assign_unique_node_ids(events)

    assert [node_id for node_id, _ in identified] == [
        'resp-1',
        'resp-1#2',
        'resp-2',
        'resp-1#3',
    ]
