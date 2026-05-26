from __future__ import annotations

import shlex
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, Field

from openhands.forgepilot.tool_registry.schema import ToolPermission


class HarnessActionType(str, Enum):
    TERMINAL = 'terminal'
    FILE_READ = 'file_read'
    FILE_WRITE = 'file_write'
    FILE_PATCH = 'file_patch'
    GIT = 'git'
    MCP_TOOL = 'mcp_tool'
    UNKNOWN = 'unknown'


class HarnessAction(BaseModel):
    action_type: HarnessActionType
    permission: ToolPermission
    target: str
    input: dict[str, Any] = Field(default_factory=dict)
    raw_action_name: str = ''
    requires_confirmation: bool = False

    @property
    def confirmation_subject(self) -> str:
        return f'{self.action_type.value}:{self.target}'


def action_from_runtime_action(
    action: Any,
    *,
    mcp_permissions: Mapping[str, str | ToolPermission | Mapping[str, Any]]
    | None = None,
) -> HarnessAction:
    action_name = action.__class__.__name__

    if action_name == 'CmdRunAction':
        command = str(getattr(action, 'command', ''))
        action_type = (
            HarnessActionType.GIT
            if _is_git_command(command)
            else HarnessActionType.TERMINAL
        )
        return HarnessAction(
            action_type=action_type,
            permission=ToolPermission.EXECUTE,
            target=_target_from_command(command, getattr(action, 'cwd', None)),
            input={
                'command': command,
                'cwd': getattr(action, 'cwd', None),
                'blocking': getattr(action, 'blocking', False),
                'is_input': getattr(action, 'is_input', False),
            },
            raw_action_name=action_name,
            requires_confirmation=True,
        )

    if action_name == 'FileReadAction':
        path = str(getattr(action, 'path', ''))
        return HarnessAction(
            action_type=HarnessActionType.FILE_READ,
            permission=ToolPermission.READ,
            target=path,
            input={
                'path': path,
                'start': getattr(action, 'start', 0),
                'end': getattr(action, 'end', -1),
            },
            raw_action_name=action_name,
        )

    if action_name == 'FileWriteAction':
        path = str(getattr(action, 'path', ''))
        return HarnessAction(
            action_type=HarnessActionType.FILE_WRITE,
            permission=ToolPermission.WRITE,
            target=path,
            input={
                'path': path,
                'content': getattr(action, 'content', ''),
                'start': getattr(action, 'start', 0),
                'end': getattr(action, 'end', -1),
            },
            raw_action_name=action_name,
            requires_confirmation=True,
        )

    if action_name == 'FileEditAction':
        path = str(getattr(action, 'path', ''))
        return HarnessAction(
            action_type=HarnessActionType.FILE_PATCH,
            permission=ToolPermission.WRITE,
            target=path,
            input={
                'path': path,
                'command': getattr(action, 'command', ''),
                'content': getattr(action, 'content', ''),
                'file_text': getattr(action, 'file_text', None),
                'old_str': getattr(action, 'old_str', None),
                'new_str': getattr(action, 'new_str', None),
                'insert_line': getattr(action, 'insert_line', None),
            },
            raw_action_name=action_name,
            requires_confirmation=True,
        )

    if action_name == 'MCPAction':
        tool_name = str(getattr(action, 'name', ''))
        permission = mcp_permission_from_mapping(tool_name, mcp_permissions)
        return HarnessAction(
            action_type=HarnessActionType.MCP_TOOL,
            permission=permission,
            target=tool_name,
            input={
                'name': tool_name,
                'arguments': getattr(action, 'arguments', {}),
            },
            raw_action_name=action_name,
            requires_confirmation=permission
            in {ToolPermission.EXECUTE, ToolPermission.CONFIRM},
        )

    return HarnessAction(
        action_type=HarnessActionType.UNKNOWN,
        permission=ToolPermission.READ,
        target=action_name,
        input={'repr': repr(action)},
        raw_action_name=action_name,
    )


def mcp_permission_from_mapping(
    tool_name: str,
    permissions: Mapping[str, str | ToolPermission | Mapping[str, Any]] | None,
    *,
    default: ToolPermission = ToolPermission.READ,
) -> ToolPermission:
    if not permissions:
        return default

    for key in _mcp_lookup_keys(tool_name):
        if key not in permissions:
            continue
        value = permissions[key]
        if isinstance(value, Mapping):
            value = value.get('permission', default)
        return _coerce_permission(value, default=default)

    return default


def _mcp_lookup_keys(tool_name: str) -> tuple[str, ...]:
    keys = [tool_name]
    for separator in ('.', ':', '/', '__'):
        if separator in tool_name:
            keys.append(tool_name.split(separator, 1)[0])
    return tuple(dict.fromkeys(keys))


def _coerce_permission(
    value: str | ToolPermission | object,
    *,
    default: ToolPermission,
) -> ToolPermission:
    if isinstance(value, ToolPermission):
        return value
    if isinstance(value, str):
        try:
            return ToolPermission(value)
        except ValueError:
            return default
    return default


def _is_git_command(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.strip().split()
    if not parts:
        return False
    return parts[0] == 'git' or parts[0].endswith('/git')


def _target_from_command(command: str, cwd: str | None) -> str:
    prefix = f'{cwd}: ' if cwd else ''
    return f'{prefix}{command}'.strip()
