from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, Field


class AuditEventType(str, Enum):
    TASK_CREATED = 'task_created'
    USER_MESSAGE = 'user_message'
    MODEL_RESPONSE = 'model_response'
    COMMAND_RUN = 'command_run'
    TEST_RESULT = 'test_result'
    APPROVAL_REQUESTED = 'approval_requested'
    APPROVAL_DECISION = 'approval_decision'
    MODEL = 'model'
    COMMAND = 'command'
    FILE_CHANGE = 'file_change'
    TOOL_CALL = 'tool_call'
    VERIFICATION = 'verification'
    REPORT = 'report'


class AuditEvent(BaseModel):
    trace_id: str
    task_id: str | None = None
    event_type: AuditEventType
    phase: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None
    cost_usd: float | None = None

    def model_dump_for_export(self) -> dict[str, Any]:
        return {
            'trace_id': self.trace_id,
            'task_id': self.task_id or '',
            'event_type': self.event_type.value,
            'phase': self.phase or '',
            'timestamp': self.timestamp.isoformat(),
            'summary': self.summary,
            'duration_ms': self.duration_ms or '',
            'cost_usd': self.cost_usd if self.cost_usd is not None else '',
            'payload': self.payload,
        }


class TaskEvidencePack(BaseModel):
    task_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_count: int
    event_types: list[str]
    audit_jsonl: str
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None

    def model_dump_for_export(self) -> dict[str, Any]:
        return {
            'task_id': self.task_id,
            'generated_at': self.generated_at.isoformat(),
            'event_count': self.event_count,
            'event_types': self.event_types,
            'first_event_at': self.first_event_at.isoformat()
            if self.first_event_at
            else '',
            'last_event_at': self.last_event_at.isoformat()
            if self.last_event_at
            else '',
            'audit_jsonl': self.audit_jsonl,
        }


def ordered_timeline(events: Iterable[AuditEvent]) -> list[AuditEvent]:
    return sorted(events, key=lambda event: event.timestamp)


def export_audit_events_jsonl(events: Iterable[AuditEvent]) -> str:
    lines: list[str] = []
    for event in ordered_timeline(events):
        row = event.model_dump_for_export()
        # default=str keeps export working when payloads carry values that
        # json cannot serialize natively (enums, datetimes, exceptions).
        lines.append(json.dumps(row, ensure_ascii=False, default=str))
    return '\n'.join(lines)


# Characters that spreadsheet applications interpret as formula starters.
# Prefixing them prevents CSV formula injection when exports are opened in
# Excel / Google Sheets / LibreOffice.
_CSV_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _sanitize_csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def export_audit_events_csv(events: Iterable[AuditEvent]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            'trace_id',
            'task_id',
            'event_type',
            'phase',
            'timestamp',
            'summary',
            'duration_ms',
            'cost_usd',
            'payload',
        ],
    )
    writer.writeheader()

    for event in ordered_timeline(events):
        row = event.model_dump_for_export()
        row['payload'] = json.dumps(row['payload'], ensure_ascii=False, default=str)
        row = {key: _sanitize_csv_cell(value) for key, value in row.items()}
        writer.writerow(row)

    return output.getvalue()


def build_task_evidence_pack(
    events: Iterable[AuditEvent],
    *,
    task_id: str | None = None,
) -> TaskEvidencePack:
    timeline = ordered_timeline(events)
    if task_id:
        inferred_task_id = task_id
    else:
        inferred_task_id = next(
            (event.task_id or '' for event in timeline if event.task_id),
            '',
        )
    return TaskEvidencePack(
        task_id=inferred_task_id,
        event_count=len(timeline),
        event_types=sorted({event.event_type.value for event in timeline}),
        first_event_at=timeline[0].timestamp if timeline else None,
        last_event_at=timeline[-1].timestamp if timeline else None,
        audit_jsonl=export_audit_events_jsonl(timeline),
    )
