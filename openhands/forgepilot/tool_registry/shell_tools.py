from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from pydantic import BaseModel, Field

from .registry import ToolRegistry
from .schema import ToolPermission

if TYPE_CHECKING:
    from .enforcement import ToolAccessGuard


class ShellToolSpec(BaseModel):
    tool_id: str
    display_name: str
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    timeout_seconds: int = Field(default=120, ge=1, le=1800)


class ShellToolResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    command_line: str


def _build_command(spec: ShellToolSpec, parameters: Mapping[str, object]) -> list[str]:
    command = [spec.command]
    for arg in spec.args:
        rendered = arg
        for key, value in parameters.items():
            rendered = rendered.replace(f'{{{{{key}}}}}', str(value))
        command.append(rendered)
    return command


def _summarize_result(result: ShellToolResult) -> str:
    lines = [
        f'command: {result.command_line}',
        f'exit_code: {result.exit_code}',
    ]
    if result.stdout:
        lines.append(f'stdout: {result.stdout.strip()}')
    if result.stderr:
        lines.append(f'stderr: {result.stderr.strip()}')
    return '\n'.join(lines)


def execute_shell_tool(
    registry: ToolRegistry,
    spec: ShellToolSpec,
    *,
    parameters: Mapping[str, object] | None = None,
    trace_id: str | None = None,
    workspace_root: Path | None = None,
    confirmed: bool = False,
    guard: ToolAccessGuard | None = None,
) -> tuple[ShellToolResult, object]:
    parameters = parameters or {}
    command = _build_command(spec, parameters)
    command_line = shlex.join(command)

    # ── permission / enablement checks ────────────────
    # When a ToolAccessGuard is provided, delegate all permission and
    # enablement decisions to it so every tool-call entry point enforces
    # the same policy.  The inline checks below serve as the backwards-
    # compatible fallback for callers that do not supply a guard.

    if guard is not None:
        # Resolve cwd for workspace boundary checking.
        target = str(spec.cwd) if spec.cwd else None
        if not guard.check(
            spec.tool_id,
            required=ToolPermission.EXECUTE,
            target_path=target,
        ):
            detail = guard.violations[-1].detail if guard.violations else 'denied'
            result = ShellToolResult(
                exit_code=126,
                stdout='',
                stderr=detail,
                command_line=command_line,
            )
            record = registry.record_call(
                spec.tool_id,
                parameters=parameters,
                output=_summarize_result(result),
                duration_ms=0,
                error=detail,
                trace_id=trace_id,
            )
            return result, record
        # guard.check passed, so the entry is guaranteed to exist.
        entry = registry.get_entry(spec.tool_id)
    else:
        try:
            entry = registry.get_entry(spec.tool_id)
        except KeyError:
            result = ShellToolResult(
                exit_code=126,
                stdout='',
                stderr=f'unknown tool: {spec.tool_id}',
                command_line=command_line,
            )
            record = registry.record_call(
                spec.tool_id,
                parameters=parameters,
                output=_summarize_result(result),
                duration_ms=0,
                error=f'unknown tool: {spec.tool_id}',
                trace_id=trace_id,
            )
            return result, record
        # Inline checks (legacy path — no guard available).
        if not entry.enabled:
            result = ShellToolResult(
                exit_code=126,
                stdout='',
                stderr='tool is disabled',
                command_line=command_line,
            )
            record = registry.record_call(
                spec.tool_id,
                parameters=parameters,
                output=_summarize_result(result),
                duration_ms=0,
                error='tool is disabled',
                trace_id=trace_id,
            )
            return result, record

        if entry.permission not in {ToolPermission.EXECUTE, ToolPermission.CONFIRM}:
            result = ShellToolResult(
                exit_code=126,
                stdout='',
                stderr=f'permission {entry.permission.value} does not allow shell execution',
                command_line=command_line,
            )
            record = registry.record_call(
                spec.tool_id,
                parameters=parameters,
                output=_summarize_result(result),
                duration_ms=0,
                error='permission denied',
                trace_id=trace_id,
            )
            return result, record

    # CONFIRM check applies regardless of guard presence — it is a
    # runtime user-confirmation gate, not a permission-level gate.
    if entry.permission == ToolPermission.CONFIRM and not confirmed:
        result = ShellToolResult(
            exit_code=126,
            stdout='',
            stderr='confirmation is required for this tool',
            command_line=command_line,
        )
        record = registry.record_call(
            spec.tool_id,
            parameters=parameters,
            output=_summarize_result(result),
            duration_ms=0,
            error='confirmation required',
            trace_id=trace_id,
        )
        return result, record

    if spec.cwd:
        cwd = Path(spec.cwd)
    elif workspace_root is not None:
        cwd = workspace_root
    else:
        cwd = Path.cwd()

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=spec.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        detail = f'timed out after {spec.timeout_seconds}s'
        stderr = exc.stderr if isinstance(exc.stderr, str) else detail
        if not stderr:
            stderr = detail
        result = ShellToolResult(
            exit_code=124,  # conventional timeout exit status (GNU timeout)
            stdout=exc.stdout if isinstance(exc.stdout, str) else '',
            stderr=stderr,
            command_line=command_line,
        )
        record = registry.record_call(
            spec.tool_id,
            parameters=parameters,
            output=_summarize_result(result),
            duration_ms=elapsed_ms,
            error=detail,
            trace_id=trace_id,
        )
        return result, record
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    result = ShellToolResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        command_line=command_line,
    )

    record = registry.record_call(
        spec.tool_id,
        parameters=parameters,
        output=_summarize_result(result),
        duration_ms=elapsed_ms,
        error=None
        if completed.returncode == 0
        else f'exit code {completed.returncode}',
        trace_id=trace_id,
    )
    return result, record
