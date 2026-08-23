from __future__ import annotations

from openhands.forgepilot.tool_registry.registry import ToolRegistry
from openhands.forgepilot.tool_registry.schema import (
    ToolExecutionMode,
    ToolPermission,
    ToolRegistryEntry,
)
from openhands.forgepilot.tool_registry.shell_tools import (
    ShellToolSpec,
    execute_shell_tool,
)


def _register_shell_tool(
    registry: ToolRegistry,
    *,
    permission: ToolPermission = ToolPermission.EXECUTE,
    enabled: bool = True,
) -> ShellToolSpec:
    registry.register(
        ToolRegistryEntry(
            tool_id='shell.format',
            display_name='Shell Format',
            provider='shell',
            permission=permission,
            enabled=enabled,
            mode=ToolExecutionMode.LIVE,
        )
    )
    return ShellToolSpec(
        tool_id='shell.format',
        display_name='Shell Format',
        command='sh',
        args=['-lc', 'printf "{{value}}"'],
    )


def test_execute_shell_tool_records_success():
    registry = ToolRegistry.from_builtin_templates()
    spec = _register_shell_tool(registry)
    result, record = execute_shell_tool(
        registry,
        spec,
        parameters={'value': 'forgepilot'},
        trace_id='trace-shell-success',
    )
    assert result.exit_code == 0
    assert result.stdout == 'forgepilot'
    assert record.error is None
    assert record.trace_id == 'trace-shell-success'
    assert 'command: sh -lc' in record.output_summary


def test_execute_shell_tool_requires_confirmation_for_confirm_permission():
    registry = ToolRegistry.from_builtin_templates()
    spec = _register_shell_tool(registry, permission=ToolPermission.CONFIRM)
    result, record = execute_shell_tool(
        registry,
        spec,
        parameters={'value': 'forgepilot'},
        confirmed=False,
    )
    assert result.exit_code == 126
    assert result.stderr == 'confirmation is required for this tool'
    assert record.error == 'confirmation required'


def test_execute_shell_tool_rejects_non_execute_permission():
    registry = ToolRegistry.from_builtin_templates()
    spec = _register_shell_tool(registry, permission=ToolPermission.READ)
    result, record = execute_shell_tool(
        registry,
        spec,
        parameters={'value': 'forgepilot'},
    )
    assert result.exit_code == 126
    assert 'does not allow shell execution' in result.stderr
    assert record.error == 'permission denied'


def test_execute_shell_tool_rejects_disabled_tool():
    registry = ToolRegistry.from_builtin_templates()
    spec = _register_shell_tool(registry, enabled=False)
    result, record = execute_shell_tool(
        registry,
        spec,
        parameters={'value': 'forgepilot'},
    )
    assert result.exit_code == 126
    assert result.stderr == 'tool is disabled'
    assert record.error == 'tool is disabled'


# ── M-3: timeout and unknown-tool handling ───────────


def test_execute_shell_tool_records_timeout_with_exit_code_124():
    registry = ToolRegistry.from_builtin_templates()
    registry.register(
        ToolRegistryEntry(
            tool_id='shell.sleep',
            display_name='Sleep',
            provider='shell',
            permission=ToolPermission.EXECUTE,
            mode=ToolExecutionMode.LIVE,
        )
    )
    spec = ShellToolSpec(
        tool_id='shell.sleep',
        display_name='Sleep',
        command='sh',
        args=['-c', 'sleep 5'],
        timeout_seconds=1,
    )
    result, record = execute_shell_tool(
        registry,
        spec,
        trace_id='trace-timeout',
    )
    assert result.exit_code == 124
    assert 'timed out after 1s' in result.stderr
    assert 'timed out after 1s' in record.error
    assert record.trace_id == 'trace-timeout'
    assert 'exit_code: 124' in record.output_summary


def test_execute_shell_tool_unknown_tool_returns_126_not_keyerror():
    """Legacy path (no guard): unknown tools must be reported, not crash."""
    registry = ToolRegistry.from_builtin_templates()
    spec = ShellToolSpec(
        tool_id='shell.nope',
        display_name='Missing',
        command='echo',
        args=['hi'],
    )
    result, record = execute_shell_tool(registry, spec)
    assert result.exit_code == 126
    assert 'unknown tool' in result.stderr
    assert 'unknown tool' in (record.error or '')


def test_execute_shell_tool_unknown_tool_with_guard_audited():
    """Guard path: unknown tools are denied by the guard and still audited."""
    from openhands.forgepilot.tool_registry.enforcement import ToolAccessGuard

    registry = ToolRegistry.from_builtin_templates()
    guard = ToolAccessGuard(registry)
    spec = ShellToolSpec(
        tool_id='shell.nope',
        display_name='Missing',
        command='echo',
        args=['hi'],
    )
    result, record = execute_shell_tool(registry, spec, guard=guard)
    assert result.exit_code == 126
    assert 'unknown tool' in result.stderr
    assert 'unknown tool' in (record.error or '')
    assert 'unknown tool' in guard.violations[-1].detail


def test_execute_shell_tool_guard_confirmed_confirm_tool_runs():
    """Guard path: a CONFIRM shell tool with confirmed=True must execute."""
    from openhands.forgepilot.tool_registry.enforcement import ToolAccessGuard

    registry = ToolRegistry.from_builtin_templates()
    registry.register(
        ToolRegistryEntry(
            tool_id='shell.confirm.echo',
            display_name='Confirmed Echo',
            provider='shell',
            permission=ToolPermission.CONFIRM,
            mode=ToolExecutionMode.LIVE,
        )
    )
    guard = ToolAccessGuard(registry)
    spec = ShellToolSpec(
        tool_id='shell.confirm.echo',
        display_name='Confirmed Echo',
        command='printf',
        args=['{{value}}'],
    )
    result, record = execute_shell_tool(
        registry,
        spec,
        parameters={'value': 'approved'},
        confirmed=True,
        guard=guard,
    )
    assert result.exit_code == 0
    assert result.stdout == 'approved'
    assert record.error is None
