"""Unified audit timeline builder.

Connects commands, file modifications, model responses, and tool calls into
a correlated causal chain view for the audit replay dashboard.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import datetime
from typing import Any, Iterable

from pydantic import BaseModel, Field

from .schema import AuditEvent, AuditEventType, ordered_timeline


class TimelineLink(BaseModel):
    """A causal link between two timeline events."""

    source_id: str
    target_id: str
    relation: str  # 'triggered', 'produced', 'verified', 'reported'
    detail: str = ''


class TimelineNode(BaseModel):
    """A single node in the unified audit timeline."""

    event: AuditEvent
    node_id: str = ''
    parent_ids: list[str] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)
    depth: int = 0
    chain_label: str = ''  # e.g. "Round 1", "Self-heal A"

    def model_post_init(self, __context: Any) -> None:
        if not self.node_id:
            self.node_id = self.event.trace_id


class TimelineChain(BaseModel):
    """A linear causal chain: idea → model → command → file changes → verification."""

    chain_id: str
    nodes: list[TimelineNode]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    self_heal_round: int = 0


class AuditTimeline(BaseModel):
    """Unified audit timeline for a task."""

    task_id: str
    chains: list[TimelineChain]
    orphan_nodes: list[TimelineNode] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    summary: str = ''


_CORRELATION_WINDOW_MS = 5000  # events within this window may be causally linked
_MODEL_EVENT_TYPES = {AuditEventType.MODEL, AuditEventType.MODEL_RESPONSE}
_COMMAND_EVENT_TYPES = {AuditEventType.COMMAND, AuditEventType.COMMAND_RUN}
_VERIFICATION_EVENT_TYPES = {AuditEventType.VERIFICATION, AuditEventType.TEST_RESULT}


def assign_unique_node_ids(
    events: Iterable[AuditEvent],
) -> list[tuple[str, AuditEvent]]:
    """Pair each event with a stable, unique node id.

    ``trace_id`` is only a correlation key: every action emitted from the same
    LLM response shares it, so it cannot identify a timeline node by itself.
    Repeated trace ids get an ``#<occurrence>`` suffix in chronological order;
    ids are deterministic for the same input sequence.
    """
    occurrences: Counter[str] = Counter()
    identified: list[tuple[str, AuditEvent]] = []
    for event in ordered_timeline(events):
        occurrences[event.trace_id] += 1
        count = occurrences[event.trace_id]
        node_id = event.trace_id if count == 1 else f'{event.trace_id}#{count}'
        identified.append((node_id, event))
    return identified


class _RecentEvents:
    """Bounded, time-ordered buffer of recent (node_id, timestamp) pairs.

    Entries older than the correlation window relative to the newest event are
    pruned on push, which keeps ``build_timeline`` linear instead of rescanning
    every historical event for each new one.
    """

    def __init__(self, window_ms: int) -> None:
        self._window_ms = window_ms
        self._entries: deque[tuple[str, datetime]] = deque()

    def push(self, node_id: str, timestamp: datetime) -> None:
        self._prune(timestamp)
        self._entries.append((node_id, timestamp))

    def latest_within_window(self, timestamp: datetime) -> str | None:
        """Return the most recent entry within the window, if any."""
        self._prune(timestamp)
        if not self._entries:
            return None
        return self._entries[-1][0]

    def _prune(self, now: datetime) -> None:
        while self._entries:
            delta_ms = (now - self._entries[0][1]).total_seconds() * 1000
            if delta_ms < 0 or delta_ms <= self._window_ms:
                break
            self._entries.popleft()


def _find_preceding(
    event: AuditEvent,
    recent_events: list[AuditEvent],
) -> list[str]:
    """Find preceding events that likely caused this event."""
    parents: list[str] = []
    for prev in reversed(recent_events):
        delta = (event.timestamp - prev.timestamp).total_seconds() * 1000
        if delta < 0 or delta > _CORRELATION_WINDOW_MS:
            continue
        # model responses trigger commands and tool calls
        if prev.event_type in _MODEL_EVENT_TYPES and event.event_type in {
            AuditEventType.COMMAND_RUN,
            AuditEventType.COMMAND,
            AuditEventType.TOOL_CALL,
        }:
            parents.append(prev.trace_id)
        # commands produce file changes
        elif (
            prev.event_type in _COMMAND_EVENT_TYPES
            and event.event_type == AuditEventType.FILE_CHANGE
        ):
            parents.append(prev.trace_id)
        # verifications follow commands
        elif (
            prev.event_type in _COMMAND_EVENT_TYPES
            and event.event_type in _VERIFICATION_EVENT_TYPES
        ):
            parents.append(prev.trace_id)
    return parents


def build_timeline(events: Iterable[AuditEvent]) -> AuditTimeline:
    """Build a unified timeline from raw audit events.

    Correlates model responses → commands → file modifications → verification
    into causal chains suitable for the audit replay dashboard.
    """
    identified = assign_unique_node_ids(events)
    if not identified:
        return AuditTimeline(task_id='', chains=[], summary='No events recorded.')

    task_id = identified[0][1].task_id or ''

    # Build nodes with parent-child relationships
    nodes_by_id: dict[str, TimelineNode] = {}
    recent_command = _RecentEvents(_CORRELATION_WINDOW_MS)
    recent_model = _RecentEvents(_CORRELATION_WINDOW_MS)

    for node_id, event in identified:
        parents: list[str] = []
        chain_label = ''

        if event.event_type in _COMMAND_EVENT_TYPES:
            parent = recent_model.latest_within_window(event.timestamp)
            if parent is not None:
                parents.append(parent)
            recent_command.push(node_id, event.timestamp)
        elif event.event_type == AuditEventType.FILE_CHANGE:
            parent = recent_command.latest_within_window(event.timestamp)
            if parent is not None:
                parents.append(parent)
        elif event.event_type in _VERIFICATION_EVENT_TYPES:
            parent = recent_command.latest_within_window(event.timestamp)
            if parent is not None:
                parents.append(parent)
                chain_label = 'verify'
        elif event.event_type in _MODEL_EVENT_TYPES:
            recent_model.push(node_id, event.timestamp)
        elif event.event_type == AuditEventType.TOOL_CALL:
            parent = recent_model.latest_within_window(event.timestamp)
            if parent is not None:
                parents.append(parent)

        node = TimelineNode(
            event=event,
            node_id=node_id,
            parent_ids=parents,
            chain_label=chain_label,
        )
        nodes_by_id[node_id] = node

    # Wire up child references
    for node in nodes_by_id.values():
        for pid in node.parent_ids:
            if pid in nodes_by_id:
                nodes_by_id[pid].child_ids.append(node.node_id)

    # Build chains by walking from root nodes (no parents) downward
    chains: list[TimelineChain] = []
    visited: set[str] = set()

    def walk_chain(start_id: str) -> list[TimelineNode]:
        chain_nodes: list[TimelineNode] = []
        stack = [start_id]
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            if nid not in nodes_by_id:
                continue
            node = nodes_by_id[nid]
            chain_nodes.append(node)
            stack.extend(reversed(node.child_ids))
        return chain_nodes

    chain_idx = 0
    for node in nodes_by_id.values():
        if not node.parent_ids and node.node_id not in visited:
            chain_nodes = walk_chain(node.node_id)
            if chain_nodes:
                chain_idx += 1
                chain = TimelineChain(
                    chain_id=f'chain-{chain_idx:03d}',
                    nodes=chain_nodes,
                    started_at=chain_nodes[0].event.timestamp,
                    completed_at=chain_nodes[-1].event.timestamp,
                )
                chains.append(chain)

    # Collect orphans
    orphan_nodes = [n for n in nodes_by_id.values() if n.node_id not in visited]

    # Compute aggregates
    total_cost = sum(
        event.cost_usd for _, event in identified if event.cost_usd is not None
    )
    total_duration = sum(
        event.duration_ms for _, event in identified if event.duration_ms is not None
    )

    # Build summary
    event_counts: dict[str, int] = defaultdict(int)
    for _, event in identified:
        event_counts[event.event_type.value] += 1
    summary_parts = [f'{v} {k}' for k, v in event_counts.items()]
    summary = f'{len(chains)} chains: {", ".join(summary_parts)}'

    return AuditTimeline(
        task_id=task_id,
        chains=chains,
        orphan_nodes=orphan_nodes,
        total_cost_usd=total_cost,
        total_duration_ms=total_duration,
        summary=summary,
    )
