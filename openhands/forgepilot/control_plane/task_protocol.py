from __future__ import annotations

from enum import Enum
from typing import Iterable, Literal

from pydantic import BaseModel, Field


class TaskPhase(str, Enum):
    PLAN = 'plan'
    EXECUTE = 'execute'
    VERIFY = 'verify'
    REPORT = 'report'


DEFAULT_TASK_PROTOCOL: tuple[TaskPhase, ...] = (
    TaskPhase.PLAN,
    TaskPhase.EXECUTE,
    TaskPhase.VERIFY,
    TaskPhase.REPORT,
)


class ChangeBoundary(BaseModel):
    """Limits where an agent is allowed to make file edits."""

    allowed_paths: list[str] = Field(default_factory=list)
    allowed_file_extensions: list[str] = Field(default_factory=list)
    blocked_path_patterns: list[str] = Field(default_factory=list)


class TaskExecutionPolicy(BaseModel):
    """Execution policy used by ForgePilot for runtime guardrails."""

    confirmation_mode: Literal['auto', 'on-request', 'manual'] = 'on-request'
    network_access: Literal['deny', 'allowlist', 'open'] = 'allowlist'
    readonly_research_mode: bool = False
    review_mode: bool = False
    handoff_mode: bool = False
    max_self_heal_rounds: int = Field(default=2, ge=0, le=10)


class TaskSpec(BaseModel):
    """Task metadata captured before execution starts."""

    title: str
    objective: str
    language: str = 'generic'
    acceptance_criteria: list[str] = Field(default_factory=list)
    change_boundary: ChangeBoundary = Field(default_factory=ChangeBoundary)
    execution_policy: TaskExecutionPolicy = Field(default_factory=TaskExecutionPolicy)


_VERIFICATION_COMMANDS: dict[str, list[str]] = {
    'python': ['pytest -q'],
    'javascript': ['npm test -- --runInBand'],
    'typescript': ['npm run typecheck', 'npm test -- --runInBand'],
    'java': ['mvn -q test'],
    'kotlin': ['./gradlew test'],
    'go': ['go test ./...'],
    'rust': ['cargo test'],
    'csharp': ['dotnet test'],
    'generic': ["echo 'No built-in verifier; define project-specific command.'"],
}


def _normalize_language(language: str) -> str:
    value = language.strip().lower()
    aliases = {
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'node': 'javascript',
        'golang': 'go',
        'cs': 'csharp',
    }
    return aliases.get(value, value or 'generic')


def select_verification_commands(language: str) -> list[str]:
    """Return default verification commands by project language."""

    normalized = _normalize_language(language)
    return _VERIFICATION_COMMANDS.get(normalized, _VERIFICATION_COMMANDS['generic'])


def is_valid_phase_transition(
    current_phase: TaskPhase | None,
    next_phase: TaskPhase,
) -> bool:
    """Allow the same phase retry or exactly one-step forward progression."""

    if current_phase is None:
        return next_phase == TaskPhase.PLAN

    if next_phase == current_phase:
        return True

    order = list(DEFAULT_TASK_PROTOCOL)
    current_index = order.index(current_phase)
    next_index = order.index(next_phase)
    return next_index == current_index + 1


def validate_phase_sequence(
    phases: Iterable[TaskPhase],
    *,
    require_complete: bool = True,
) -> bool:
    """Validate a phase sequence under the fixed task protocol.

    When ``require_complete`` is True (the default) the sequence must end at
    ``REPORT`` — this is what callers want when validating a finished task
    trace. When False, a prefix is accepted as long as every transition is
    legal, so a real-time trace from an in-progress task (e.g. ``[PLAN,
    EXECUTE]`` or ``[PLAN, EXECUTE, VERIFY]``) can be validated without
    waiting for the task to reach ``REPORT``.
    """

    previous: TaskPhase | None = None
    last: TaskPhase | None = None
    for phase in phases:
        if not is_valid_phase_transition(previous, phase):
            return False
        previous = phase
        last = phase

    if last is None:
        # An empty sequence is not a valid protocol trace at all.
        return False

    if require_complete:
        return last == TaskPhase.REPORT
    return True
