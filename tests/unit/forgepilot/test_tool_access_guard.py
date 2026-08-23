"""Tests for ToolAccessGuard path resolution and workspace boundary enforcement.

Covers: directory-traversal (../), absolute paths, symlinks, Windows-style
separators, and legal relative paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openhands.forgepilot.tool_registry.enforcement import ToolAccessGuard
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

# ── helpers ───────────────────────────────────────────


def _make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolRegistryEntry(
            tool_id='file.read',
            display_name='File Read',
            provider='core',
            permission=ToolPermission.READ,
            mode=ToolExecutionMode.MOCK,
        )
    )
    registry.register(
        ToolRegistryEntry(
            tool_id='file.write',
            display_name='File Write',
            provider='core',
            permission=ToolPermission.WRITE,
            mode=ToolExecutionMode.MOCK,
        )
    )
    return registry


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Create a temp workspace with a symlink that points outside."""
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'app.py').write_text('print("hello")')

    # Create an external directory and symlink to it from workspace.
    external = tmp_path.parent / 'external_dir'
    external.mkdir(exist_ok=True)
    (external / 'secret.txt').write_text('SENSITIVE')

    link = tmp_path / 'leak'
    link.symlink_to(external)

    return tmp_path


# ── basic checks (no workspace) ──────────────────────


class TestGuardNoWorkspace:
    """Guard works without workspace_root (backwards-compat)."""

    def test_allows_known_tool(self):
        registry = _make_registry()
        guard = ToolAccessGuard(registry)
        assert guard.check('file.read') is True
        assert guard.violations == []

    def test_rejects_unknown_tool(self):
        registry = _make_registry()
        guard = ToolAccessGuard(registry)
        assert guard.check('nonexistent') is False
        assert len(guard.violations) == 1
        assert 'unknown tool' in guard.violations[0].detail

    def test_rejects_disabled_tool(self):
        registry = _make_registry()
        registry.set_enabled('file.read', False)
        guard = ToolAccessGuard(registry)
        assert guard.check('file.read') is False
        assert 'disabled' in guard.violations[0].detail

    def test_rejects_insufficient_permission(self):
        registry = _make_registry()
        guard = ToolAccessGuard(registry)
        assert guard.check('file.read', required=ToolPermission.WRITE) is False
        assert 'insufficient permission' in guard.violations[0].detail


# ── directory-traversal (../) ────────────────────────


class TestTraversalAttacks:
    """Paths containing ../ must not escape the workspace."""

    def test_dotdot_blocked(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        assert guard.check('file.read', target_path='../outside') is False
        assert 'escapes workspace' in guard.violations[0].detail

    def test_multiple_dotdot_blocked(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        assert guard.check('file.read', target_path='src/../../etc/passwd') is False
        assert 'escapes workspace' in guard.violations[0].detail

    def test_leading_dotdot_blocked(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        assert guard.check('file.read', target_path='../../etc/shadow') is False


# ── absolute path ────────────────────────────────────


class TestAbsolutePath:
    """Absolute paths outside the workspace must be rejected."""

    def test_absolute_path_outside(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        assert guard.check('file.read', target_path='/etc/passwd') is False
        assert 'escapes workspace' in guard.violations[0].detail

    def test_absolute_path_inside_workspace(self, workspace: Path):
        """An absolute path that resolves inside the workspace should be allowed."""
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
        )
        abs_inside = str(workspace / 'src' / 'app.py')
        assert guard.check('file.read', target_path=abs_inside) is True


# ── symlinks ─────────────────────────────────────────


class TestSymlinks:
    """Symlinks pointing outside the workspace must be caught after resolve."""

    def test_symlink_escape(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        # 'leak' is a symlink to a directory outside workspace
        assert guard.check('file.read', target_path='leak/secret.txt') is False
        assert 'escapes workspace' in guard.violations[0].detail

    def test_symlink_inside_workspace(self, workspace: Path):
        """A symlink whose target stays inside workspace is allowed."""
        # Create an internal symlink: link_app -> src/app.py
        link = workspace / 'link_app'
        link.symlink_to(workspace / 'src' / 'app.py')

        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
        )
        assert guard.check('file.read', target_path='link_app') is True


# ── Windows-style separators ─────────────────────────


class TestWindowsSeparators:
    """Backslash separators must be normalised and still checked."""

    def test_backslash_traversal_blocked(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        assert guard.check('file.read', target_path='src\\..\\..\\etc\\passwd') is False
        assert 'escapes workspace' in guard.violations[0].detail

    def test_backslash_legal_path_allowed(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
        )
        assert guard.check('file.read', target_path='src\\app.py') is True


# ── legal relative paths ─────────────────────────────


class TestLegalPaths:
    """Normal relative paths should pass through cleanly."""

    def test_simple_relative(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
        )
        assert guard.check('file.read', target_path='src/app.py') is True

    def test_dot_relative(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
        )
        assert guard.check('file.read', target_path='./src/app.py') is True

    def test_no_target_path(self, workspace: Path):
        """Omitting target_path should not trigger path checks."""
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        assert guard.check('file.read') is True


# ── allowlist / blocklist with resolved paths ────────


class TestPathRules:
    """Allowlist and blocklist should match against the resolved relative path."""

    def test_allowlist_filters(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['src/*'],
        )
        # src/app.py matches src/*
        assert guard.check('file.read', target_path='src/app.py') is True

        # A file in a different dir does not match
        (workspace / 'docs').mkdir()
        (workspace / 'docs' / 'readme.md').write_text('hi')
        assert guard.check('file.read', target_path='docs/readme.md') is False

    def test_blocklist_filters(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
            path_blocklist=['*.pyc', '__pycache__/*'],
        )
        assert guard.check('file.read', target_path='src/app.py') is True

        (workspace / '__pycache__').mkdir()
        (workspace / '__pycache__' / 'app.pyc').write_text('x')
        assert guard.check('file.read', target_path='__pycache__/app.pyc') is False

    def test_blocklist_takes_priority_over_allowlist(self, workspace: Path):
        """Blocklist must win when a path matches both allowlist and blocklist."""
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
            path_blocklist=['src/*'],
        )
        # src/app.py matches both allowlist '*' and blocklist 'src/*' — must be blocked
        assert guard.check('file.read', target_path='src/app.py') is False
        assert 'blocked' in guard.violations[-1].detail

        # A path that matches allowlist but not blocklist should still pass
        (workspace / 'docs').mkdir()
        (workspace / 'docs' / 'readme.md').write_text('hi')
        assert guard.check('file.read', target_path='docs/readme.md') is True


# ── guard_invoke integration ────────────────────────


class TestGuardInvoke:
    """guard_invoke should raise PermissionError for blocked paths."""

    def test_invoke_blocks_traversal(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        with pytest.raises(PermissionError, match='escapes workspace'):
            guard.guard_invoke(
                'file.read',
                {},
                target_path='../outside',
            )

    def test_invoke_allows_valid_path(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
        )
        # In MOCK mode this should succeed
        record = guard.guard_invoke(
            'file.read',
            {'path': 'src/app.py'},
            target_path='src/app.py',
        )
        assert record.error is None

    def test_invoke_non_blocking_mode(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        guard._block_on_violation = False
        record = guard.guard_invoke(
            'file.read',
            {},
            target_path='../outside',
        )
        assert 'permission denied' in record.error
        assert 'escapes workspace' in record.error


# ── entry point integration: shell ────────────────


class TestShellEntryPoint:
    """Shell tool entry point must go through ToolAccessGuard."""

    def test_shell_guard_blocks_cwd_escape(self, workspace: Path):
        """A shell tool whose cwd escapes the workspace must be rejected."""
        registry = ToolRegistry()
        registry.register(
            ToolRegistryEntry(
                tool_id='shell.echo',
                display_name='Echo',
                provider='shell',
                permission=ToolPermission.EXECUTE,
                mode=ToolExecutionMode.LIVE,
            )
        )
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        spec = ShellToolSpec(
            tool_id='shell.echo',
            display_name='Echo',
            command='echo',
            args=['hello'],
            cwd=str(workspace.parent),  # outside workspace
        )
        result, record = execute_shell_tool(
            registry,
            spec,
            guard=guard,
        )
        assert result.exit_code == 126
        assert 'escapes workspace' in result.stderr

    def test_shell_guard_allows_cwd_inside(self, workspace: Path):
        """A shell tool whose cwd is inside workspace must succeed."""
        registry = ToolRegistry()
        registry.register(
            ToolRegistryEntry(
                tool_id='shell.echo',
                display_name='Echo',
                provider='shell',
                permission=ToolPermission.EXECUTE,
                mode=ToolExecutionMode.LIVE,
            )
        )
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        spec = ShellToolSpec(
            tool_id='shell.echo',
            display_name='Echo',
            command='echo',
            args=['hello'],
            cwd=str(workspace / 'src'),
        )
        result, record = execute_shell_tool(
            registry,
            spec,
            guard=guard,
        )
        assert result.exit_code == 0
        assert 'hello' in result.stdout
        assert record.error is None

    def test_shell_legacy_path_without_guard(self, workspace: Path):
        """Without a guard, shell_tools falls back to inline permission checks."""
        registry = ToolRegistry()
        registry.register(
            ToolRegistryEntry(
                tool_id='shell.echo',
                display_name='Echo',
                provider='shell',
                permission=ToolPermission.READ,  # insufficient for EXECUTE
                mode=ToolExecutionMode.LIVE,
            )
        )
        spec = ShellToolSpec(
            tool_id='shell.echo',
            display_name='Echo',
            command='echo',
            args=['hello'],
        )
        result, record = execute_shell_tool(registry, spec)
        assert result.exit_code == 126
        assert 'does not allow shell execution' in result.stderr


# ── entry point integration: HTTP/MCP via guard_invoke ──


class TestHTTPEndPoint:
    """HTTP/MCP tool calls go through guard_invoke → registry.invoke."""

    def test_http_invoke_via_guard_blocks_traversal(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(registry, workspace_root=workspace)
        with pytest.raises(PermissionError, match='escapes workspace'):
            guard.guard_invoke(
                'file.read',
                {'url': 'http://example.com'},
                target_path='../../etc/passwd',
            )

    def test_http_invoke_via_guard_allows_valid(self, workspace: Path):
        registry = _make_registry()
        guard = ToolAccessGuard(
            registry,
            workspace_root=workspace,
            path_allowlist=['*'],
        )
        record = guard.guard_invoke(
            'file.read',
            {'url': 'http://example.com'},
            target_path='src/app.py',
        )
        assert record.error is None


# ── CONFIRM permission semantics (M-2) ────────────────


class TestConfirmPermission:
    """CONFIRM = EXECUTE-level capability + a human confirmation gate."""

    @staticmethod
    def _registry_with_confirm_tool() -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolRegistryEntry(
                tool_id='connector.github',
                display_name='GitHub',
                provider='github',
                permission=ToolPermission.CONFIRM,
                mode=ToolExecutionMode.MOCK,
            )
        )
        return registry

    def test_check_confirms_satisfies_execute_requirement(self):
        """Guard path: CONFIRM tools must satisfy EXECUTE-level checks.

        Previously CONFIRM compared as level 0, so guard-based callers could
        never execute CONFIRM tools even after approval.
        """
        registry = self._registry_with_confirm_tool()
        guard = ToolAccessGuard(registry)
        assert guard.check('connector.github', required=ToolPermission.EXECUTE) is True
        assert guard.violations == []

    def test_check_confirm_satisfies_read_and_write_requirements(self):
        registry = self._registry_with_confirm_tool()
        guard = ToolAccessGuard(registry)
        assert guard.check('connector.github', required=ToolPermission.READ) is True
        assert guard.check('connector.github', required=ToolPermission.WRITE) is True

    def test_guard_invoke_confirm_tool_blocked_without_confirmation(self):
        """guard_invoke path: unconfirmed CONFIRM tools must be denied."""
        registry = self._registry_with_confirm_tool()
        guard = ToolAccessGuard(registry)
        with pytest.raises(PermissionError, match='confirmation required'):
            guard.guard_invoke('connector.github', {})
        assert 'confirmation required' in guard.violations[-1].detail

    def test_guard_invoke_confirm_tool_non_blocking_records_error(self):
        registry = self._registry_with_confirm_tool()
        guard = ToolAccessGuard(registry)
        guard._block_on_violation = False
        record = guard.guard_invoke('connector.github', {})
        assert 'confirmation required' in record.error

    def test_guard_invoke_confirm_tool_executes_when_confirmed(self):
        registry = self._registry_with_confirm_tool()
        guard = ToolAccessGuard(registry)
        record = guard.guard_invoke('connector.github', {}, confirmed=True)
        assert record.error is None

    def test_registry_invoke_confirm_tool_gated_without_guard(self):
        """Unguarded ToolRegistry.invoke must also enforce the confirmation."""
        registry = self._registry_with_confirm_tool()
        record = registry.invoke('connector.github', {})
        assert record.error == 'confirmation required for CONFIRM tools'

        confirmed_record = registry.invoke('connector.github', {}, confirmed=True)
        assert confirmed_record.error is None

    def test_read_tool_invoke_unaffected_by_confirmation_gate(self):
        registry = _make_registry()
        record = registry.invoke('file.read', {})
        assert record.error is None
