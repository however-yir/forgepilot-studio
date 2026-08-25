from openhands.forgepilot.control_plane.task_protocol import (
    TaskPhase,
    is_valid_phase_transition,
    select_verification_commands,
    validate_phase_sequence,
)


def test_select_verification_commands_with_aliases():
    assert select_verification_commands('py') == ['pytest -q']
    assert select_verification_commands('ts') == [
        'npm run typecheck',
        'npm test -- --runInBand',
    ]


def test_select_verification_commands_fallback():
    assert select_verification_commands('unknown') == [
        "echo 'No built-in verifier; define project-specific command.'"
    ]


def test_phase_transition_rules():
    assert is_valid_phase_transition(None, TaskPhase.PLAN)
    assert is_valid_phase_transition(TaskPhase.PLAN, TaskPhase.PLAN)
    assert is_valid_phase_transition(TaskPhase.PLAN, TaskPhase.EXECUTE)
    assert not is_valid_phase_transition(TaskPhase.PLAN, TaskPhase.REPORT)


def test_validate_phase_sequence_complete():
    sequence = [
        TaskPhase.PLAN,
        TaskPhase.EXECUTE,
        TaskPhase.VERIFY,
        TaskPhase.REPORT,
    ]
    assert validate_phase_sequence(sequence)


def test_validate_phase_sequence_incomplete():
    sequence = [TaskPhase.PLAN, TaskPhase.EXECUTE, TaskPhase.VERIFY]
    assert not validate_phase_sequence(sequence)


def test_validate_phase_sequence_accepts_in_progress_prefix():
    """A real-time trace from an in-progress task is a valid protocol prefix.

    The original ``validate_phase_sequence`` rejected any sequence that did
    not end at ``REPORT``, which made it impossible to validate a live trace
    from a task still running. The ``require_complete=False`` mode is the
    supported way to validate an in-progress trace.
    """
    prefixes = [
        [TaskPhase.PLAN],
        [TaskPhase.PLAN, TaskPhase.EXECUTE],
        [TaskPhase.PLAN, TaskPhase.EXECUTE, TaskPhase.VERIFY],
        # Same-phase retries are also legal.
        [TaskPhase.PLAN, TaskPhase.PLAN, TaskPhase.EXECUTE],
    ]
    for prefix in prefixes:
        assert validate_phase_sequence(prefix, require_complete=False), prefix

    # Illegal transitions are still rejected in prefix mode.
    assert not validate_phase_sequence(
        [TaskPhase.PLAN, TaskPhase.REPORT], require_complete=False
    )
    assert not validate_phase_sequence([TaskPhase.EXECUTE], require_complete=False)


def test_validate_phase_sequence_default_still_requires_complete():
    """Default behaviour (require_complete=True) still demands a full trace.

    This protects existing callers that depend on the contract that
    ``validate_phase_sequence`` returns True only for completed runs.
    """
    complete = [
        TaskPhase.PLAN,
        TaskPhase.EXECUTE,
        TaskPhase.VERIFY,
        TaskPhase.REPORT,
    ]
    assert validate_phase_sequence(complete)

    # Empty sequence is not a valid trace at all.
    assert not validate_phase_sequence([])
