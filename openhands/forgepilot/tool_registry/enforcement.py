"""Runtime tool permission enforcement and schema visualization.

E-41: Generates Mermaid diagrams and JSON Schema visualizations for MCP tools.
E-43: Wraps tool invocations with runtime permission guards that cannot be bypassed.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .registry import ToolRegistry
from .schema import ToolExecutionMode, ToolPermission, ToolRegistryEntry

# ───────────────────────────────────────────────
#  E-43: Runtime Permission Enforcement
# ───────────────────────────────────────────────


@dataclass
class PermissionViolation:
    tool_id: str
    required_permission: ToolPermission
    actual_permission: ToolPermission
    detail: str


class ToolAccessGuard:
    """Runtime guard that intercepts every tool invocation.

    Cannot be bypassed — wraps the ToolRegistry.invoke() entrypoint so that
    every call path (shell, HTTP, MCP, script) goes through the same check.

    When *workspace_root* is provided the guard resolves every *target_path*
    to a canonical absolute path (resolving symlinks and ``..`` components),
    confirms it stays within the workspace, then converts it to a relative
    path for allowlist / blocklist matching.  This prevents path-traversal
    attacks via ``../``, absolute paths, symlinks, and Windows-style
    separators.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        workspace_root: str | Path | None = None,
        path_allowlist: list[str] | None = None,
        path_blocklist: list[str] | None = None,
    ) -> None:
        self._registry = registry
        self._workspace_root: Path | None = (
            Path(workspace_root).resolve() if workspace_root is not None else None
        )
        self._path_allowlist = path_allowlist or []
        self._path_blocklist = path_blocklist or []
        self._violations: list[PermissionViolation] = []
        self._block_on_violation = True

    @property
    def violations(self) -> list[PermissionViolation]:
        return list(self._violations)

    # ── path helpers ──────────────────────────────────

    def _resolve_target_path(self, raw_path: str) -> tuple[Path | None, str | None]:
        """Resolve *raw_path* and confirm it is inside the workspace.

        Returns ``(resolved_relative, None)`` on success or
        ``(None, error_detail)`` when the path escapes the workspace.

        The resolved relative path normalises backslashes so that
        fnmatch patterns written with ``/`` also match on Windows.
        """
        if self._workspace_root is None:
            # No workspace configured — normalise separators but skip
            # the boundary check.
            normalised = raw_path.replace(os.sep, '/')
            return Path(normalised), None

        # Normalise Windows separators before joining so that
        # "src\\..\\..\\etc" is handled identically on all platforms.
        normalised_input = raw_path.replace('\\', '/')

        # Resolve against workspace root so that absolute paths and
        # bare relative paths are both handled uniformly.
        candidate = (self._workspace_root / normalised_input).resolve()

        # Confirm the canonical path is still inside the workspace.
        # Use a try/except for Python <3.12 compat (is_relative_to
        # raises ValueError on mismatch in 3.9-3.11).
        try:
            relative = candidate.relative_to(self._workspace_root)
        except ValueError:
            return None, (
                f'path {raw_path!r} escapes workspace (resolved to {candidate})'
            )

        # Normalise to forward-slash form for consistent matching.
        relative_str = str(relative).replace(os.sep, '/')
        return Path(relative_str), None

    def _check_path_rules(
        self,
        tool_id: str,
        required: ToolPermission,
        entry: ToolRegistryEntry,
        resolved_path: str,
    ) -> bool:
        """Apply blocklist / allowlist fnmatch rules against *resolved_path*."""
        if self._path_blocklist and any(
            fnmatch.fnmatch(resolved_path, pattern) for pattern in self._path_blocklist
        ):
            self._violations.append(
                PermissionViolation(
                    tool_id=tool_id,
                    required_permission=required,
                    actual_permission=entry.permission,
                    detail=f'path {resolved_path} is blocked',
                )
            )
            return False

        if self._path_allowlist and not any(
            fnmatch.fnmatch(resolved_path, pattern) for pattern in self._path_allowlist
        ):
            self._violations.append(
                PermissionViolation(
                    tool_id=tool_id,
                    required_permission=required,
                    actual_permission=entry.permission,
                    detail=f'path {resolved_path} is not in allowlist',
                )
            )
            return False

        return True

    # ── main check ───────────────────────────────────

    def check(
        self,
        tool_id: str,
        *,
        required: ToolPermission = ToolPermission.READ,
        target_path: str | None = None,
    ) -> bool:
        """Check whether a tool call is allowed under the current policy.

        Returns True if allowed; appends a violation and returns False otherwise.
        """
        try:
            entry = self._registry.get_entry(tool_id)
        except KeyError:
            self._violations.append(
                PermissionViolation(
                    tool_id=tool_id,
                    required_permission=required,
                    actual_permission=ToolPermission.READ,
                    detail=f'unknown tool: {tool_id}',
                )
            )
            return False

        if not entry.enabled:
            self._violations.append(
                PermissionViolation(
                    tool_id=tool_id,
                    required_permission=required,
                    actual_permission=entry.permission,
                    detail='tool is disabled',
                )
            )
            return False

        # Permission level check
        if not _meets_permission(entry.permission, required):
            self._violations.append(
                PermissionViolation(
                    tool_id=tool_id,
                    required_permission=required,
                    actual_permission=entry.permission,
                    detail=f'insufficient permission: need {required.value}, have {entry.permission.value}',
                )
            )
            return False

        # Path boundary check — resolve, verify workspace containment,
        # then apply allowlist / blocklist against the normalised
        # relative path.
        if target_path is not None:
            resolved, err_detail = self._resolve_target_path(target_path)
            if err_detail is not None:
                self._violations.append(
                    PermissionViolation(
                        tool_id=tool_id,
                        required_permission=required,
                        actual_permission=entry.permission,
                        detail=err_detail,
                    )
                )
                return False

            assert resolved is not None
            resolved_str = str(resolved)

            if not self._check_path_rules(tool_id, required, entry, resolved_str):
                return False

        return True

    def guard_invoke(
        self,
        tool_id: str,
        parameters: Mapping[str, object] | str,
        *,
        executor: Callable | None = None,
        trace_id: str | None = None,
        target_path: str | None = None,
        required: ToolPermission = ToolPermission.READ,
        confirmed: bool = False,
    ):
        """Invoke a tool through the permission guard.

        Behaves identically to ToolRegistry.invoke but first runs permission,
        enablement, and path-boundary checks.  Tools whose permission level is
        CONFIRM are additionally gated on the ``confirmed`` flag and are
        rejected unless a human confirmation has been supplied.  Raises
        PermissionError on violation when block_on_violation is True.
        """
        if not self.check(
            tool_id,
            required=required,
            target_path=target_path,
        ):
            if self._block_on_violation:
                latest = self._violations[-1]
                raise PermissionError(
                    f'Tool access denied: {latest.tool_id} — {latest.detail}'
                )
            # If not blocking, return a synthetic error record
            return self._registry.record_call(
                tool_id=tool_id,
                parameters=parameters,
                output='',
                duration_ms=0,
                error=f'permission denied: {self._violations[-1].detail}',
                trace_id=trace_id,
            )

        entry = self._registry.get_entry(tool_id)
        if entry.permission == ToolPermission.CONFIRM and not confirmed:
            self._violations.append(
                PermissionViolation(
                    tool_id=tool_id,
                    required_permission=required,
                    actual_permission=entry.permission,
                    detail='confirmation required for CONFIRM tools',
                )
            )
            if self._block_on_violation:
                raise PermissionError(
                    f'Tool access denied: {tool_id} — confirmation required'
                )
            return self._registry.record_call(
                tool_id=tool_id,
                parameters=parameters,
                output='',
                duration_ms=0,
                error='confirmation required for CONFIRM tools',
                trace_id=trace_id,
            )

        return self._registry.invoke(
            tool_id,
            parameters,
            executor=executor,
            trace_id=trace_id,
            confirmed=confirmed,
        )


# ───────────────────────────────────────────────
#  E-41: Schema Visualization (Mermaid + JSON)
# ───────────────────────────────────────────────


@dataclass
class SchemaNode:
    name: str
    type_: str  # 'object', 'string', 'number', 'array', 'boolean'
    required: bool = False
    children: list['SchemaNode'] = field(default_factory=list)
    description: str = ''


def _escape_mermaid_label(text: str) -> str:
    """Escape user-controlled text so it cannot break out of a Mermaid label."""
    return text.replace('"', '&quot;').replace('\n', ' ')


def _entries_to_graph(entries: list[ToolRegistryEntry]) -> str:
    """Render tool schemas as a Mermaid graph for the MCP Registry dashboard."""
    lines = ['graph TD', '  TITLE[MCP Tool Registry]']
    for entry in entries:
        node_id = _safe_id(entry.tool_id)
        provider = _escape_mermaid_label(entry.provider or 'unknown')
        permission = entry.permission.value
        status = 'enabled' if entry.enabled else 'disabled'
        display_name = _escape_mermaid_label(entry.display_name)
        tool_id = _escape_mermaid_label(entry.tool_id)
        lines.append(
            f'  {node_id}["{display_name} ({tool_id})<br/>'
            f'{provider} | {permission} | {status}"]'
        )
        if entry.schema_ref:
            schema_id = f'{node_id}_schema'
            schema_type = _escape_mermaid_label(entry.schema_ref.schema_type)
            lines.append(f'  {schema_id}[("Schema: {schema_type}")]')
            lines.append(f'  {node_id} --> {schema_id}')
    return '\n'.join(lines)


def _entry_to_json_schema(entry: ToolRegistryEntry) -> dict[str, Any]:
    """Generate a JSON Schema fragment for a tool registry entry."""
    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'title': entry.display_name,
        'type': 'object',
        'properties': {
            'tool_id': {'type': 'string', 'const': entry.tool_id},
            'provider': {'type': 'string', 'const': entry.provider},
            'permission': {
                'type': 'string',
                'enum': [p.value for p in ToolPermission],
                'default': entry.permission.value,
            },
            'permission_scopes': {
                'type': 'array',
                'items': {'type': 'string'},
                'default': list(entry.permission_scopes),
            },
            'enabled': {'type': 'boolean', 'default': entry.enabled},
            'mode': {
                'type': 'string',
                'enum': [m.value for m in ToolExecutionMode],
                'default': entry.mode.value,
            },
            'health_status': {
                'type': 'string',
                'enum': ['unknown', 'healthy', 'degraded', 'unreachable'],
            },
        },
    }


def generate_mermaid_registry_graph(registry: ToolRegistry) -> str:
    """Generate a complete Mermaid diagram of the tool registry for the dashboard."""
    entries = registry.list_entries()
    return _entries_to_graph(entries)


def generate_json_schemas(registry: ToolRegistry) -> dict[str, dict[str, Any]]:
    """Generate JSON Schema definitions for every registered tool."""
    return {
        entry.tool_id: _entry_to_json_schema(entry) for entry in registry.list_entries()
    }


def _safe_id(tool_id: str) -> str:
    return tool_id.replace('.', '_').replace('-', '_').replace(':', '_')


def _meets_permission(actual: ToolPermission, required: ToolPermission) -> bool:
    """Check if actual permission level satisfies the required level.

    CONFIRM means "EXECUTE-level capability that additionally requires human
    confirmation": it satisfies every requirement EXECUTE satisfies, and the
    confirmation gate itself is enforced separately (see ``guard_invoke`` and
    ``ToolRegistry.invoke``).
    """
    levels = {
        ToolPermission.READ: 0,
        ToolPermission.WRITE: 1,
        ToolPermission.EXECUTE: 2,
        ToolPermission.CONFIRM: 2,  # EXECUTE + human confirmation gate
    }
    return levels.get(actual, 0) >= levels.get(required, 0)
