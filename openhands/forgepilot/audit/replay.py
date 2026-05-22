from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, Field

from .schema import AuditEvent, AuditEventType, build_task_evidence_pack
from .timeline import AuditTimeline, build_timeline


class ReplayRiskQueue(BaseModel):
    name: str
    event_ids: list[str] = Field(default_factory=list)
    reason: str


class AuditReplaySummary(BaseModel):
    task_id: str
    event_count: int
    chain_count: int
    total_cost_usd: float
    total_duration_ms: int
    event_types: list[str]
    risk_queues: list[ReplayRiskQueue]
    timeline: AuditTimeline
    audit_jsonl: str

    def render_markdown(self) -> str:
        lines = [
            '# ForgePilot Audit Replay',
            '',
            f'- Task ID: `{self.task_id}`',
            f'- Events: {self.event_count}',
            f'- Chains: {self.chain_count}',
            f'- Total Cost USD: {self.total_cost_usd:.6f}',
            f'- Total Duration MS: {self.total_duration_ms}',
            '',
            '## Event Types',
            '',
        ]
        for event_type in self.event_types:
            lines.append(f'- `{event_type}`')

        lines.extend(['', '## Risk Queues', ''])
        if not self.risk_queues:
            lines.append('No risk queues.')
        for queue in self.risk_queues:
            joined = ', '.join(queue.event_ids) if queue.event_ids else '-'
            lines.append(f'- `{queue.name}`: {queue.reason} ({joined})')

        lines.extend(['', '## Chains', ''])
        for chain in self.timeline.chains:
            labels = ' -> '.join(node.event.event_type.value for node in chain.nodes)
            lines.append(f'- `{chain.chain_id}`: {labels}')
        lines.append('')
        return '\n'.join(lines)


def _risk_queues(events: list[AuditEvent]) -> list[ReplayRiskQueue]:
    approval_requests = [
        event.trace_id
        for event in events
        if event.event_type == AuditEventType.APPROVAL_REQUESTED
    ]
    failed_verifications = [
        event.trace_id
        for event in events
        if event.event_type in {AuditEventType.TEST_RESULT, AuditEventType.VERIFICATION}
        and str(event.payload.get('status', '')).lower() in {'failed', 'fail', 'error'}
    ]
    high_risk_commands = [
        event.trace_id
        for event in events
        if event.event_type in {AuditEventType.COMMAND, AuditEventType.COMMAND_RUN}
        and str(event.payload.get('risk', '')).lower() == 'high'
    ]

    queues: list[ReplayRiskQueue] = []
    if approval_requests:
        queues.append(
            ReplayRiskQueue(
                name='approval_required',
                event_ids=approval_requests,
                reason='Task requested human approval before continuing.',
            )
        )
    if failed_verifications:
        queues.append(
            ReplayRiskQueue(
                name='failed_verification',
                event_ids=failed_verifications,
                reason='Verification or test events reported failure.',
            )
        )
    if high_risk_commands:
        queues.append(
            ReplayRiskQueue(
                name='high_risk_command',
                event_ids=high_risk_commands,
                reason='Command events were marked high risk by policy.',
            )
        )
    return queues


def build_audit_replay_summary(events: Iterable[AuditEvent]) -> AuditReplaySummary:
    event_list = list(events)
    evidence = build_task_evidence_pack(event_list)
    timeline = build_timeline(event_list)
    return AuditReplaySummary(
        task_id=evidence.task_id,
        event_count=evidence.event_count,
        chain_count=len(timeline.chains),
        total_cost_usd=timeline.total_cost_usd,
        total_duration_ms=timeline.total_duration_ms,
        event_types=evidence.event_types,
        risk_queues=_risk_queues(event_list),
        timeline=timeline,
        audit_jsonl=evidence.audit_jsonl,
    )
