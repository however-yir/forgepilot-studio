from datetime import UTC, datetime, timedelta

from openhands.forgepilot.audit.schema import (
    AuditEvent,
    AuditEventType,
    build_task_evidence_pack,
    export_audit_events_csv,
    export_audit_events_jsonl,
    ordered_timeline,
)


def test_ordered_timeline_sorts_by_timestamp():
    now = datetime.now(UTC)
    late = AuditEvent(
        trace_id='trace-1',
        event_type=AuditEventType.REPORT,
        summary='final report',
        timestamp=now + timedelta(seconds=10),
    )
    early = AuditEvent(
        trace_id='trace-1',
        event_type=AuditEventType.COMMAND,
        summary='run tests',
        timestamp=now,
    )

    timeline = ordered_timeline([late, early])
    assert [event.summary for event in timeline] == ['run tests', 'final report']


def test_export_audit_events_jsonl():
    event = AuditEvent(
        trace_id='trace-jsonl',
        task_id='task-42',
        event_type=AuditEventType.TOOL_CALL,
        phase='execute',
        summary='invoke github connector',
        payload={'tool': 'github', 'status': 'ok'},
        duration_ms=321,
        cost_usd=0.003,
    )

    content = export_audit_events_jsonl([event])
    assert '"trace_id": "trace-jsonl"' in content
    assert '"event_type": "tool_call"' in content
    assert '"tool": "github"' in content


def test_export_audit_events_csv():
    event = AuditEvent(
        trace_id='trace-csv',
        event_type=AuditEventType.VERIFICATION,
        phase='verify',
        summary='pytest -q',
        payload={'exit_code': 0},
    )

    content = export_audit_events_csv([event])
    lines = content.strip().splitlines()
    assert lines[0].startswith('trace_id,task_id,event_type')
    assert 'trace-csv' in lines[1]
    assert 'verification' in lines[1]


def test_task_evidence_pack_contains_full_jsonl_export():
    events = [
        AuditEvent(
            trace_id='trace-task',
            task_id='task-99',
            event_type=AuditEventType.TASK_CREATED,
            summary='create task',
        ),
        AuditEvent(
            trace_id='trace-test',
            task_id='task-99',
            event_type=AuditEventType.TEST_RESULT,
            summary='pytest passed',
            payload={'command': 'pytest -q', 'exit_code': 0},
        ),
    ]

    pack = build_task_evidence_pack(events)
    exported = pack.model_dump_for_export()
    assert pack.task_id == 'task-99'
    assert pack.event_count == 2
    assert 'task_created' in pack.event_types
    assert '"event_type": "test_result"' in exported['audit_jsonl']


# ── L-1: CSV formula injection protection ───────────


def test_export_audit_events_csv_neutralizes_formula_cells():
    malicious = AuditEvent(
        trace_id='=cmd|"/c calc"!A1',
        event_type=AuditEventType.COMMAND,
        summary='=HYPERLINK("http://evil.example", "click")',
        payload={'command': '+SUM(1,2)', 'injection': '@evil'},
    )

    content = export_audit_events_csv([malicious])
    data_line = content.strip().splitlines()[1]

    import csv

    row = next(csv.reader([data_line]))
    # Cells starting with a formula character must be neutralized.
    assert row[0] == '\'=cmd|"/c calc"!A1'
    assert row[5].startswith("'=HYPERLINK")
    # The payload cell itself starts with '{' so it is not a formula cell;
    # embedded formula-looking text inside a non-formula cell is inert.
    assert row[8].startswith('{')


def test_export_audit_events_csv_leaves_normal_cells_untouched():
    event = AuditEvent(
        trace_id='trace-normal',
        event_type=AuditEventType.REPORT,
        summary='all good',
        payload={'ok': True},
    )
    content = export_audit_events_csv([event])
    assert 'trace-normal' in content
    assert "'trace-normal" not in content


# ── L-4: json.dumps fallback for non-serializable payloads ──


def test_export_audit_events_jsonl_tolerates_non_serializable_payloads():
    now = datetime.now(UTC)
    event = AuditEvent(
        trace_id='trace-exotic',
        event_type=AuditEventType.TOOL_CALL,
        summary='tool with exotic payload',
        timestamp=now,
        payload={
            'raw_object': object(),
            'raw_datetime': now,
            'error': ValueError('boom'),
        },
    )

    content = export_audit_events_jsonl([event])  # must not raise TypeError
    assert '"trace_id": "trace-exotic"' in content


def test_task_evidence_pack_survives_exotic_payloads():
    event = AuditEvent(
        trace_id='trace-exotic-2',
        event_type=AuditEventType.MODEL,
        summary='model output',
        payload={'blob': object()},
    )
    pack = build_task_evidence_pack([event])
    assert pack.event_count == 1
    assert 'trace-exotic-2' in pack.audit_jsonl
