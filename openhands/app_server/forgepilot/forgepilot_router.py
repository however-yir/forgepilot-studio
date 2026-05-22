from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from openhands.app_server.utils.dependencies import get_dependencies
from openhands.events.event_filter import EventFilter
from openhands.events.event_store import EventStore
from openhands.forgepilot.audit import (
    audit_events_from_event_stream,
    build_task_evidence_pack,
)
from openhands.forgepilot.tool_registry import ToolRegistry
from openhands.server.shared import file_store

router = APIRouter(
    prefix='/forgepilot',
    tags=['ForgePilot'],
    dependencies=get_dependencies(),
)


@router.get('/audit/export/{conversation_id}')
async def export_audit_jsonl(
    conversation_id: str,
    task_id: str | None = Query(default=None),
) -> PlainTextResponse:
    try:
        event_store = EventStore(
            sid=conversation_id,
            file_store=file_store,
            user_id=None,
        )
        events = list(
            event_store.search_events(filter=EventFilter(exclude_hidden=True))
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Conversation {conversation_id} was not found.',
        ) from exc

    audit_events = audit_events_from_event_stream(
        events, task_id=task_id or conversation_id
    )
    pack = build_task_evidence_pack(audit_events, task_id=task_id or conversation_id)
    filename = f'{conversation_id}-audit.jsonl'
    return PlainTextResponse(
        pack.audit_jsonl,
        media_type='application/x-ndjson',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.get('/tool-registry')
async def list_tool_registry() -> list[dict[str, object]]:
    registry = ToolRegistry.from_builtin_templates()
    return [registry.preview_schema(entry.tool_id) for entry in registry.list_entries()]
